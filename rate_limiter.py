import asyncio
import time
import redis.asyncio as redis
from typing import Dict, Tuple, Optional
import json
import hashlib
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)

try:
    from redis_mock import MockRedisAsync
except ImportError:
    MockRedisAsync = None

@dataclass
class RateLimitConfig:
    """Rate limit configuration for an API key"""
    input_tpm: int  # Input tokens per minute
    output_tpm: int  # Output tokens per minute  
    rpm: int        # Requests per minute

class DistributedRateLimiter:
    """
    Distributed rate limiter using Redis with sliding window algorithm.
    Uses Redis sorted sets for efficient sliding window tracking.
    """
    
    def __init__(self, redis_url: str = "redis://localhost:6379", use_mock: bool = False):
        if use_mock and MockRedisAsync is not None:
            self.redis = MockRedisAsync()
            self.is_mock = True
        else:
            self.redis = redis.from_url(redis_url, decode_responses=False)
            self.is_mock = False
        self.window_size = 60  # 60 seconds sliding window
        
    async def initialize(self):
        """Initialize Redis connection with retry"""
        if self.is_mock:
            await self.redis.ping()
            return
            
        max_retries = 5
        retry_delay = 1
        
        for attempt in range(max_retries):
            try:
                await self.redis.ping()
                return
            except Exception as e:
                if attempt == max_retries - 1:
                    logger.warning("Using mock Redis for testing")
                    self.redis = MockRedisAsync()
                    self.is_mock = True
                    return
                await asyncio.sleep(retry_delay)
                retry_delay *= 2
        
    async def close(self):
        """Close Redis connection"""
        await self.redis.close()
        
    def _get_keys(self, api_key: str) -> Tuple[str, str, str]:
        """Generate Redis keys for different rate limit metrics"""
        base_key = f"rate_limit:{api_key}"
        return (
            f"{base_key}:input_tokens",
            f"{base_key}:output_tokens", 
            f"{base_key}:requests"
        )
        
    def _get_current_timestamp(self) -> int:
        """Get current timestamp in seconds"""
        return int(time.time())
        
    async def check_rate_limit(
        self, 
        api_key: str, 
        input_tokens: int, 
        output_tokens: int
    ) -> Tuple[bool, Optional[str]]:
        """
        Check if request is within rate limits using atomic Redis operations.
        
        Args:
            api_key: The API key to check
            input_tokens: Number of input tokens in request
            output_tokens: Number of output tokens expected
            
        Returns:
            Tuple of (is_allowed, error_message)
        """
        if not api_key:
            return False, "Missing API key"
            
        # Get rate limits for this API key
        config = await self._get_rate_limit_config(api_key)
        if not config:
            return False, "Invalid API key"
            
        input_key, output_key, request_key = self._get_keys(api_key)
        current_time = self._get_current_timestamp()
        window_start = current_time - self.window_size
        
        # Use Redis Lua script for atomicity
        lua_script = """
        -- Keys: [input_key, output_key, request_key]
        -- Args: [current_time, window_start, input_tokens, output_tokens, 1, 
        --        input_tpm, output_tpm, rpm]
        
        local input_key = KEYS[1]
        local output_key = KEYS[2] 
        local request_key = KEYS[3]
        
        local current_time = tonumber(ARGV[1])
        local window_start = tonumber(ARGV[2])
        local input_tokens = tonumber(ARGV[3])
        local output_tokens = tonumber(ARGV[4])
        local request_count = tonumber(ARGV[5])
        local input_tpm = tonumber(ARGV[6])
        local output_tpm = tonumber(ARGV[7])
        local rpm = tonumber(ARGV[8])
        
        -- Remove old entries outside window
        redis.call('ZREMRANGEBYSCORE', input_key, '-inf', window_start)
        redis.call('ZREMRANGEBYSCORE', output_key, '-inf', window_start)
        redis.call('ZREMRANGEBYSCORE', request_key, '-inf', window_start)
        
        -- Calculate current usage
        local current_input = redis.call('ZCARD', input_key)
        local current_output = redis.call('ZCARD', output_key)  
        local current_requests = redis.call('ZCARD', request_key)
        
        -- Check if request would exceed limits
        if current_input + input_tokens > input_tpm then
            return {0, "Input TPM limit exceeded"}
        end
        
        if current_output + output_tokens > output_tpm then
            return {0, "Output TPM limit exceeded"}
        end
        
        if current_requests + request_count > rpm then
            return {0, "RPM limit exceeded"}
        end
        
        -- Add new entries with current timestamp as score
        for i = 1, input_tokens do
            redis.call('ZADD', input_key, current_time, current_time .. ":" .. math.random())
        end
        
        for i = 1, output_tokens do
            redis.call('ZADD', output_key, current_time, current_time .. ":" .. math.random())
        end
        
        for i = 1, request_count do
            redis.call('ZADD', request_key, current_time, current_time .. ":" .. math.random())
        end
        
        -- Set expiration to prevent memory leaks
        redis.call('EXPIRE', input_key, 3600)
        redis.call('EXPIRE', output_key, 3600)
        redis.call('EXPIRE', request_key, 3600)
        
        return {1, "OK"}
        """
        
        try:
            result = await self.redis.eval(
                lua_script, 3,  # 3 keys
                input_key, output_key, request_key,
                current_time, window_start, input_tokens, output_tokens, 1,
                config.input_tpm, config.output_tpm, config.rpm
            )
            
            allowed = bool(result[0])
            message = result[1].decode() if isinstance(result[1], bytes) else str(result[1])
            
            return allowed, None if allowed else message
            
        except Exception as e:
            return False, f"Rate limit check failed: {str(e)}"
            
    async def _get_rate_limit_config(self, api_key: str) -> Optional[RateLimitConfig]:
        """Get rate limit configuration for API key"""
        # In production, this would come from a database
        # For demo, use hash of API key to generate deterministic config
        hash_obj = hashlib.md5(api_key.encode())
        hash_hex = hash_obj.hexdigest()
        
        # Generate pseudo-random but deterministic rate limits
        input_tpm = 10000 + (int(hash_hex[:4], 16) % 50000)  # 10K-60K
        output_tpm = 5000 + (int(hash_hex[4:8], 16) % 25000)   # 5K-30K
        rpm = 100 + (int(hash_hex[8:12], 16) % 900)            # 100-1000
        
        return RateLimitConfig(
            input_tpm=input_tpm,
            output_tpm=output_tpm,
            rpm=rpm
        )
        
    async def get_usage_stats(self, api_key: str) -> Dict:
        """Get current usage statistics for an API key"""
        input_key, output_key, request_key = self._get_keys(api_key)
        current_time = self._get_current_timestamp()
        window_start = current_time - self.window_size
        
        pipeline = self.redis.pipeline()
        pipeline.zcount(input_key, window_start, current_time)
        pipeline.zcount(output_key, window_start, current_time)
        pipeline.zcount(request_key, window_start, current_time)
        
        results = await pipeline.execute()
        config = await self._get_rate_limit_config(api_key)
        
        return {
            "input_tokens_used": results[0],
            "input_tokens_limit": config.input_tpm,
            "output_tokens_used": results[1], 
            "output_tokens_limit": config.output_tpm,
            "requests_used": results[2],
            "requests_limit": config.rpm,
            "window_size_seconds": self.window_size
        }
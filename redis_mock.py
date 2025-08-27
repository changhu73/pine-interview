import asyncio
import time
import uuid
from collections import defaultdict, deque
from typing import Dict, List, Tuple, Optional
import threading

class MockRedis:
    """In-memory mock Redis for testing without Redis server"""
    
    def __init__(self):
        self.data = {}
        self.locks = defaultdict(threading.Lock)
        
    def zadd(self, key: str, *args):
        """Mock ZADD operation"""
        if key not in self.data:
            self.data[key] = deque(maxlen=10000)
            
        # Parse arguments: score1 member1 score2 member2 ...
        args_list = list(args)
        for i in range(0, len(args_list), 2):
            if i + 1 < len(args_list):
                score = args_list[i]
                member = args_list[i + 1]
                self.data[key].append((score, member))
                
        # Keep only recent entries (simulate sliding window)
        current_time = time.time()
        cutoff_time = current_time - 60
        
        self.data[key] = deque(
            [(s, m) for s, m in self.data[key] if s >= cutoff_time],
            maxlen=10000
        )
        
        return len([x for x in args[1::2]])
        
    def zremrangebyscore(self, key: str, min_score: str, max_score: str):
        """Mock ZREMRANGEBYSCORE operation"""
        if key not in self.data:
            return 0
            
        if min_score == '-inf':
            min_score = float('-inf')
        else:
            min_score = float(min_score)
            
        if max_score == '+inf':
            max_score = float('inf')
        else:
            max_score = float(max_score)
            
        original_len = len(self.data[key])
        self.data[key] = deque(
            [(s, m) for s, m in self.data[key] if not (min_score <= s <= max_score)],
            maxlen=10000
        )
        
        return original_len - len(self.data[key])
        
    def zcard(self, key: str):
        """Mock ZCARD operation"""
        return len(self.data.get(key, deque()))
        
    def zcount(self, key: str, min_score: str, max_score: str):
        """Mock ZCOUNT operation"""
        if key not in self.data:
            return 0
            
        if min_score == '-inf':
            min_score = float('-inf')
        else:
            min_score = float(min_score)
            
        if max_score == '+inf':
            max_score = float('inf')
        else:
            max_score = float(max_score)
            
        return len([s for s, _ in self.data[key] if min_score <= s <= max_score])
        
    def expire(self, key: str, seconds: int):
        """Mock EXPIRE operation"""
        return 1
        
    def pipeline(self):
        """Mock pipeline"""
        return MockPipeline(self)
        
    async def ping(self):
        """Mock PING operation"""
        return True
        
    async def close(self):
        """Mock close"""
        pass

class MockPipeline:
    """Mock Redis pipeline"""
    
    def __init__(self, redis):
        self.redis = redis
        self.commands = []
        self.results = []
        
    def zcount(self, key: str, min_score: str, max_score: str):
        """Mock ZCOUNT in pipeline"""
        result = self.redis.zcount(key, min_score, max_score)
        self.results.append(result)
        return self
        
    async def execute(self):
        """Execute pipeline"""
        return self.results

class MockRedisAsync:
    """Async version of mock Redis"""
    
    def __init__(self):
        self.mock = MockRedis()
        
    async def ping(self):
        return self.mock.ping()
        
    async def close(self):
        return self.mock.close()
        
    async def zcount(self, key: str, min_score: str, max_score: str):
        return self.mock.zcount(key, min_score, max_score)
        
    async def zadd(self, key: str, *args):
        return self.mock.zadd(key, *args)
        
    async def zremrangebyscore(self, key: str, min_score: str, max_score: str):
        return self.mock.zremrangebyscore(key, min_score, max_score)
        
    async def zcard(self, key: str):
        return self.mock.zcard(key)
        
    async def expire(self, key: str, seconds: int):
        return self.mock.expire(key, seconds)
        
    def pipeline(self):
        return MockPipeline(self.mock)
        
    async def eval(self, script: str, numkeys: int, *args):
        """Mock EVAL for Lua scripts"""
        return await self._mock_eval(script, numkeys, *args)
        
    async def _mock_eval(self, script: str, numkeys: int, *args):
        """Mock Lua script execution"""
        keys = args[:numkeys]
        argv = args[numkeys:]
        
        # Simplified implementation of the rate limiting logic
        current_time = float(argv[0])
        window_start = float(argv[1])
        input_tokens = int(argv[2])
        output_tokens = int(argv[3])
        request_count = int(argv[4])
        input_tpm = int(argv[5])
        output_tpm = int(argv[6])
        rpm = int(argv[7])
        
        # Remove old entries
        for key in keys:
            await self.zremrangebyscore(key, '-inf', str(window_start))
            
        # Check limits
        input_key, output_key, request_key = keys
        
        current_input = await self.zcount(input_key, str(window_start), str(current_time))
        current_output = await self.zcount(output_key, str(window_start), str(current_time))
        current_requests = await self.zcount(request_key, str(window_start), str(current_time))
        
        if current_input + input_tokens > input_tpm:
            return [0, "Input TPM limit exceeded"]
            
        if current_output + output_tokens > output_tpm:
            return [0, "Output TPM limit exceeded"]
            
        if current_requests + request_count > rpm:
            return [0, "RPM limit exceeded"]
            
        # Add new entries
        for _ in range(input_tokens):
            await self.zadd(input_key, current_time, f"{current_time}_{uuid.uuid4()}")
            
        for _ in range(output_tokens):
            await self.zadd(output_key, current_time, f"{current_time}_{uuid.uuid4()}")
            
        for _ in range(request_count):
            await self.zadd(request_key, current_time, f"{current_time}_{uuid.uuid4()}")
            
        return [1, "OK"]


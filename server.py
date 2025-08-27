import asyncio
import uvloop
import time
import json
from typing import Dict, Any, Optional
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field
import logging
import os
import signal
import sys

from rate_limiter import DistributedRateLimiter
from mock_generator import MockOpenAIResponseGenerator, MockResponseConfig

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Install uvloop for better async performance
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

# Request/Response models
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatCompletionRequest(BaseModel):
    model: str = Field(default="gpt-3.5-turbo")
    messages: list[ChatMessage]
    max_tokens: Optional[int] = Field(default=150, ge=1, le=4096)
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    stream: Optional[bool] = Field(default=False)

class RateLimitError(HTTPException):
    def __init__(self, detail: str, retry_after: int = 1):
        super().__init__(status_code=429, detail=detail)
        self.headers = {"Retry-After": str(retry_after)}

class LLMAPIServer:
    def __init__(self, redis_url: str = "redis://localhost:6379", port: int = 8000):
        self.app = FastAPI(
            title="Distributed LLM API Rate Limiter",
            description="High-performance distributed rate limiting for LLM APIs",
            version="1.0.0"
        )
        self.port = port
        self.rate_limiter = DistributedRateLimiter(redis_url)
        self.response_generator = MockOpenAIResponseGenerator()
        self.request_count = 0
        self.setup_routes()
        
    async def initialize(self):
        """Initialize server components"""
        await self.rate_limiter.initialize()
        logger.info(f"Server initialized on port {self.port}")
        
    async def cleanup(self):
        """Cleanup server components"""
        await self.rate_limiter.close()
        logger.info("Server cleanup completed")
        
    def setup_routes(self):
        """Setup API routes"""
        
        @self.app.on_event("startup")
        async def startup():
            await self.initialize()
            
        @self.app.on_event("shutdown")
        async def shutdown():
            await self.cleanup()
            
        @self.app.get("/")
        async def root():
            return {
                "service": "Distributed LLM API Rate Limiter",
                "version": "1.0.0",
                "status": "running",
                "port": self.port
            }
            
        @self.app.get("/health")
        async def health_check():
            return {
                "status": "healthy",
                "timestamp": int(time.time()),
                "request_count": self.request_count
            }
            
        @self.app.get("/v1/models")
        async def list_models():
            """List available models (mock)"""
            return {
                "object": "list",
                "data": [
                    {
                        "id": "gpt-3.5-turbo",
                        "object": "model",
                        "created": 1677610602,
                        "owned_by": "openai"
                    },
                    {
                        "id": "gpt-4",
                        "object": "model", 
                        "created": 1687882411,
                        "owned_by": "openai"
                    }
                ]
            }
            
        @self.app.post("/v1/chat/completions")
        async def chat_completions(
            request: ChatCompletionRequest,
            background_tasks: BackgroundTasks,
            raw_request: Request
        ):
            """Handle chat completions with rate limiting"""
            
            # Extract API key from Authorization header
            auth_header = raw_request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
                
            api_key = auth_header[7:]  # Remove "Bearer " prefix
            
            # Estimate tokens
            input_tokens = self._estimate_input_tokens(request.messages)
            output_tokens = request.max_tokens or 150
            
            # Check rate limits
            allowed, error_message = await self.rate_limiter.check_rate_limit(
                api_key, input_tokens, output_tokens
            )
            
            if not allowed:
                logger.warning(f"Rate limit exceeded for API key: {api_key[:8]}... - {error_message}")
                raise RateLimitError(error_message)
                
            # Generate mock response
            request_dict = request.dict()
            
            if request.stream:
                return await self._handle_streaming_response(
                    request_dict, api_key
                )
            else:
                return await self._handle_regular_response(
                    request_dict, api_key
                )
                
        @self.app.get("/v1/usage/{api_key}")
        async def get_usage_stats(api_key: str):
            """Get usage statistics for an API key"""
            try:
                stats = await self.rate_limiter.get_usage_stats(api_key)
                return stats
            except Exception as e:
                raise HTTPException(status_code=500, detail=str(e))
                
    def _estimate_input_tokens(self, messages: list[ChatMessage]) -> int:
        """Estimate input tokens from messages"""
        total_chars = 0
        for msg in messages:
            total_chars += len(msg.content)
        
        # Rough approximation: 1 token ≈ 4 characters
        return max(1, total_chars // 4)
        
    async def _handle_regular_response(self, request_dict: Dict, api_key: str) -> Dict[str, Any]:
        """Handle non-streaming response"""
        response = self.response_generator.generate_response(
            request_dict, api_key
        )
        
        self.request_count += 1
        
        # Add rate limit headers
        return JSONResponse(
            content=response,
            headers={
                "X-RateLimit-InputTPM-Limit": str(60000),  # Mock values
                "X-RateLimit-OutputTPM-Limit": str(30000),
                "X-RateLimit-RPM-Limit": str(1000),
                "X-Request-ID": response["id"]
            }
        )
        
    async def _handle_streaming_response(self, request_dict: Dict, api_key: str):
        """Handle streaming response"""
        events = self.response_generator.generate_streaming_response(
            request_dict, api_key
        )
        
        self.request_count += 1
        
        async def generate():
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"
                await asyncio.sleep(0.01)  # Simulate streaming delay
                
            yield "data: [DONE]\n\n"
            
        return StreamingResponse(
            generate(),
            media_type="text/plain",
            headers={
                "X-RateLimit-InputTPM-Limit": str(60000),
                "X-RateLimit-OutputTPM-Limit": str(30000), 
                "X-RateLimit-RPM-Limit": str(1000),
                "Cache-Control": "no-cache",
                "Connection": "keep-alive"
            }
        )
        
    def run(self, host: str = "0.0.0.0", workers: int = 1):
        """Run the server"""
        import uvicorn
        
        uvicorn.run(
            self.app,
            host=host,
            port=self.port,
            workers=workers,
            log_level="info",
            access_log=True
        )

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Distributed LLM API Rate Limiter")
    parser.add_argument("--port", type=int, default=8000, help="Port to run on")
    parser.add_argument("--redis", default="redis://localhost:6379", help="Redis URL")
    parser.add_argument("--workers", type=int, default=1, help="Number of worker processes")
    
    args = parser.parse_args()
    
    server = LLMAPIServer(redis_url=args.redis, port=args.port)
    server.run(workers=args.workers)
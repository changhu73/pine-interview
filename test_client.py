import asyncio
import aiohttp
import time
import json
import random
import logging
import os
import sys
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from collections import defaultdict, deque
import statistics
import argparse
import uuid
import hashlib

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class TestConfig:
    """Configuration for load testing"""
    target_nodes: List[str]
    api_keys: List[str]
    concurrent_requests: int = 100
    duration_seconds: int = 60
    request_rate: int = 1000  # requests per second
    output_file: str = "test_results.json"
    
@dataclass
class RequestResult:
    """Result of a single request"""
    success: bool
    status_code: int
    response_time: float
    tokens_sent: int
    tokens_received: int
    api_key: str
    timestamp: float
    error_message: Optional[str] = None

class MockRequestGenerator:
    """Generates realistic mock OpenAI API requests"""
    
    def __init__(self):
        self.prompts = [
            "Explain the concept of distributed systems.",
            "Write a Python function to reverse a string.",
            "What are the benefits of using Redis for rate limiting?",
            "Describe how sliding window algorithms work.",
            "Generate a haiku about programming.",
            "Compare REST vs GraphQL APIs.",
            "Explain CAP theorem in distributed systems.",
            "Write a SQL query to find duplicate records.",
            "What is the difference between async and sync programming?",
            "How does load balancing work in microservices?"
        ]
        
    def generate_request(self, api_key: str) -> Dict[str, Any]:
        """Generate a mock OpenAI chat completion request"""
        prompt = random.choice(self.prompts)
        
        # Generate deterministic request based on API key for consistent testing
        hash_obj = hashlib.md5(api_key.encode())
        hash_hex = hash_obj.hexdigest()
        
        # Generate input tokens (100-1000)
        input_tokens = 100 + (int(hash_hex[:4], 16) % 900)
        
        # Create messages with appropriate length
        words_needed = input_tokens * 0.75  # Rough approximation
        extended_prompt = prompt
        while len(extended_prompt.split()) < words_needed:
            extended_prompt += f" {prompt}"
            
        return {
            "model": "gpt-3.5-turbo",
            "messages": [
                {"role": "user", "content": extended_prompt}
            ],
            "max_tokens": random.randint(50, 500),
            "temperature": random.uniform(0.1, 1.0)
        }

class HighPerformanceLoadTester:
    """High-performance load testing client"""
    
    def __init__(self, config: TestConfig):
        self.config = config
        self.results = []
        self.start_time = None
        self.stats = defaultdict(int)
        self.response_times = deque(maxlen=10000)
        self.error_counts = defaultdict(int)
        
    async def run_load_test(self) -> Dict[str, Any]:
        """Run the complete load test"""
        logger.info(f"Starting load test with {self.config.concurrent_requests} concurrent clients")
        logger.info(f"Target nodes: {self.config.target_nodes}")
        logger.info(f"API keys: {len(self.config.api_keys)}")
        logger.info(f"Duration: {self.config.duration_seconds}s")
        
        self.start_time = time.time()
        
        # Create semaphore to control concurrency
        semaphore = asyncio.Semaphore(self.config.concurrent_requests)
        
        # Create all tasks
        tasks = []
        request_generator = MockRequestGenerator()
        
        # Calculate total requests to send
        total_requests = self.config.duration_seconds * self.config.request_rate
        
        # Create tasks with proper timing
        for i in range(total_requests):
            target_time = self.start_time + (i / self.config.request_rate)
            api_key = random.choice(self.config.api_keys)
            request_data = request_generator.generate_request(api_key)
            
            task = asyncio.create_task(
                self._send_request_at_time(
                    request_data, api_key, target_time, semaphore
                )
            )
            tasks.append(task)
        
        # Wait for all tasks to complete
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.error(f"Error during load test: {e}")
            
        # Generate report
        report = await self._generate_report()
        
        # Save results
        with open(self.config.output_file, 'w') as f:
            json.dump(report, f, indent=2)
            
        logger.info(f"Load test completed. Results saved to {self.config.output_file}")
        return report
        
    async def _send_request_at_time(
        self, 
        request_data: Dict, 
        api_key: str, 
        target_time: float, 
        semaphore: asyncio.Semaphore
    ):
        """Send request at the specified time"""
        # Wait until the target time
        current_time = time.time()
        if target_time > current_time:
            await asyncio.sleep(target_time - current_time)
            
        async with semaphore:
            return await self._send_single_request(request_data, api_key)
            
    async def _send_single_request(
        self, 
        request_data: Dict[str, Any], 
        api_key: str
    ) -> RequestResult:
        """Send a single request and record the result"""
        
        # Select random target node
        target_url = random.choice(self.config.target_nodes)
        
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "LoadTester/1.0"
        }
        
        start_time = time.time()
        
        try:
            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{target_url}/v1/chat/completions",
                    json=request_data,
                    headers=headers
                ) as response:
                    
                    response_time = time.time() - start_time
                    
                    # Read response
                    try:
                        response_data = await response.json()
                        tokens_sent = len(json.dumps(request_data))
                        tokens_received = len(json.dumps(response_data))
                        
                        result = RequestResult(
                            success=response.status == 200,
                            status_code=response.status,
                            response_time=response_time,
                            tokens_sent=tokens_sent,
                            tokens_received=tokens_received,
                            api_key=api_key,
                            timestamp=start_time,
                            error_message=None if response.status == 200 else await response.text()
                        )
                        
                    except Exception as e:
                        result = RequestResult(
                            success=False,
                            status_code=response.status,
                            response_time=response_time,
                            tokens_sent=len(json.dumps(request_data)),
                            tokens_received=0,
                            api_key=api_key,
                            timestamp=start_time,
                            error_message=str(e)
                        )
                    
        except asyncio.TimeoutError:
            result = RequestResult(
                success=False,
                status_code=0,
                response_time=time.time() - start_time,
                tokens_sent=len(json.dumps(request_data)),
                tokens_received=0,
                api_key=api_key,
                timestamp=start_time,
                error_message="Timeout"
            )
            
        except Exception as e:
            result = RequestResult(
                success=False,
                status_code=0,
                response_time=time.time() - start_time,
                tokens_sent=len(json.dumps(request_data)),
                tokens_received=0,
                api_key=api_key,
                timestamp=start_time,
                error_message=str(e)
            )
            
        self.results.append(result)
        self.response_times.append(result.response_time)
        
        # Update stats
        if result.success:
            self.stats['successful_requests'] += 1
        else:
            self.stats['failed_requests'] += 1
            self.error_counts[result.error_message] += 1
            
        return result
        
    async def _generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive test report"""
        test_duration = time.time() - self.start_time
        
        if not self.results:
            return {"error": "No results collected"}
            
        # Calculate statistics
        response_times = [r.response_time for r in self.results]
        successful_times = [r.response_time for r in self.results if r.success]
        
        report = {
            "test_config": {
                "target_nodes": self.config.target_nodes,
                "api_keys_count": len(self.config.api_keys),
                "concurrent_requests": self.config.concurrent_requests,
                "duration_seconds": self.config.duration_seconds,
                "request_rate": self.config.request_rate,
                "total_expected_requests": self.config.duration_seconds * self.config.request_rate
            },
            "summary": {
                "total_requests": len(self.results),
                "successful_requests": self.stats['successful_requests'],
                "failed_requests": self.stats['failed_requests'],
                "success_rate": self.stats['successful_requests'] / len(self.results),
                "test_duration_seconds": test_duration,
                "requests_per_second": len(self.results) / test_duration
            },
            "performance_metrics": {
                "min_response_time_ms": min(response_times) * 1000,
                "max_response_time_ms": max(response_times) * 1000,
                "mean_response_time_ms": statistics.mean(response_times) * 1000,
                "median_response_time_ms": statistics.median(response_times) * 1000,
                "p95_response_time_ms": statistics.quantiles(response_times, n=20)[18] * 1000,
                "p99_response_time_ms": statistics.quantiles(response_times, n=100)[98] * 1000,
                "std_dev_response_time_ms": statistics.stdev(response_times) * 1000 if len(response_times) > 1 else 0
            },
            "error_analysis": {
                "total_errors": len([r for r in self.results if not r.success]),
                "error_types": dict(self.error_counts),
                "rate_limit_hits": len([r for r in self.results if r.status_code == 429])
            },
            "throughput_by_key": {},
            "detailed_results": [
                {
                    "success": r.success,
                    "status_code": r.status_code,
                    "response_time_ms": r.response_time * 1000,
                    "api_key": r.api_key[:8] + "...",
                    "timestamp": r.timestamp,
                    "error": r.error_message
                }
                for r in self.results
            ]
        }
        
        # Calculate throughput by API key
        key_stats = defaultdict(lambda: {'requests': 0, 'success': 0})
        for result in self.results:
            key_stats[result.api_key]['requests'] += 1
            if result.success:
                key_stats[result.api_key]['success'] += 1
                
        report["throughput_by_key"] = {
            k: {
                'total_requests': v['requests'],
                'success_rate': v['success'] / v['requests'],
                'requests_per_second': v['requests'] / test_duration
            }
            for k, v in key_stats.items()
        }
        
        return report

async def main():
    """Main entry point for testing"""
    parser = argparse.ArgumentParser(description="High-performance load testing client")
    parser.add_argument("--nodes", nargs="+", default=["http://localhost:8000"], 
                       help="Target server nodes")
    parser.add_argument("--api-keys", nargs="+", default=["test_key_1", "test_key_2", "test_key_3"],
                       help="API keys to test")
    parser.add_argument("--concurrent", type=int, default=100,
                       help="Number of concurrent requests")
    parser.add_argument("--duration", type=int, default=60,
                       help="Test duration in seconds")
    parser.add_argument("--rate", type=int, default=1000,
                       help="Requests per second")
    parser.add_argument("--output", default="test_results.json",
                       help="Output file for results")
    
    args = parser.parse_args()
    
    config = TestConfig(
        target_nodes=args.nodes,
        api_keys=args.api_keys,
        concurrent_requests=args.concurrent,
        duration_seconds=args.duration,
        request_rate=args.rate,
        output_file=args.output
    )
    
    tester = HighPerformanceLoadTester(config)
    
    try:
        results = await tester.run_load_test()
        
        # Print summary
        print("\n" + "="*60)
        print("LOAD TEST SUMMARY")
        print("="*60)
        print(f"Total Requests: {results['summary']['total_requests']}")
        print(f"Successful: {results['summary']['successful_requests']}")
        print(f"Failed: {results['summary']['failed_requests']}")
        print(f"Success Rate: {results['summary']['success_rate']:.2%}")
        print(f"Duration: {results['summary']['test_duration_seconds']:.2f}s")
        print(f"Throughput: {results['summary']['requests_per_second']:.2f} req/s")
        print()
        print(f"Min Response Time: {results['performance_metrics']['min_response_time_ms']:.2f}ms")
        print(f"Mean Response Time: {results['performance_metrics']['mean_response_time_ms']:.2f}ms")
        print(f"P95 Response Time: {results['performance_metrics']['p95_response_time_ms']:.2f}ms")
        print(f"P99 Response Time: {results['performance_metrics']['p99_response_time_ms']:.2f}ms")
        
        if results['error_analysis']['rate_limit_hits'] > 0:
            print(f"\nRate Limit Hits: {results['error_analysis']['rate_limit_hits']}")
            
    except KeyboardInterrupt:
        logger.info("Test interrupted by user")
    except Exception as e:
        logger.error(f"Test failed: {e}")
        raise

if __name__ == "__main__":
    asyncio.run(main())
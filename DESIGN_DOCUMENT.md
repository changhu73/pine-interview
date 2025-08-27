# Distributed LLM API Rate Limiter - Design Document

## System Overview

This document describes the design and implementation of a high-performance, distributed rate limiter specifically designed for Large Language Model (LLM) APIs. The system provides precise rate limiting based on three key metrics:

1. **Input Tokens Per Minute (Input TPM)**
2. **Output Tokens Per Minute (Output TPM)** 
3. **Requests Per Minute (RPM)**

The rate limiter uses a sliding window algorithm with sub-second precision to ensure accurate rate limiting across distributed nodes.

## Architecture

### High-Level Design

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Rate Limiter  │    │   Rate Limiter  │    │   Rate Limiter  │
│   Node 1        │    │   Node 2        │    │   Node N        │
│   Port 8000     │    │   Port 8001     │    │   Port 800N     │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                       │                       │
         └───────────────────────┴───────────────────────┘
                                 │
                    ┌─────────────┴─────────────┐
                    │      Redis Cluster        │
                    │   (Central Coordination)  │
                    └─────────────────────────────┘
```

### Components

#### 1. Distributed Rate Limiter (`rate_limiter.py`)
- **Purpose**: Core rate limiting logic using Redis
- **Algorithm**: Sliding window with sorted sets (ZSET)
- **Consistency**: Atomic operations via Lua scripts
- **Accuracy**: Sub-second precision with 60-second sliding window

#### 2. API Server (`server.py`)
- **Framework**: FastAPI with uvloop for async performance
- **Protocol**: OpenAI-compatible REST API
- **Endpoints**: 
  - `POST /v1/chat/completions`
  - `GET /v1/models`
  - `GET /v1/usage/{api_key}`

#### 3. Mock Response Generator (`mock_generator.py`)
- **Purpose**: Generate realistic OpenAI API responses
- **Features**: Configurable token counts, streaming support
- **Performance**: High-throughput mock generation

#### 4. Load Testing Client (`test_client.py`)
- **Type**: High-performance async client
- **Capabilities**: 
  - Concurrent request simulation
  - Distributed node targeting
  - Comprehensive metrics collection

## Rate Limiting Algorithm

### Sliding Window Implementation

The system uses Redis sorted sets (ZSET) to implement precise sliding window rate limiting:

```
ZSET Structure:
Key: rate_limit:{api_key}:{metric}
Score: Timestamp (seconds)
Member: "{timestamp}:{random_uuid}"
```

### Lua Script Atomicity

Critical operations are executed atomically using Redis Lua scripts to prevent race conditions:

1. **Check Limits**: Verify all three rate limits
2. **Update State**: Add new entries only if within limits
3. **Cleanup**: Remove expired entries (older than 60s)

### Time Precision

- **Window Size**: 60 seconds (configurable)
- **Precision**: 1-second granularity
- **Accuracy**: Error margin < 1 second

## Data Structures

### Redis Keys

```
rate_limit:{api_key}:input_tokens    # Input token tracking
rate_limit:{api_key}:output_tokens   # Output token tracking  
rate_limit:{api_key}:requests        # Request count tracking
```

### Rate Limit Configuration

```python
@dataclass
class RateLimitConfig:
    input_tpm: int   # Input tokens per minute (10K-60K)
    output_tpm: int  # Output tokens per minute (5K-30K)
    rpm: int         # Requests per minute (100-1000)
```

## Performance Characteristics

### Time Complexity

| Operation | Time Complexity | Description |
|-----------|----------------|-------------|
| Rate Check | O(log n) | ZSET operations + Lua script |
| Cleanup | O(log n) | ZREMRANGEBYSCORE |
| Usage Stats | O(1) | ZCARD operations |

### Space Complexity

| Component | Space Usage | Notes |
|-----------|-------------|--------|
| Per API Key | O(n) | Where n = requests in 60s window |
| Per Token | O(1) | Fixed size per token entry |
| Total Memory | O(m × n) | m = active API keys |

## Scalability Analysis

### Horizontal Scaling

- **Node Count**: Linear horizontal scaling
- **Load Distribution**: Random/round-robin request routing
- **Shared State**: Redis provides distributed consistency
- **Throughput**: Each node handles 1K+ QPS

### Redis Scaling

- **Cluster Mode**: Redis Cluster for sharding
- **Memory**: 512MB LRU cache per node
- **Persistence**: AOF for durability (optional)
- **Replication**: Master-replica for HA

## Consistency Guarantees

### Distributed Consistency

- **Atomic Operations**: Lua scripts ensure atomicity
- **No Distributed Locks**: Avoids single-key bottlenecks
- **Eventual Consistency**: All nodes see same state via Redis
- **No Split-Brain**: Single Redis cluster prevents conflicts

### Rate Limit Accuracy

- **Strict Enforcement**: No requests exceed limits
- **Immediate Effect**: Rate limit changes take effect instantly
- **No Over-Counting**: Failed requests don't count against limits

## Network Protocol

### OpenAI Compatibility

```json
{
  "model": "gpt-3.5-turbo",
  "messages": [{"role": "user", "content": "Hello"}],
  "max_tokens": 150,
  "temperature": 0.7,
  "stream": false
}
```

### Response Format

```json
{
  "id": "mock_req_...",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "gpt-3.5-turbo",
  "choices": [...],
  "usage": {
    "prompt_tokens": 100,
    "completion_tokens": 150,
    "total_tokens": 250
  }
}
```

## Testing Framework

### Performance Testing

**Configuration Options:**
- Concurrent clients: 1-1000
- Request rate: 1-10,000 RPS
- Test duration: 10-300 seconds
- API keys: 1-100 keys
- Target nodes: 1-10 servers

**Metrics Collected:**
- Response times (min, max, mean, p95, p99)
- Throughput (requests/second)
- Error rates (429, 500, timeouts)
- Rate limit accuracy
- Resource utilization

### Test Scenarios

1. **Single Node Load**: 1K QPS sustained load
2. **Distributed Load**: 5K QPS across 5 nodes
3. **Rate Limit Stress**: Aggressive key testing
4. **Burst Handling**: Sudden traffic spikes
5. **Long Duration**: 1-hour sustained load

## Deployment Options

### Docker Compose (Development)

```yaml
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
  
  rate-limiter-1:
    build: .
    ports: ["8000:8000"]
    depends_on: [redis]
    
  rate-limiter-2:
    build: .
    ports: ["8001:8000"]
    depends_on: [redis]
```

### Kubernetes (Production)

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rate-limiter
spec:
  replicas: 3
  selector:
    matchLabels:
      app: rate-limiter
  template:
    spec:
      containers:
      - name: rate-limiter
        image: rate-limiter:latest
        ports:
        - containerPort: 8000
        env:
        - name: REDIS_URL
          value: "redis://redis-cluster:6379"
```

## Monitoring and Observability

### Key Metrics

- **Request Rate**: Requests per second per node
- **Response Time**: P95 and P99 latencies
- **Error Rate**: 429 and 5xx error rates
- **Redis Performance**: Connection pool utilization
- **Memory Usage**: Redis memory consumption

### Health Checks

- **HTTP**: `/health` endpoint
- **Redis**: Connection and command latency
- **Rate Limits**: Config validation
- **Mock Generation**: Response generation health

## Security Considerations

### Authentication

- **API Keys**: Bearer token authentication
- **Validation**: Key format and existence checks
- **Rate Limits**: Per-key configurable limits
- **Encryption**: TLS for all communications

### Rate Limiting Security

- **Fairness**: Equal treatment across keys
- **Protection**: DDoS prevention via strict limits
- **Monitoring**: Suspicious activity detection
- **Audit**: Request logging for compliance

## Future Enhancements

### Planned Features

1. **WebSocket Support**: Real-time streaming
2. **Custom Metrics**: Business-specific rate limits
3. **Machine Learning**: Adaptive rate limiting
4. **Multi-Region**: Global deployment support
5. **Webhooks**: Rate limit notifications

### Performance Optimizations

1. **Redis Pipeline**: Batch operations
2. **Connection Pooling**: Optimized Redis connections
3. **Caching**: Local cache for frequent checks
4. **Compression**: Redis value compression
5. **Sharding**: Horizontal Redis scaling

## Conclusion

This distributed rate limiter provides enterprise-grade rate limiting for LLM APIs with the following key benefits:

- **High Performance**: 1K+ QPS per node
- **Distributed Consistency**: Atomic operations via Redis
- **OpenAI Compatibility**: Drop-in replacement
- **Scalable Architecture**: Horizontal scaling ready
- **Comprehensive Testing**: Production-grade testing framework
- **Production Ready**: Docker and Kubernetes deployment

The system successfully addresses all requirements including distributed consistency, sub-second sliding window accuracy, high throughput, and comprehensive testing capabilities.
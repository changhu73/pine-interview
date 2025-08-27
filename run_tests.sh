#!/bin/bash

# Distributed LLM API Rate Limiter Testing Script
set -e

echo "🚀 Starting Distributed LLM Rate Limiter Testing Environment"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    print_error "Docker is not running. Please start Docker first."
    exit 1
fi

# Check if Docker Compose is available
if ! command -v docker-compose > /dev/null 2>&1 && ! docker compose version > /dev/null 2>&1; then
    print_error "Docker Compose is not available. Please install Docker Compose."
    exit 1
fi

print_status "Starting infrastructure..."

# Start Redis and all rate limiter nodes
docker-compose up -d redis

print_status "Waiting for Redis to be ready..."
sleep 5

print_status "Starting rate limiter nodes..."
docker-compose up -d rate-limiter-1 rate-limiter-2 rate-limiter-3 rate-limiter-4

print_status "Waiting for all nodes to be ready..."
sleep 10

# Check if all services are running
print_status "Checking service health..."
docker-compose ps

# Wait for all services to be healthy
print_status "Waiting for all services to be healthy..."
timeout=60
counter=0
while [ $counter -lt $timeout ]; do
    if docker-compose ps | grep -E "(unhealthy|starting)" > /dev/null; then
        echo -n "."
        sleep 2
        counter=$((counter + 2))
    else
        print_status "All services are healthy!"
        break
    fi
done

if [ $counter -ge $timeout ]; then
    print_warning "Some services may not be fully ready, continuing anyway..."
fi

print_status "Running performance tests..."

# Run the test client
python test_client.py \
    --nodes http://localhost:8000 http://localhost:8001 http://localhost:8002 http://localhost:8003 \
    --api-keys test_key_1 test_key_2 test_key_3 test_key_4 test_key_5 \
    --concurrent 200 \
    --duration 30 \
    --rate 2000 \
    --output test_results.json

print_status "Tests completed! Results saved to test_results.json"

# Display summary
if [ -f test_results.json ]; then
    print_status "Test Summary:"
    echo "----------------------------------------"
    cat test_results.json | jq '.summary'
    echo "----------------------------------------"
    cat test_results.json | jq '.performance_metrics'
fi

print_status "To view detailed logs:"
echo "  docker-compose logs -f"
print_status "To stop the test environment:"
echo "  docker-compose down"
print_status "To run custom tests:"
echo "  python test_client.py --help"
# pine-interview

# Distributed LLM API Rate Limiter Design & Testing

## Requirements

You are asked to implement a **scalable, distributed API Rate Limiter** for LLM services (e.g., OpenAI-compatible APIs).
The implementation can be done in **any programming language**, using any tools or libraries (e.g., Redis).
The solution should support **multiple nodes** (simulated with multiple processes) serving as entry points for HTTP requests.

### API Request Format

* Each HTTP request follows the **OpenAI API format**.
* Each request carries an **API key**.
* Each API key is associated with three rate limit metrics:

1. **Input Token Limit per Minute (Input TPM)**
2. **Output Token Limit per Minute (Output TPM)**
3. **Request Rate Limit per Minute (RPM)**

### Rate Limiting Rules

* **Sliding Window** algorithm must be used for rate limit calculation.
* If **any** of the three limits is exceeded, the request must be rejected with **HTTP 429**.
* Rejected requests **do not** count towards the rate limit usage.
* If all three limits are within range, the system should generate a **mock OpenAI API response** (HTTP 200).

  > Note: No actual LLM call is required.

---

## Distributed Requirements

* The system must handle **large numbers of requests**.
* Same API key requests may be routed to **different Rate Limiter nodes**.
* The distributed Rate Limiter must ensure **consistency across nodes**:

  * Avoid common pitfalls like **check-then-set race conditions**.
  * Avoid performance bottlenecks like **global distributed locks** that reduce throughput per API key.

---

## Performance Requirements

1. **Sliding window error margin** must be less than **1 second**.
2. Each Rate Limiter node (process) must sustain at least **1K QPS** throughput.
3. The test client should be capable of generating **high-performance load**, so that performance bottlenecks of the Rate Limiter can be measured.

---

## Testing

* Implement a **mock OpenAI API request generator client**.
* The client should:

  * Randomly distribute requests across multiple Rate Limiter nodes.
  * Generate high-load traffic to stress test throughput.

---

## Deliverables

1. **Implementation** of the distributed Rate Limiter.
2. **Testing client** for mock request generation.
3. **Design document & performance test report**, including:

   * System design explanation.
   * Time & space complexity analysis.
   * Scalability discussion.
   * Performance benchmarking results.


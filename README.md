# Distributed Rate Limiting Middleware (FastAPI + Redis GCRA)

[![CI Status](https://github.com/cvneren/rate-limiting-architecture/actions/workflows/ci.yml/badge.svg)](https://github.com/cvneren/rate-limiting-architecture/actions/workflows)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Redis 7.0+](https://img.shields.io/badge/redis-7.0+-red.svg)](https://redis.io/)

A high-performance, production-grade distributed rate limiting solution for FastAPI applications. This implementation leverages the **Generic Cell Rate Algorithm (GCRA)** and atomic **Redis Lua scripting** to ensure systemic stability under high concurrency.

## 1. Business Value & Problem Statement

In distributed microservices, rate limiting is a critical control plane mechanism. This project solves three primary engineering challenges:

*   **Systemic Stability**: Prevents downstream service saturation during traffic spikes, ensuring that API gateways remain responsive during infrastructure degradation.
*   **Fair Resource Allocation**: Enforces strict throughput quotas for multi-tenant consumers, preventing "noisy neighbor" scenarios.
*   **Volumetric Security**: Serves as a primary defense vector against malicious resource exhaustion, scraping, and Distributed Denial-of-Service (DDoS) attacks.

The architecture is designed for microsecond-level latency, ensuring that the rate limiting tier does not become the system bottleneck.

## 2. Architectural Decisions

### 2.1 Generic Cell Rate Algorithm (GCRA)
We implement the Token Bucket model via the GCRA. Unlike naive implementations that require continuous replenishment threads, GCRA tracks a single state variable per client—the **Theoretical Arrival Time (TAT)**. This reduces memory overhead to $O(1)$ per identifier and eliminates float-rounding anomalies in distributed state.

### 2.2 Atomic Concurrency Control (Lua Scripting)
To neutralize **Time-Of-Check-To-Time-Of-Use (TOCTOU)** race conditions, the entire evaluation lifecycle is offloaded to a server-side Lua script (`EVALSHA`). 
*   **Atomicity**: Evaluation and mutation occur as a single indivisible unit on the Redis event loop.
*   **Clock Synchronization**: The script utilizes `redis.call('TIME')` as the absolute chronological source of truth, defeating multi-node clock drift.
*   **Cluster Compatibility**: Implements **Hash Tags** (e.g., `{client_id}`) to ensure all state for a specific client maps to the same Redis Cluster shard, preventing `CROSSSLOT` errors.

### 2.3 Two-Tier Resilience Strategy
*   **L1 Hot-Key Protection**: A local, bounded `TTLCache` (in-memory) intercepts identified abusers. If a client is grossly exceeding quotas, the middleware blocks subsequent requests natively in Python, shielding the Redis cluster from single-core saturation.
*   **Fail-Open Resilience**: All Redis operations are wrapped in strict `asyncio.timeout` blocks. Upon network partition or Redis failure, the system falls back to a local in-process rate limiter, maintaining API availability (High Availability over Strict Consistency).

### 2.4 Pure ASGI Implementation
This middleware is implemented as a **Pure ASGI class**, bypassing Starlette’s `BaseHTTPMiddleware`. This prevents unnecessary request/response object cloning and minimizes garbage collection (GC) overhead, yielding a significant improvement in raw requests-per-second (RPS) throughput.

## 3. Local Development

### Prerequisites
*   **Python**: 3.11 or higher
*   **Redis**: 7.0 or higher (required for native `TIME` command support in Lua scripts)

### Installation
```bash
# Clone the repository
git clone https://github.com/cvneren/rate-limiting-architecture.git
cd rate-limiting-architecture/infrastructure-repo

# Install dependencies
pip install -r requirements.txt
```

### Configuration
Environment variables are managed via Pydantic Settings:
*   `REDIS_URL`: Defaults to `redis://localhost:6379/0`
*   `RATE_LIMIT_LIMIT`: Allowed requests per period (default: 100)
*   `RATE_LIMIT_PERIOD`: Time window in seconds (default: 60)
*   `RATE_LIMIT_BURST`: Initial burst capacity (default: 10)

### Running the Application
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Verification
The project includes a comprehensive concurrency test suite:
```bash
pytest tests/ -v --asyncio-mode=auto
```
This validates TOCTOU defense, fail-open fallback mechanisms, and L1 blocklist isolation.

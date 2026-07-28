# Docker Health Check Setup

This document explains the health check implementation for monitoring and recovering from Socket Mode connection failures.

## Problem

Your Slack Bolt app can enter a stuck state where:
1. Socket Mode connection establishes
2. Immediately fails with `BrokenPipeError` 
3. Attempts to reconnect
4. Fails again in a loop
5. Never recovers without manual intervention

The app continues running, so Docker doesn't restart it automatically. This state persists indefinitely.

## Solution Overview

The solution detects the error loop pattern and **proactively terminates the container** so Docker can restart it:

1. **Error Monitoring** — Slack Bolt logger errors are captured in real-time
2. **Health Tracking** — `ConnectionHealthMonitor` counts errors in a sliding window
3. **Auto-Shutdown** — When error threshold is reached, the app calls `sys.exit(1)` to terminate
4. **Docker Restart** — Docker's `restart: unless-stopped` policy restarts the container
5. **Fresh State** — New container instance gets new connections

## Components

### 1. Connection Health Monitor (`health_check.py`)

A thread-safe monitor that:
- Tracks `BrokenPipeError` timestamps in a sliding window (default: 20 seconds)
- Implements a **startup grace period** (15s) where errors don't trigger shutdown
- Marks connection as unhealthy if 3+ errors occur within the window **after** grace period expires
- Calls `exit_callback()` when threshold is reached (triggers immediate container shutdown)
- Thread-safe with internal locking

Key parameters (customizable):
```python
ConnectionHealthMonitor(
    error_threshold=3,           # errors needed to trigger shutdown
    window_seconds=20,           # time window for counting errors
    startup_grace_seconds=15,    # grace period after startup
    exit_callback=sys.exit       # called when unhealthy
)
```

### 2. HTTP Health Check Endpoint (`app.py`)

An HTTP server on port 8080 that:
- Listens for GET requests to `/health` 
- Returns `200 OK` if monitor reports healthy
- Returns `503 Service Unavailable` if monitor reports unhealthy
- Runs in a background daemon thread (non-blocking)
- Useful for manual health checks via `curl http://localhost:8080/health`

### 3. Error Monitoring Logger (`app.py`)

A custom logging handler that:
- Attaches to `slack_bolt.app` logger
- Captures all ERROR level logs from Slack Bolt
- Detects `BrokenPipeError`, `Broken pipe`, or `[Errno 32]` in error messages
- Calls `monitor.record_error()` for each detected error

### 4. Docker Health Check Configuration (`Dockerfile`)

```dockerfile
HEALTHCHECK --interval=5s --timeout=3s --retries=2 --start-period=20s \
    CMD curl -f http://localhost:8080/health || exit 1
```

- `interval=5s` — Check health every 5 seconds (frequent detection)
- `timeout=3s` — Max 3 seconds to wait for response
- `retries=2` — If 2 checks fail within 10 seconds, mark unhealthy
- `start-period=20s` — Grace period before Docker starts health checks

## How It Works

### Timeline (Error Loop Scenario)

```
t=0s:    Container starts
         - app.py loads
         - HTTP server starts on :8080
         - Error monitoring installed
         - Socket Mode handler starts

t=0-15s: Startup Grace Period
         - BrokenPipeError occurs
         - Logger captures error
         - monitor.record_error() called
         - Grace period active → error RECORDED but NOT triggering shutdown
         - is_healthy() returns True (grace period active)

t=0-20s: Docker Start-Period
         - Docker waits, doesn't run health checks yet
         - App keeps attempting reconnection

t=20s:   Start-period expires
         - Grace period expires (t=15s) 
         - Docker starts running health checks (every 5s)

t=20-24s: If errors continue...
         - BrokenPipeError #1 → record_error() → count=1
         - BrokenPipeError #2 → record_error() → count=2
         - BrokenPipeError #3 → record_error() → count=3 (THRESHOLD!)
         - exit_callback called → sys.exit(1)
         - Container terminates
         - Process ends with exit code 1

t=24s+:  Docker detects terminated process
         - Marks container unhealthy
         - Applies restart: unless-stopped policy
         - Starts new container
         - Fresh state, new connections
         - Cycle repeats (if error pattern persists)
         - Eventually succeeds (or restarts)
```

### Timing Summary

- **Total time from first error to restart:** ~20-30 seconds
- **Grace period:** 15 seconds (allows normal startup errors)
- **Detection window:** 20 seconds (for counting errors)
- **Threshold:** 3 errors = shutdown

## Configuration & Customization

### Adjusting Sensitivity

Edit `health_check.py` defaults in `app.py`:

```python
# More sensitive: restart faster (requires fewer errors)
monitor = ConnectionHealthMonitor(
    error_threshold=2,           # 2 instead of 3
    window_seconds=15,           # shorter window
    startup_grace_seconds=10,    # shorter grace
)

# Less sensitive: tolerate more errors
monitor = ConnectionHealthMonitor(
    error_threshold=5,           # 5 instead of 3
    window_seconds=30,           # longer window
    startup_grace_seconds=20,    # longer grace
)
```

### Docker Health Check Timings

Edit `Dockerfile` HEALTHCHECK instruction:

```dockerfile
# Faster detection (check every 1s)
HEALTHCHECK --interval=1s --timeout=2s --retries=3 --start-period=20s \
    CMD curl -f http://localhost:8080/health || exit 1

# Slower detection (check every 10s)
HEALTHCHECK --interval=10s --timeout=5s --retries=2 --start-period=30s \
    CMD curl -f http://localhost:8080/health || exit 1
```

### Docker Compose Override

Override in `docker-compose.yml`:

```yaml
services:
  trivia-bot:
    build: .
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 5s
      timeout: 3s
      retries: 2
      start_period: 20s
    # ... rest of config
```

## Monitoring & Troubleshooting

### Check Current Health

```bash
# View container health status in real-time
docker ps | grep trivia-bot

# View detailed health check state
docker inspect --format='{{json .State.Health}}' <container-id> | jq

# View the app's health endpoint
curl http://localhost:8080/health
```

### View Logs

```bash
# Live logs with timestamps
docker-compose logs -f

# Last 50 lines
docker logs <container-id> | tail -50

# Find error patterns
docker logs <container-id> | grep -i "brokenpipe"
docker logs <container-id> | grep "UNHEALTHY"
```

### Example Log Output

**Healthy startup:**
```
2026-07-28 21:45:00 [INFO] app: Health check server started on port 8080
2026-07-28 21:45:00 [INFO] app: Trivia Bot starting...
2026-07-28 21:45:00 [INFO] app: Error monitoring handler installed
2026-07-28 21:45:01 [INFO] slack_bolt.App: Connecting to Socket Mode...
2026-07-28 21:45:02 [INFO] slack_bolt.App: Starting to receive messages from a new connection
```

**Error loop detection (auto-restart triggered):**
```
2026-07-28 21:45:00 [INFO] app: Health check server started on port 8080
2026-07-28 21:45:00 [ERROR] slack_bolt.App: on_error invoked (...BrokenPipeError...)
2026-07-28 21:45:00 [WARNING] health_check: BrokenPipeError recorded (startup: 0.1s, errors in window: 1/3)
2026-07-28 21:45:01 [ERROR] slack_bolt.App: on_error invoked (...BrokenPipeError...)
2026-07-28 21:45:01 [WARNING] health_check: BrokenPipeError recorded (startup: 0.2s, errors in window: 2/3)
2026-07-28 21:45:01 [ERROR] slack_bolt.App: on_error invoked (...BrokenPipeError...)
2026-07-28 21:45:01 [WARNING] health_check: BrokenPipeError recorded (startup: 0.3s, errors in window: 3/3)
2026-07-28 21:45:01 [ERROR] health_check: UNHEALTHY: 3 errors in 20s window - initiating shutdown
2026-07-28 21:45:01 [CRITICAL] app: Emergency shutdown triggered by health monitor
```

Then Docker restarts the container.

## Testing

### Local Test (without Docker)

```bash
# Start the app locally
python app.py

# In another terminal, test the health endpoint
curl http://localhost:8080/health

# Should return: "200 OK" with body "OK"
```

### Docker Build & Test

```bash
# Build the image
docker build -t slack-trivia-bot .

# Run with explicit error logs
docker run -it --env-file .env slack-trivia-bot

# In another terminal, check health during runtime
docker exec <container-id> curl http://localhost:8080/health
```

### Manual Error Injection (advanced)

To test that the shutdown triggers correctly without relying on actual Slack errors:

1. Temporarily modify `health_check.py` to reduce `startup_grace_seconds` to 2s
2. Start the app: `python app.py`
3. The app will treat normal startup as errors (if Socket Mode fails)
4. After 2s + 3 errors, the app should exit with code 1

## Architecture Decisions

| Decision | Rationale |
|----------|-----------|
| **Exit callback instead of Docker health check only** | Health check alone can't force restart; we need to terminate the process |
| **Startup grace period** | Allows normal connection establishment without false positives |
| **Sliding window instead of cumulative count** | Prevents stale errors from old restart cycles interfering |
| **Logging handler instead of API hook** | More reliable and uses public APIs only |
| **HTTP endpoint at :8080** | Standard health check port, useful for manual testing |
| **Daemon thread for HTTP server** | Non-blocking, won't prevent graceful shutdown |

## Limitations & Future Improvements

- Only detects `BrokenPipeError` patterns; could be extended for other error types
- Could emit metrics (Prometheus, CloudWatch) for monitoring
- Slack Bolt library could implement exponential backoff natively
- Could add manual health recovery signal via HTTP endpoint

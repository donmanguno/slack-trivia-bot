# Docker Health Check Setup

This document explains the health check implementation for monitoring and recovering from Socket Mode connection failures.

## Problem

Your Slack Bolt app can enter a stuck state where:
1. Socket Mode connection establishes
2. Immediately fails with `BrokenPipeError` 
3. Attempts to reconnect
4. Fails again in a loop
5. Never recovers without manual intervention

This state is not detected by Docker, so the container keeps running indefinitely without serving its purpose.

## Solution

The solution implements:

### 1. Connection Health Monitor (`health_check.py`)

A thread-safe monitor that:
- Tracks `BrokenPipeError` timestamps in a sliding window (default: 60 seconds)
- Marks the connection unhealthy if 3+ errors occur within the window
- Marks the connection as recovered after successful reconnection
- Provides a health status that can be queried

### 2. HTTP Health Check Endpoint (`app.py`)

An HTTP server on port 8080 that:
- Listens for GET requests to `/health`
- Returns `200 OK` if connection is healthy
- Returns `503 Service Unavailable` if connection is unhealthy
- Runs in a background thread (non-blocking)

### 3. Error Monitoring Hook (`app.py`)

Integrates with Slack Bolt's error handler to:
- Intercept all application errors
- Detect `BrokenPipeError` patterns
- Record errors with timestamps for the health monitor

### 4. Docker Health Check Configuration (`Dockerfile`)

Defines a health check that:
- Runs every 30 seconds
- Times out after 5 seconds
- Requires 3 consecutive failures to mark container unhealthy
- Starts checking after 10 seconds (startup grace period)
- Automatically triggers container restart if unhealthy

## How It Works

```
App starts → HTTP server starts on :8080 → Error hook installed
                                              ↓
Socket Mode fails with BrokenPipeError → Monitor records error
                                              ↓
After 3 errors in 60s → Monitor marks unhealthy
                        ↓
Docker health check fails (/health returns 503)
                        ↓
After 3 failed checks → Docker marks container unhealthy
                        ↓
Docker restarts container (due to restart: unless-stopped policy)
                        ↓
Fresh start: new connections, fresh state → Success
```

## Configuration

### Adjusting Sensitivity

Edit `health_check.py` to change error detection thresholds:

```python
# In app.py startup
get_monitor()  # uses default: 3 errors in 60 seconds

# Or customize:
from health_check import ConnectionHealthMonitor
monitor = ConnectionHealthMonitor(error_threshold=2, window_seconds=45)
```

### Docker Health Check Timings

Edit the `HEALTHCHECK` instruction in `Dockerfile`:

```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=10s \
    CMD curl -f http://localhost:8080/health || exit 1
```

- `interval`: How often Docker checks health (30s)
- `timeout`: Max time to wait for check response (5s)
- `retries`: Consecutive failures before marking unhealthy (3)
- `start-period`: Grace period before checks start (10s)

### Docker Compose Override

If needed, override health check settings in `docker-compose.yml`:

```yaml
services:
  trivia-bot:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
      interval: 60s
      timeout: 5s
      retries: 2
      start_period: 20s
```

## Monitoring

### Check Health Status

```bash
# View container health status
docker ps

# View detailed health check logs
docker inspect --format='{{json .State.Health}}' <container-id> | jq

# View app logs to see error tracking
docker logs <container-name> | grep "Connection"
```

### Example Logs

When errors occur:
```
2026-07-02 14:53:30,849 [ERROR] slack_bolt.App: on_error invoked (...BrokenPipeError...)
2026-07-02 14:53:41,166 [ERROR] slack_bolt.App: on_error invoked (...BrokenPipeError...)
2026-07-02 14:53:51,481 [ERROR] slack_bolt.App: on_error invoked (...BrokenPipeError...)
app: Connection unhealthy: 3 errors in 60s window
```

Then Docker will restart, and you'll see:
```
app: Health check server started on port 8080
app: Trivia Bot starting...
app: Connection recovered, marked as healthy
```

## Limitations & Future Improvements

- Currently only detects `BrokenPipeError`; could extend to other connection error patterns
- Could add metrics collection (Prometheus, CloudWatch) for monitoring
- Could add exponential backoff to reconnection logic (upstream in Slack Bolt library)
- Manual recovery signal could be added to allow apps to report health beyond connection state

## Testing

To manually test the health check locally:

```bash
# Start the app
python app.py

# In another terminal, check health
curl http://localhost:8080/health
# Should return 200 OK

# Or with docker:
docker build -t slack-trivia-bot .
docker run --env-file .env slack-trivia-bot
docker exec <container-id> curl -f http://localhost:8080/health
```

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


class ConnectionHealthMonitor:
    """
    Monitors Socket Mode connection health and detects when the bot is stuck
    in a broken pipe / reconnection loop.
    """

    def __init__(self, error_threshold: int = 3, window_seconds: int = 60, startup_grace_seconds: int = 30):
        """
        Args:
            error_threshold: Number of BrokenPipeErrors in the window to mark unhealthy
            window_seconds: Time window for counting errors
            startup_grace_seconds: Grace period after startup before health checks are strict
        """
        self.error_threshold = error_threshold
        self.window_seconds = window_seconds
        self.startup_grace_seconds = startup_grace_seconds

        self._lock = threading.Lock()
        self._error_times: list[datetime] = []
        self._startup_time = datetime.now()
        self._is_healthy = True
        self._has_connected_successfully = False

    def _is_in_startup_grace_period(self) -> bool:
        """Check if we're still in the startup grace period."""
        elapsed = (datetime.now() - self._startup_time).total_seconds()
        return elapsed < self.startup_grace_seconds

    def record_error(self) -> None:
        """Record a BrokenPipeError timestamp."""
        with self._lock:
            # Don't mark unhealthy during startup grace period
            if self._is_in_startup_grace_period():
                logger.debug("Error during startup grace period, deferring health check")
                return

            now = datetime.now()
            self._error_times.append(now)
            # Clean up old errors outside the window
            cutoff = now - timedelta(seconds=self.window_seconds)
            self._error_times = [t for t in self._error_times if t > cutoff]

            # Check if we're now unhealthy
            if len(self._error_times) >= self.error_threshold:
                self._is_healthy = False
                logger.error(
                    f"Connection unhealthy: {len(self._error_times)} errors "
                    f"in {self.window_seconds}s window"
                )

    def is_healthy(self) -> bool:
        """
        Check if the connection is healthy.
        Returns True if no error threshold breached, False if stuck in error loop.
        """
        with self._lock:
            # If we're in startup grace period, always report healthy
            if self._is_in_startup_grace_period():
                return True
            return self._is_healthy

    def mark_connected(self) -> None:
        """Mark that we've successfully connected at least once."""
        with self._lock:
            if not self._has_connected_successfully:
                self._has_connected_successfully = True
                logger.info("Connection established successfully")

    def mark_recovered(self) -> None:
        """Mark the connection as recovered (called after successful reconnect)."""
        with self._lock:
            self._error_times.clear()
            self._is_healthy = True
            logger.info("Connection recovered, marked as healthy")

    def reset(self) -> None:
        """Reset the monitor (for testing or manual reset)."""
        with self._lock:
            self._error_times.clear()
            self._is_healthy = True
            self._startup_time = datetime.now()


# Global monitor instance
_monitor: Optional[ConnectionHealthMonitor] = None


def get_monitor() -> ConnectionHealthMonitor:
    """Get or create the global health monitor."""
    global _monitor
    if _monitor is None:
        _monitor = ConnectionHealthMonitor()
    return _monitor

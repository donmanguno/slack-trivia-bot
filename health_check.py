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

    def __init__(self, error_threshold: int = 3, window_seconds: int = 60):
        """
        Args:
            error_threshold: Number of BrokenPipeErrors in the window to mark unhealthy
            window_seconds: Time window for counting errors
        """
        self.error_threshold = error_threshold
        self.window_seconds = window_seconds

        self._lock = threading.Lock()
        self._error_times: list[datetime] = []
        self._last_healthy_check: Optional[datetime] = None
        self._is_healthy = True

    def record_error(self) -> None:
        """Record a BrokenPipeError timestamp."""
        with self._lock:
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
            return self._is_healthy

    def mark_recovered(self) -> None:
        """Mark the connection as recovered (called after successful reconnect)."""
        with self._lock:
            self._error_times.clear()
            self._is_healthy = True
            self._last_healthy_check = datetime.now()
            logger.info("Connection recovered, marked as healthy")

    def reset(self) -> None:
        """Reset the monitor (for testing or manual reset)."""
        with self._lock:
            self._error_times.clear()
            self._is_healthy = True


# Global monitor instance
_monitor: Optional[ConnectionHealthMonitor] = None


def get_monitor() -> ConnectionHealthMonitor:
    """Get or create the global health monitor."""
    global _monitor
    if _monitor is None:
        _monitor = ConnectionHealthMonitor()
    return _monitor

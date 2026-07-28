import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class ConnectionHealthMonitor:
    """
    Monitors Socket Mode connection health and detects when the bot is stuck
    in a broken pipe / reconnection loop.
    """

    def __init__(
        self,
        error_threshold: int = 3,
        window_seconds: int = 20,
        startup_grace_seconds: int = 15,
        exit_callback: Optional[Callable] = None,
    ):
        """
        Args:
            error_threshold: Number of BrokenPipeErrors in the window to mark unhealthy
            window_seconds: Time window for counting errors
            startup_grace_seconds: Grace period after startup before health checks are strict
            exit_callback: Optional callback to call when we detect failure (e.g. sys.exit)
        """
        self.error_threshold = error_threshold
        self.window_seconds = window_seconds
        self.startup_grace_seconds = startup_grace_seconds
        self.exit_callback = exit_callback

        self._lock = threading.Lock()
        self._error_times: list[datetime] = []
        self._startup_time = datetime.now()
        self._is_healthy = True
        self._has_connected_successfully = False

    def _is_in_startup_grace_period(self) -> bool:
        """Check if we're still in the startup grace period."""
        elapsed = (datetime.now() - self._startup_time).total_seconds()
        in_grace = elapsed < self.startup_grace_seconds
        if in_grace:
            logger.debug(f"In startup grace period ({elapsed:.1f}s / {self.startup_grace_seconds}s)")
        return in_grace

    def record_error(self) -> None:
        """Record a BrokenPipeError timestamp."""
        with self._lock:
            now = datetime.now()
            elapsed = (now - self._startup_time).total_seconds()

            self._error_times.append(now)
            # Clean up old errors outside the window
            cutoff = now - timedelta(seconds=self.window_seconds)
            self._error_times = [t for t in self._error_times if t > cutoff]

            error_count = len(self._error_times)
            logger.warning(
                f"BrokenPipeError recorded (startup: {elapsed:.1f}s, errors in window: {error_count}/{self.error_threshold})"
            )

            # Skip health check during startup grace period
            if self._is_in_startup_grace_period():
                logger.info("Error during startup grace period, deferring health decision")
                return

            # Check if we're now unhealthy (after grace period)
            if error_count >= self.error_threshold:
                self._is_healthy = False
                logger.error(
                    f"UNHEALTHY: {error_count} errors in {self.window_seconds}s window - initiating shutdown"
                )
                if self.exit_callback:
                    self.exit_callback()

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
                logger.info("✓ Connection established successfully")

    def mark_recovered(self) -> None:
        """Mark the connection as recovered (called after successful reconnect)."""
        with self._lock:
            self._error_times.clear()
            self._is_healthy = True
            logger.info("✓ Connection recovered, cleared error history")

    def get_error_count(self) -> int:
        """Get the current error count in the window."""
        with self._lock:
            return len(self._error_times)

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

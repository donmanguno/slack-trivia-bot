import logging
import os
import threading
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from trivia.bot import register_handlers
from health_check import get_monitor

load_dotenv()

# Set TRIVIA_DEBUG=1 in your .env to enable verbose logging
_debug = os.environ.get("TRIVIA_DEBUG", "0") == "1"
logging.basicConfig(
    level=logging.DEBUG if _debug else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# Quiet noisy third-party loggers unless in debug mode
if not _debug:
    logging.getLogger("slack_bolt").setLevel(logging.WARNING)
    logging.getLogger("slack_sdk").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

app = App(token=os.environ["SLACK_BOT_TOKEN"])
register_handlers(app)


class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP handler for Docker health checks."""

    def do_GET(self):
        if self.path == "/health":
            monitor = get_monitor()
            if monitor.is_healthy():
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(b"OK")
            else:
                self.send_response(503)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                error_count = monitor.get_error_count()
                self.wfile.write(f"Unhealthy: {error_count} errors detected".encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        logger.debug(f"Health check: {format % args}")


def start_health_check_server(port: int = 8080) -> None:
    """Start the health check HTTP server in a background thread."""
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"Health check server started on port {port}")


def setup_error_monitoring() -> None:
    """
    Set up error monitoring using a custom log handler that monitors error logs.
    """
    monitor = get_monitor()

    class ErrorMonitoringHandler(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.ERROR:
                msg = record.getMessage()
                # Check for BrokenPipeError in various formats
                if "BrokenPipeError" in msg or "Broken pipe" in msg or "[Errno 32]" in msg:
                    logger.debug(f"Captured error message: {msg}")
                    monitor.record_error()

    handler = ErrorMonitoringHandler()
    logging.getLogger("slack_bolt.app").addHandler(handler)
    logger.info("Error monitoring handler installed")


if __name__ == "__main__":
    def emergency_shutdown():
        """Called by health monitor when too many errors are detected."""
        logger.critical("Emergency shutdown triggered by health monitor")
        sys.exit(1)

    monitor = get_monitor()
    monitor.exit_callback = emergency_shutdown

    start_health_check_server()
    setup_error_monitoring()

    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])

    logger.info("Trivia Bot starting (debug=%s)...", _debug)

    try:
        handler.start()
    except KeyboardInterrupt:
        logger.info("Trivia Bot shutting down...")
        sys.exit(0)
    except Exception as e:
        logger.exception(f"Fatal error: {e}")
        sys.exit(1)

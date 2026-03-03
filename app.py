import logging
import os

from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from trivia.bot import register_handlers

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

if __name__ == "__main__":
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    logger.info("Trivia Bot starting (debug=%s)...", _debug)
    handler.start()

from __future__ import annotations

from pathlib import Path

from .base import QuestionPool, QuestionProvider
from .json_file import JEOPARDY_SCHEMA, JsonFileProvider
from .opentdb import OpenTDBProvider
from .trivia_api import TriviaAPIProvider

_DATA_DIR = Path(__file__).parent.parent.parent / "data"

# Ordered dict — display order in UI matches insertion order.
# Key = stable internal source name used in DB and commands.
_PROVIDERS: dict[str, QuestionProvider] = {
    "opentdb": OpenTDBProvider(),
    "trivia_api": TriviaAPIProvider(),
    "jeopardy": JsonFileProvider(_DATA_DIR / "jeopardy.json", JEOPARDY_SCHEMA),
}

# All valid source names, in display order
ALL_SOURCE_NAMES: list[str] = list(_PROVIDERS.keys())
DEFAULT_SOURCES: list[str] = ALL_SOURCE_NAMES[:]


def display_name(source_name: str) -> str:
    """Return the human-readable name for a source key."""
    provider = _PROVIDERS.get(source_name)
    return provider.name if provider else source_name


def build_pool(source_names: list[str] | None = None) -> QuestionPool:
    """Build a QuestionPool from a list of source keys.

    Passes ``None`` or an empty list to use all sources.
    Unknown keys are silently ignored. Falls back to all sources if the
    filtered list would be empty.
    """
    names = [n for n in (source_names or ALL_SOURCE_NAMES) if n in _PROVIDERS]
    providers = [_PROVIDERS[n] for n in names] or list(_PROVIDERS.values())
    return QuestionPool(providers)

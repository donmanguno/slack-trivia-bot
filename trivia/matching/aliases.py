from __future__ import annotations

# Bidirectional alias mappings: any value in the set matches any other value.
# All entries should be lowercase.
ALIAS_GROUPS: list[set[str]] = [
    {"united states", "united states of america", "us", "usa", "america"},
    {"united kingdom", "uk", "great britain", "britain", "england"},
    {"new york city", "nyc", "new york"},
    {"los angeles", "la"},
    {"san francisco", "sf"},
    {"washington dc", "washington d c", "dc"},
    {"world war 1", "world war i", "wwi", "ww1", "first world war", "great war"},
    {"world war 2", "world war ii", "wwii", "ww2", "second world war"},
    {"martin luther king jr", "martin luther king", "mlk"},
    {"franklin d roosevelt", "franklin roosevelt", "fdr"},
    {"john f kennedy", "john kennedy", "jfk"},
    {"abraham lincoln", "abe lincoln"},
    {"mount everest", "mt everest", "everest"},
    {"pacific ocean", "pacific"},
    {"atlantic ocean", "atlantic"},
    {"carbon dioxide", "co2"},
    {"deoxyribonucleic acid", "dna"},
    {"ribonucleic acid", "rna"},
    {"artificial intelligence", "ai"},
    {"central intelligence agency", "cia"},
    {"federal bureau of investigation", "fbi"},
    {"national aeronautics and space administration", "nasa"},
    {"european union", "eu"},
    {"united nations", "un"},
]

_LOOKUP: dict[str, set[str]] | None = None


def _build_lookup() -> dict[str, set[str]]:
    global _LOOKUP
    if _LOOKUP is None:
        _LOOKUP = {}
        for group in ALIAS_GROUPS:
            for alias in group:
                _LOOKUP[alias] = group
    return _LOOKUP


def get_aliases(text: str) -> set[str]:
    """Return all known aliases for a given text (lowercase), including itself."""
    lookup = _build_lookup()
    return lookup.get(text.lower(), set())


def are_aliases(a: str, b: str) -> bool:
    """Check if two strings are known aliases of each other."""
    a_lower = a.lower()
    b_lower = b.lower()
    if a_lower == b_lower:
        return True
    aliases = get_aliases(a_lower)
    return b_lower in aliases if aliases else False

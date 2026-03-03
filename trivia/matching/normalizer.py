from __future__ import annotations

import re
import unicodedata

LEADING_ARTICLES = re.compile(r"^(the|a|an)\s+", re.IGNORECASE)
WHITESPACE = re.compile(r"\s+")
PUNCTUATION = re.compile(r"[^\w\s]")

NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
    "million": "1000000",
}


def normalize(text: str) -> str:
    """Apply full normalization pipeline to a string."""
    text = unicodedata.normalize("NFKD", text)
    text = text.lower().strip()
    text = PUNCTUATION.sub("", text)
    text = LEADING_ARTICLES.sub("", text)
    text = WHITESPACE.sub(" ", text).strip()
    return text


def normalize_number_words(text: str) -> str:
    """Convert number words to digits where possible."""
    words = text.split()
    result = []
    for word in words:
        result.append(NUMBER_WORDS.get(word, word))
    return " ".join(result)


def try_parse_number(text: str) -> float | None:
    """Try to interpret text as a number. Uses light normalization to preserve decimals."""
    cleaned = text.lower().strip()
    cleaned = normalize_number_words(cleaned)

    try:
        return float(cleaned.replace(",", "").replace(" ", ""))
    except ValueError:
        pass

    return None


def is_year(text: str) -> bool:
    """Check if text looks like a year (4-digit number between 1000-2100)."""
    stripped = normalize(text)
    if re.match(r"^\d{4}$", stripped):
        year = int(stripped)
        return 1000 <= year <= 2100
    return False


def extract_last_name(text: str) -> str | None:
    """Extract what looks like the last name from a full name."""
    normalized = normalize(text)
    parts = normalized.split()
    if len(parts) >= 2:
        return parts[-1]
    return None

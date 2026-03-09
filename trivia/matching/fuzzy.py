from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging

from rapidfuzz import fuzz

from .aliases import are_aliases
from .normalizer import (
    extract_last_name,
    is_year,
    normalize,
    try_parse_number,
)

logger = logging.getLogger(__name__)


class MatchResult(Enum):
    CORRECT = "correct"
    CLOSE = "close"
    WRONG = "wrong"


@dataclass
class AnswerCheck:
    result: MatchResult
    score: float = 0.0

    @property
    def is_correct(self) -> bool:
        return self.result == MatchResult.CORRECT

    @property
    def is_close(self) -> bool:
        return self.result == MatchResult.CLOSE


ACCEPT_THRESHOLD = 85.0
CLOSE_THRESHOLD = 70.0


def check_answer(
    user_answer: str,
    correct_answer: str,
    alternate_answers: list[str] | None = None,
) -> AnswerCheck:
    """
    Multi-layered answer checking:
    1. Normalization + exact match
    2. Alias matching
    3. Type-specific rules (years, numbers, names)
    4. RapidFuzz token_set_ratio
    """
    all_accepted = [correct_answer]
    if alternate_answers:
        all_accepted.extend(alternate_answers)

    user_norm = normalize(user_answer)
    if not user_norm:
        return AnswerCheck(MatchResult.WRONG, 0.0)

    best_score = 0.0

    for accepted in all_accepted:
        accepted_norm = normalize(accepted)
        if not accepted_norm:
            continue

        # Layer 1: exact match after normalization
        if user_norm == accepted_norm:
            return AnswerCheck(MatchResult.CORRECT, 100.0)

        # Layer 2: alias check
        if are_aliases(user_norm, accepted_norm):
            return AnswerCheck(MatchResult.CORRECT, 100.0)

        # Layer 3: type-specific rules
        type_result = _check_type_specific(user_norm, accepted_norm)
        if type_result is not None:
            return type_result

        # Layer 4: fuzzy matching
        score = fuzz.token_set_ratio(user_norm, accepted_norm)
        best_score = max(best_score, score)

    if best_score >= ACCEPT_THRESHOLD:
        logger.info(f"AnswerCheck: CORRECT: {user_answer} -> {accepted_norm} (score: {best_score})")
    if best_score >= CLOSE_THRESHOLD:
        return AnswerCheck(MatchResult.CLOSE, best_score)

    return AnswerCheck(MatchResult.WRONG, best_score)


def _check_type_specific(user_norm: str, accepted_norm: str) -> AnswerCheck | None:
    # Year answers: exact match only
    if is_year(accepted_norm):
        if user_norm == accepted_norm:
            return AnswerCheck(MatchResult.CORRECT, 100.0)
        return AnswerCheck(MatchResult.WRONG, 0.0)

    # Numeric answers
    user_num = try_parse_number(user_norm)
    accepted_num = try_parse_number(accepted_norm)
    if user_num is not None and accepted_num is not None:
        if user_num == accepted_num:
            return AnswerCheck(MatchResult.CORRECT, 100.0)
        return AnswerCheck(MatchResult.WRONG, 0.0)

    # Person names: allow last-name-only match
    accepted_last = extract_last_name(accepted_norm)
    if accepted_last and user_norm == accepted_last:
        return AnswerCheck(MatchResult.CORRECT, 95.0)

    return None

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class UserScore:
    user_id: str
    channel_id: str
    total_score: int = 0
    correct_answers: int = 0


@dataclass
class QuestionRecord:
    id: Optional[int] = None
    channel_id: str = ""
    question_text: str = ""
    correct_answer: str = ""
    difficulty: str = ""
    source: str = ""
    points: int = 0
    asked_at: Optional[datetime] = None
    answered_by: Optional[str] = None
    answered_at: Optional[datetime] = None


@dataclass
class SoloPlayFreeze:
    user_id: str
    channel_id: str
    frozen_at: datetime
    expires_at: datetime

    @property
    def is_active(self) -> bool:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return now < self.expires_at

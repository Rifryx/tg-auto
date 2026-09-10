from enum import Enum


class CommentStatus(str, Enum):
    """Статус записи в comment_logs (PROJECT-STAGES §1.3)."""

    POSTED = "posted"
    FAILED = "failed"
    FLAGGED = "flagged"


class LLMProvider(str, Enum):
    """Провайдер LLM на уровне кампании (PROJECT-STAGES §1.3)."""

    DEEPSEEK = "deepseek"
    GEMINI = "gemini"

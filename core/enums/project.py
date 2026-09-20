"""Enum роли аккаунта в проекте (этап 2).

* main   — основной, рабочая лошадка;
* support— поддержка (лайки/просмотры для main);
* warmup — держится в прогреве, не для боевых кампаний;
* burner — расходник, готов сгореть.
"""

from __future__ import annotations

from enum import Enum


class AccountRole(str, Enum):
    MAIN = "main"
    SUPPORT = "support"
    WARMUP = "warmup"
    BURNER = "burner"

"""Live-алерты кампании прайминга (prompt 6.2).

Отдельный от health_alert канал: экран «Ход» и внешние дашборды
подписываются на ``priming.alert``. Отправитель — orchestrator (при
автопаузе кампании) или executor (при карантине аккаунта). Payload —
плоский JSON с ключом ``event`` и контекстом.

Publisher не обязателен: в тестах и dry-run вызывающий кладёт None,
и :func:`emit_priming_alert` тихо становится no-op'ом.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

get_logger = structlog.get_logger

PRIMING_ALERT_CHANNEL = "priming.alert"


def emit_priming_alert(publisher: Optional[Any], event: str, **payload) -> None:
    if publisher is None:
        return
    try:
        publisher.publish(PRIMING_ALERT_CHANNEL, {"event": event, **payload})
    except Exception:  # noqa: BLE001 — алерт не должен ронять хот-путь
        get_logger().warning("priming.alert.publish_failed", event=event)


__all__ = ["PRIMING_ALERT_CHANNEL", "emit_priming_alert"]

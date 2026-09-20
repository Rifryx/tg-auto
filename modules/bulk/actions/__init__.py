"""Экшн-реестр bulk-операций.

Импорт этого пакета регистрирует все встроенные действия (side-effect в
``registry`` при первом импорте модуля). Внешние действия могут добавляться в
реестр через :func:`modules.bulk.actions.registry.register`.
"""

from modules.bulk.actions import (  # noqa: F401 - импорт ради side-effect
    apply_profile,
    apply_profile_pool,
    assign_proxy,
    generate_and_apply_profile,
    join_channels,
    leave_channels,
    logout_other_sessions,
    publish_story,
    send_reactions,
    set_2fa,
    set_persona,
    set_privacy,
    view_channel_posts,
    view_stories,
)
from modules.bulk.actions.registry import (
    ACTION_REGISTRY,
    BulkAction,
    BulkActionResult,
    register,
)

__all__ = ["ACTION_REGISTRY", "BulkAction", "BulkActionResult", "register"]

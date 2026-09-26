"""Тела задач commenting.* (PROJECT-STAGES §5).

Логика — в ``modules/commenting/worker/runner`` и ``.../channels``; здесь только
тонкие обёртки для регистрации в диспетчере воркера.
"""

from __future__ import annotations

from modules.commenting.worker.backfill import backfill_channel
from modules.commenting.worker.verify import verify_comment
from modules.commenting.worker.channels import (
    leave_channel,
    resolve_channel,
    sync_account_subscriptions,
    sync_campaign_channels,
)
from modules.commenting.worker.runner import (
    on_channel_post,
    on_new_post,
    post_channel_comment,
    post_comment,
)

on_new_post_impl = on_new_post
post_comment_impl = post_comment
resolve_channel_impl = resolve_channel
leave_channel_impl = leave_channel
sync_campaign_channels_impl = sync_campaign_channels
sync_account_subscriptions_impl = sync_account_subscriptions
backfill_channel_impl = backfill_channel
verify_comment_impl = verify_comment
on_channel_post_impl = on_channel_post
post_channel_comment_impl = post_channel_comment

__all__ = [
    "on_new_post_impl",
    "post_comment_impl",
    "resolve_channel_impl",
    "leave_channel_impl",
    "sync_campaign_channels_impl",
    "sync_account_subscriptions_impl",
    "backfill_channel_impl",
    "verify_comment_impl",
    "on_channel_post_impl",
    "post_channel_comment_impl",
]

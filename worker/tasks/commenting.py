"""Тела задач commenting.* (PROJECT-STAGES §5).

Логика — в ``modules/commenting/worker/runner``; здесь только тонкие обёртки
для регистрации в диспетчере воркера.
"""

from __future__ import annotations

from modules.commenting.worker.runner import on_new_post, post_comment

on_new_post_impl = on_new_post
post_comment_impl = post_comment

__all__ = ["on_new_post_impl", "post_comment_impl"]

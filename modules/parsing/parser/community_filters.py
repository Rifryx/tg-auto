"""Фильтры сообществ (Discovery, этап 2).

Форма кандидата — dict со снапшотом канала/чата:
    kind, is_public, participants_count, has_linked_chat, last_post_days,
    is_verified, is_scam, is_fake, title, username.
Кандидат отбрасывается ПЕРВОЙ подходящей причиной.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

REASON_WRONG_KIND = "wrong_kind"
REASON_TOO_FEW = "too_few_participants"
REASON_TOO_MANY = "too_many_participants"
REASON_NOT_PUBLIC = "not_public"
REASON_NO_LINKED_CHAT = "no_linked_chat"
REASON_POST_TOO_OLD = "post_too_old"
REASON_SCAM_FAKE = "scam_fake"
REASON_NOT_VERIFIED = "not_verified"
REASON_TITLE_REGEX = "title_regex"
REASON_USERNAME_REGEX = "username_regex"


@dataclass
class CommunityFilterOptions:
    kind: Optional[str] = None  # "channel" | "chat" | None(любой)
    min_participants: Optional[int] = None
    max_participants: Optional[int] = None
    require_public: bool = False
    require_linked_chat: bool = False
    last_post_max_days: Optional[int] = None
    exclude_scam_fake: bool = True
    verified_only: bool = False
    title_regex: Optional[str] = None
    username_regex: Optional[str] = None

    def _rx(self, pattern: Optional[str]) -> Optional["re.Pattern[str]"]:
        if not pattern:
            return None
        try:
            return re.compile(pattern, re.IGNORECASE)
        except re.error:
            return None


def first_community_drop_reason(
    row: dict, options: CommunityFilterOptions
) -> Optional[str]:
    if options.kind and row.get("kind") != options.kind:
        return REASON_WRONG_KIND
    if options.exclude_scam_fake and (row.get("is_scam") or row.get("is_fake")):
        return REASON_SCAM_FAKE
    if options.verified_only and not row.get("is_verified"):
        return REASON_NOT_VERIFIED
    if options.require_public and not row.get("is_public"):
        return REASON_NOT_PUBLIC
    if options.require_linked_chat and not row.get("has_linked_chat"):
        return REASON_NO_LINKED_CHAT

    pc = row.get("participants_count")
    if options.min_participants is not None:
        if pc is None or pc < options.min_participants:
            return REASON_TOO_FEW
    if options.max_participants is not None:
        if pc is not None and pc > options.max_participants:
            return REASON_TOO_MANY

    if options.last_post_max_days is not None:
        days = row.get("last_post_days")
        if days is None or days > options.last_post_max_days:
            return REASON_POST_TOO_OLD

    if options.title_regex:
        rx = options._rx(options.title_regex)
        if rx is not None and not rx.search(row.get("title") or ""):
            return REASON_TITLE_REGEX
    if options.username_regex:
        rx = options._rx(options.username_regex)
        if rx is not None and not rx.search(row.get("username") or ""):
            return REASON_USERNAME_REGEX
    return None

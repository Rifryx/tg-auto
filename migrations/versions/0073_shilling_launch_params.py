"""Параметры запуска НейроШиллинга: темп, режимы целей, состав ролей.

Приводим модуль к функционалу, который пользователь видел у конкурента:

* ``max_parallel_chats`` — «Чаты идут: По одному / До 3 сразу». Раньше цели
  просто раскидывались по расписанию с накопительной задержкой, то есть
  фактически шли параллельно, как попадёт. Теперь 1 = следующий чат стартует
  только после завершения диалога в предыдущем (+ пауза), 2–3 = столько
  одновременных диалогов максимум.
* ``first_reply_delay_min_sec`` / ``..._max_sec`` — «Пауза до первой реплики»:
  сколько ждём перед ПЕРВЫМ сообщением в новом чате. Отличается от
  ``reply_delay_*`` (пауза между репликами внутри диалога): зайти в чат и
  сразу начать разговор — самый заметный паттерн.
* ``shuffle_lineup_between_chats`` — «Менять состав между чатами»: в каждом
  новом чате роли раздаются заново по случайным аккаунтам (кроме закреплённых
  через ``campaign_accounts.role_id``). Выключено — аккаунт играет одну роль
  везде (диалог не разваливается, когда у учёток разные имя/пол/аватар).
* ``pickup_replies_hours`` — «Подхватывать ответы N ч после диалога». Раньше
  окно было захардкожено в live_interception (_STALE_HOURS = 24).
* ``campaign_targets.mode`` — режим цели. До сих пор ЛЮБАЯ цель означала
  «резолвим канал, берём последний пост, пишем в комментарии». Теперь:
  ``link`` (как раньше, авто-определение), ``chat`` (пишем прямо в чат),
  ``channel_post`` (комментарии под КОНКРЕТНЫМ постом t.me/channel/123),
  ``channel_monitor`` (следим за новыми постами канала и заходим в каждый).
* ``campaign_targets.post_id`` / ``last_seen_post_id`` — id поста для
  ``channel_post`` и курсор уже обработанных постов для ``channel_monitor``.

Revision ID: 0073
Revises: 0072
Create Date: 2026-11-04
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0073"
down_revision: Union[str, None] = "0072"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Кампания: темп и состав ---------------------------------------
    op.add_column(
        "campaigns",
        sa.Column(
            "max_parallel_chats", sa.Integer(), nullable=False, server_default="1"
        ),
        schema="shilling",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "first_reply_delay_min_sec",
            sa.Integer(),
            nullable=False,
            server_default="300",
        ),
        schema="shilling",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "first_reply_delay_max_sec",
            sa.Integer(),
            nullable=False,
            server_default="900",
        ),
        schema="shilling",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "shuffle_lineup_between_chats",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        schema="shilling",
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "pickup_replies_hours", sa.Integer(), nullable=False, server_default="6"
        ),
        schema="shilling",
    )
    op.create_check_constraint(
        "max_parallel_chats_valid",
        "campaigns",
        "max_parallel_chats >= 1 AND max_parallel_chats <= 3",
        schema="shilling",
    )
    op.create_check_constraint(
        "first_reply_delay_range_valid",
        "campaigns",
        "first_reply_delay_min_sec >= 0 "
        "AND first_reply_delay_max_sec >= first_reply_delay_min_sec",
        schema="shilling",
    )
    op.create_check_constraint(
        "pickup_replies_hours_valid",
        "campaigns",
        "pickup_replies_hours >= 1 AND pickup_replies_hours <= 72",
        schema="shilling",
    )

    # --- Цели: режим + привязка к посту --------------------------------
    op.add_column(
        "campaign_targets",
        sa.Column("mode", sa.String(), nullable=False, server_default="link"),
        schema="shilling",
    )
    op.add_column(
        "campaign_targets",
        sa.Column("post_id", sa.BigInteger(), nullable=True),
        schema="shilling",
    )
    op.add_column(
        "campaign_targets",
        sa.Column("last_seen_post_id", sa.BigInteger(), nullable=True),
        schema="shilling",
    )
    op.create_check_constraint(
        "ck_campaign_targets_mode_allowed",
        "campaign_targets",
        "mode IN ('link', 'chat', 'channel_post', 'channel_monitor')",
        schema="shilling",
    )
    # Ключ дедупликации теперь включает post_id: один и тот же канал может
    # быть и на мониторинге (post_id IS NULL), и добавлен отдельными постами.
    # NULLS NOT DISTINCT (PG15+) обязателен — иначе Postgres считает все NULL
    # различными и дубли обычных целей перестали бы отсекаться вовсе.
    op.drop_constraint(
        "uq_campaign_targets_campaign_id_raw_input",
        "campaign_targets",
        schema="shilling",
        type_="unique",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_campaign_targets_campaign_raw_post "
        "ON shilling.campaign_targets (campaign_id, raw_input, post_id) "
        "NULLS NOT DISTINCT"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS shilling.uq_campaign_targets_campaign_raw_post")
    # Назад к (campaign_id, raw_input): дубли по посту сначала чистим, иначе
    # констрейнт не создастся.
    op.execute(
        "DELETE FROM shilling.campaign_targets a USING shilling.campaign_targets b "
        "WHERE a.id > b.id AND a.campaign_id = b.campaign_id "
        "AND a.raw_input = b.raw_input"
    )
    op.create_unique_constraint(
        "uq_campaign_targets_campaign_id_raw_input",
        "campaign_targets",
        ["campaign_id", "raw_input"],
        schema="shilling",
    )
    op.drop_constraint(
        "ck_campaign_targets_mode_allowed",
        "campaign_targets",
        schema="shilling",
        type_="check",
    )
    op.drop_column("campaign_targets", "last_seen_post_id", schema="shilling")
    op.drop_column("campaign_targets", "post_id", schema="shilling")
    op.drop_column("campaign_targets", "mode", schema="shilling")

    op.drop_constraint(
        "pickup_replies_hours_valid", "campaigns", schema="shilling", type_="check"
    )
    op.drop_constraint(
        "first_reply_delay_range_valid",
        "campaigns",
        schema="shilling",
        type_="check",
    )
    op.drop_constraint(
        "max_parallel_chats_valid", "campaigns", schema="shilling", type_="check"
    )
    op.drop_column("campaigns", "pickup_replies_hours", schema="shilling")
    op.drop_column("campaigns", "shuffle_lineup_between_chats", schema="shilling")
    op.drop_column("campaigns", "first_reply_delay_max_sec", schema="shilling")
    op.drop_column("campaigns", "first_reply_delay_min_sec", schema="shilling")
    op.drop_column("campaigns", "max_parallel_chats", schema="shilling")

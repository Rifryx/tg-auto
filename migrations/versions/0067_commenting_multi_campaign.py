"""Commenting: аккаунт может работать в нескольких кампаниях одновременно.

Пользователь явно запросил поведение «если аккаунт занят, он всё равно должен
поддерживать многопоточность задач». Для этого убираем эксклюзивность
``account_id`` в ``commenting.campaign_accounts``.

PK ``(campaign_id, account_id)`` остаётся — он гарантирует «одна строка на
пару», т.е. один аккаунт нельзя добавить дважды в одну и ту же кампанию.
Но один аккаунт теперь может иметь N строк (по одной на каждую кампанию,
в которой он работает).

На ``accounts.assigned_container_type/id`` этот коммит пока не влияет: там
хранится «первая прикреплённая» кампания, а полный список берётся через
``CampaignAccountRepository.list_by_account``.

Revision ID: 0067
Revises: 0066
Create Date: 2026-10-28
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0067"
down_revision: Union[str, None] = "0066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_campaign_accounts_account_id",
        "campaign_accounts",
        schema="commenting",
        type_="unique",
    )


def downgrade() -> None:
    op.create_unique_constraint(
        "uq_campaign_accounts_account_id",
        "campaign_accounts",
        ["account_id"],
        schema="commenting",
    )

"""CHECK constraints для health_events.triggered_status_change и
accounts.previous_status (backlog #прочее).

* Раньше оба поля были свободным ``String`` — мусор мог попасть при багах
  вызывающего кода. Теперь БД гарантирует набор значений.
* ``triggered_status_change`` ∈ (NULL, cooldown, banned, retired) —
  формализовано под enum :class:`core.enums.TriggeredStatusChange`.
* ``previous_status`` ∈ (NULL, pool, assigned) — единственные точки, куда
  аккаунт может «вернуться» из cooldown (PROJECT-STAGES §1.2).

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-22
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # health_events.triggered_status_change
    op.create_check_constraint(
        "triggered_status_change_allowed",
        "health_events",
        "triggered_status_change IS NULL OR "
        "triggered_status_change IN ('cooldown', 'banned', 'retired')",
    )
    # accounts.previous_status
    op.create_check_constraint(
        "previous_status_allowed",
        "accounts",
        "previous_status IS NULL OR previous_status IN ('pool', 'assigned')",
    )


def downgrade() -> None:
    op.drop_constraint("previous_status_allowed", "accounts", type_="check")
    op.drop_constraint(
        "triggered_status_change_allowed", "health_events", type_="check"
    )

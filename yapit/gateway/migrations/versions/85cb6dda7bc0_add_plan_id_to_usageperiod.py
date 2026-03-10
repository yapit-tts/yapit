"""add plan_id to usageperiod

Revision ID: 85cb6dda7bc0
Revises: a5b9e7f3d359
Create Date: 2026-03-09 22:59:20.044707

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "85cb6dda7bc0"
down_revision: Union[str, None] = "a5b9e7f3d359"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usageperiod", sa.Column("plan_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_usageperiod_plan_id", "usageperiod", "plan", ["plan_id"], ["id"])

    # Backfill existing periods from the user's current subscription plan
    op.execute("""
        UPDATE usageperiod
        SET plan_id = us.plan_id
        FROM usersubscription us
        WHERE usageperiod.user_id = us.user_id
          AND usageperiod.plan_id IS NULL
    """)


def downgrade() -> None:
    op.drop_constraint("fk_usageperiod_plan_id", "usageperiod", type_="foreignkey")
    op.drop_column("usageperiod", "plan_id")

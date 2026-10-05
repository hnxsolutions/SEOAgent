"""Autonomous schedule types and the uniqueness that makes provisioning idempotent.

Adds the six schedule types the autonomous loop needs (health monitoring,
content research, drafting, content performance, internal linking, monthly
content strategy) and a unique index on the natural key of a schedule.

The index is what actually enforces "running the provisioner twice does not
create two identical schedules". `day_of_week` and `day_of_month` are nullable
and Postgres treats NULLs in a unique index as distinct, so a plain index on
those columns would let every daily schedule be created again and again —
hence COALESCE to a sentinel that cannot collide with a real weekday (0-6) or
day of month (1-31).

Revision ID: 0044_autonomous_schedules
Revises: 0043_growth_snapshots
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0044_autonomous_schedules"
down_revision: Union[str, None] = "0043_growth_snapshots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_SCHEDULE_TYPES = (
    "daily_health_monitor",
    "content_opportunity_scan",
    "blog_generation",
    "weekly_content_performance",
    "weekly_internal_link_scan",
    "monthly_content_strategy",
)

UNIQUE_INDEX = "uq_seo_schedules_project_type_slot"


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block on older
    # servers; COMMIT first so each value is applied on its own, matching the
    # pattern migration 0019 already established for this enum.
    op.execute("COMMIT")
    for value in NEW_SCHEDULE_TYPES:
        op.execute(f"ALTER TYPE seoscheduletype ADD VALUE IF NOT EXISTS '{value}'")

    # De-duplicate anything that predates the constraint, keeping the oldest row
    # of each natural key. Without this the index cannot be built on a database
    # that already ran the provisioner.
    op.execute(
        """
        DELETE FROM seo_schedules a
        USING seo_schedules b
        WHERE a.ctid > b.ctid
          AND a.project_id = b.project_id
          AND a.schedule_type = b.schedule_type
          AND COALESCE(a.day_of_week, -1) = COALESCE(b.day_of_week, -1)
          AND COALESCE(a.day_of_month, -1) = COALESCE(b.day_of_month, -1)
        """
    )

    op.execute(
        f"""
        CREATE UNIQUE INDEX IF NOT EXISTS {UNIQUE_INDEX}
        ON seo_schedules (
            project_id,
            schedule_type,
            COALESCE(day_of_week, -1),
            COALESCE(day_of_month, -1)
        )
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {UNIQUE_INDEX}")
    # Enum values are deliberately left in place: dropping one would fail for
    # any row still using it, and an unused value costs nothing.

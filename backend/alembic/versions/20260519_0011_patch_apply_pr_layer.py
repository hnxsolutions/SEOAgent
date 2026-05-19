"""Add patch apply and optional GitHub PR tables.

Revision ID: 0011_patch_apply_pr_layer
Revises: 0010_repo_code_agent
Create Date: 2026-05-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0011_patch_apply_pr_layer"
down_revision: Union[str, None] = "0010_repo_code_agent"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


patch_apply_run_status = postgresql.ENUM(
    "queued", "running", "completed", "failed", "rolled_back",
    name="patchapplyrunstatus",
    create_type=False,
)
patch_validation_status = postgresql.ENUM(
    "not_run", "passed", "failed",
    name="patchvalidationstatus",
    create_type=False,
)
patch_apply_result_status = postgresql.ENUM(
    "applied", "skipped", "failed", "rolled_back",
    name="patchapplyresultstatus",
    create_type=False,
)
pull_request_provider = postgresql.ENUM("github", name="pullrequestprovider", create_type=False)
pull_request_status = postgresql.ENUM(
    "draft", "open", "merged", "closed", "failed",
    name="pullrequeststatus",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    for enum_type in (
        patch_apply_run_status,
        patch_validation_status,
        patch_apply_result_status,
        pull_request_provider,
        pull_request_status,
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "patch_apply_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repo_connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scan_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branch_name", sa.String(length=255), nullable=True),
        sa.Column("status", patch_apply_run_status, nullable=False),
        sa.Column("patches_requested", sa.Integer(), nullable=True),
        sa.Column("patches_applied", sa.Integer(), nullable=True),
        sa.Column("patches_failed", sa.Integer(), nullable=True),
        sa.Column("validation_status", patch_validation_status, nullable=False),
        sa.Column("validation_output", sa.Text(), nullable=True),
        sa.Column("git_diff_summary", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["repo_connection_id"], ["repo_connections.id"]),
        sa.ForeignKeyConstraint(["scan_run_id"], ["repo_scan_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_patch_apply_runs_tenant_id", "patch_apply_runs", ["tenant_id"])
    op.create_index("ix_patch_apply_runs_project_id", "patch_apply_runs", ["project_id"])
    op.create_index("ix_patch_apply_runs_repo_connection_id", "patch_apply_runs", ["repo_connection_id"])
    op.create_index("ix_patch_apply_runs_scan_run_id", "patch_apply_runs", ["scan_run_id"])
    op.create_index("ix_patch_apply_runs_branch_name", "patch_apply_runs", ["branch_name"])
    op.create_index("ix_patch_apply_runs_status", "patch_apply_runs", ["status"])
    op.create_index("ix_patch_apply_runs_validation_status", "patch_apply_runs", ["validation_status"])
    op.create_index("ix_patch_apply_runs_created_at", "patch_apply_runs", ["created_at"])
    op.create_index("ix_patch_apply_runs_tenant_project", "patch_apply_runs", ["tenant_id", "project_id"])
    op.create_index("ix_patch_apply_runs_scan_status", "patch_apply_runs", ["scan_run_id", "status"])

    op.create_table(
        "patch_apply_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("apply_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("patch_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_path", sa.String(length=2048), nullable=False),
        sa.Column("status", patch_apply_result_status, nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("original_content_hash", sa.String(length=64), nullable=True),
        sa.Column("new_content_hash", sa.String(length=64), nullable=True),
        sa.Column("backup_path", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["apply_run_id"], ["patch_apply_runs.id"]),
        sa.ForeignKeyConstraint(["patch_id"], ["seo_code_patches.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_patch_apply_results_tenant_id", "patch_apply_results", ["tenant_id"])
    op.create_index("ix_patch_apply_results_project_id", "patch_apply_results", ["project_id"])
    op.create_index("ix_patch_apply_results_apply_run_id", "patch_apply_results", ["apply_run_id"])
    op.create_index("ix_patch_apply_results_patch_id", "patch_apply_results", ["patch_id"])
    op.create_index("ix_patch_apply_results_file_path", "patch_apply_results", ["file_path"])
    op.create_index("ix_patch_apply_results_status", "patch_apply_results", ["status"])
    op.create_index("ix_patch_apply_results_created_at", "patch_apply_results", ["created_at"])
    op.create_index("ix_patch_apply_results_run_status", "patch_apply_results", ["apply_run_id", "status"])
    op.create_index("ix_patch_apply_results_tenant_project", "patch_apply_results", ["tenant_id", "project_id"])

    op.create_table(
        "pull_request_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repo_connection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("apply_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", pull_request_provider, nullable=False),
        sa.Column("branch_name", sa.String(length=255), nullable=False),
        sa.Column("base_branch", sa.String(length=255), nullable=False),
        sa.Column("commit_sha", sa.String(length=128), nullable=True),
        sa.Column("pr_number", sa.Integer(), nullable=True),
        sa.Column("pr_url", sa.String(length=2048), nullable=True),
        sa.Column("status", pull_request_status, nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["apply_run_id"], ["patch_apply_runs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["repo_connection_id"], ["repo_connections.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pull_request_records_tenant_id", "pull_request_records", ["tenant_id"])
    op.create_index("ix_pull_request_records_project_id", "pull_request_records", ["project_id"])
    op.create_index("ix_pull_request_records_repo_connection_id", "pull_request_records", ["repo_connection_id"])
    op.create_index("ix_pull_request_records_apply_run_id", "pull_request_records", ["apply_run_id"])
    op.create_index("ix_pull_request_records_provider", "pull_request_records", ["provider"])
    op.create_index("ix_pull_request_records_branch_name", "pull_request_records", ["branch_name"])
    op.create_index("ix_pull_request_records_base_branch", "pull_request_records", ["base_branch"])
    op.create_index("ix_pull_request_records_status", "pull_request_records", ["status"])
    op.create_index("ix_pull_request_records_created_at", "pull_request_records", ["created_at"])
    op.create_index("ix_pull_request_records_tenant_project", "pull_request_records", ["tenant_id", "project_id"])
    op.create_index("ix_pull_request_records_apply_status", "pull_request_records", ["apply_run_id", "status"])


def downgrade() -> None:
    op.drop_table("pull_request_records")
    op.drop_table("patch_apply_results")
    op.drop_table("patch_apply_runs")

    for enum_type in (
        pull_request_status,
        pull_request_provider,
        patch_apply_result_status,
        patch_validation_status,
        patch_apply_run_status,
    ):
        enum_type.drop(op.get_bind(), checkfirst=True)

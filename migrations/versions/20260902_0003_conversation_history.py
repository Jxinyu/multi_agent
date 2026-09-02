"""创建用户会话历史、消息与反馈表。

Revision ID: 20260902_0003
Revises: 20260812_0002
Create Date: 2026-09-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260902_0003"
down_revision: str | Sequence[str] | None = "20260812_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("thread_id", sa.String(128), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("waiting_prompt", sa.Text(), nullable=True),
        sa.Column("attachment_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'waiting', 'completed', 'failed', 'cancelled')",
            name="ck_conversations_status",
        ),
        sa.UniqueConstraint("tenant_id", "owner_id", "thread_id", name="uq_conversation_scope_thread"),
    )
    op.create_index("ix_conversations_thread_id", "conversations", ["thread_id"])
    op.create_index("ix_conversations_tenant_id", "conversations", ["tenant_id"])
    op.create_index("ix_conversations_owner_id", "conversations", ["owner_id"])
    op.create_index("ix_conversations_status", "conversations", ["status"])

    op.create_table(
        "conversation_messages",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("references", sa.JSON(), nullable=False),
        sa.Column("attachments", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'status', 'error')",
            name="ck_conversation_messages_role",
        ),
    )
    op.create_index(
        "ix_conversation_messages_conversation_id",
        "conversation_messages",
        ["conversation_id"],
    )
    op.create_index("ix_conversation_messages_created_at", "conversation_messages", ["created_at"])

    op.create_table(
        "conversation_feedback",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.String(64),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.String(64),
            sa.ForeignKey("conversation_messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("rating", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "rating IN ('helpful', 'not_helpful')",
            name="ck_conversation_feedback_rating",
        ),
        sa.UniqueConstraint("message_id", "user_id", name="uq_conversation_feedback_message_user"),
    )
    op.create_index(
        "ix_conversation_feedback_conversation_id",
        "conversation_feedback",
        ["conversation_id"],
    )
    op.create_index("ix_conversation_feedback_message_id", "conversation_feedback", ["message_id"])
    op.create_index("ix_conversation_feedback_user_id", "conversation_feedback", ["user_id"])


def downgrade() -> None:
    op.drop_table("conversation_feedback")
    op.drop_table("conversation_messages")
    op.drop_table("conversations")

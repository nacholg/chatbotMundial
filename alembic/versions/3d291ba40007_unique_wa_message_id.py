"""unique wa_message_id

Revision ID: 3d291ba40007
Revises: 8ff72946d54e
Create Date: 2026-03-05

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '3d291ba40007'
down_revision: Union[str, Sequence[str], None] = '8ff72946d54e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # eliminar índice anterior
    op.drop_index("ix_messages_wa_message_id", table_name="messages")

    # crear índice único solo para valores no nulos
    op.create_index(
        "ux_messages_wa_message_id_not_null",
        "messages",
        ["wa_message_id"],
        unique=True,
        postgresql_where=sa.text("wa_message_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ux_messages_wa_message_id_not_null", table_name="messages")

    op.create_index(
        "ix_messages_wa_message_id",
        "messages",
        ["wa_message_id"],
        unique=False
    )
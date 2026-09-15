"""Add totp_last_code_hash for literal TOTP-code replay detection.

SEC-TOTP-REPLAY-WINDOW (2026-09-15): totp_last_counter (AUTH-06) alone does
not detect replay once the server clock has advanced into the next 30s
window -- services/totp.py::verify()'s +/-1 drift tolerance still accepts
the same code there, and the pure counter-monotonicity check (last < counter)
then lets the CAS update through. This column stores sha256(last accepted
TOTP code) -- never the raw code -- so routers/auth.py::
_totp_replay_check_and_record() can reject literal code reuse regardless of
whether the time window has advanced.

Revision ID: a1c5e7f92b46
Revises: 8e9af7d00ffc
Create Date: 2026-09-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c5e7f92b46"
down_revision: Union[str, Sequence[str], None] = "8e9af7d00ffc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("totp_last_code_hash", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "totp_last_code_hash")

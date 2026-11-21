"""H12 N-910-14: Schluesselversion des Approval-Bindings.

Neue, nullable Spalte ``allocation_publication_decisions.approval_key_version``
(= ``tenants.dek_version`` des Schluessels, mit dem der ``approval_hash``
gebunden wurde; zusaetzlich im HMAC-Record). Eigene Revision nach P4, weil P4
(``24e7606245d3``) eingefroren ist und nicht in place geaendert wird.

Warum eine Spalte und nicht nur der Hash-Kontext: Ohne gespeicherte Version
laesst sich eine DEK-Rotation nicht von einer Manipulation unterscheiden
(der alte DEK ist nach ``rotate_tenant_dek`` weg, der Hash ist nicht mehr
nachrechenbar). Der Entscheid hat kein freies JSON-Feld
(``blocker_codes_json`` muss bei Publikation ``'[]'`` sein, ``schema_version``
ist per CHECK fixiert).

* Kein Backfill: eine publizierte Zeile ohne Version (Altpublikation vor H12)
  gilt im Lesepfad als ungueltig (``CCX_APPROVAL_KEY_VERSION_MISSING``).
* Bewusst kein CHECK: SQLite kann den bestehenden CHECK nur per Tabellen-
  Neuaufbau aendern; dabei gingen die Append-only-/Guard-Trigger verloren
  bzw. muessten neu angelegt werden. Die Pflicht erzwingt der einzige
  Schreiber (``publish_allocation``) und der Lesepfad.
* Append-only bleibt unberuehrt: ``ADD COLUMN`` ist DDL, kein UPDATE einer
  Zeile; die Trigger bleiben bestehen (SQLite ohne Batch-Modus).

Revision ID: b3f1c9d2e4a7
Revises: 24e7606245d3
Create Date: 2026-11-18
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b3f1c9d2e4a7"
down_revision: Union[str, None] = "24e7606245d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DECISIONS = "allocation_publication_decisions"


def upgrade() -> None:
    op.add_column(DECISIONS, sa.Column("approval_key_version", sa.Integer(), nullable=True))


def downgrade() -> None:
    # SQLite >= 3.35 kann DROP COLUMN ohne Tabellen-Neuaufbau (Trigger bleiben).
    op.drop_column(DECISIONS, "approval_key_version")

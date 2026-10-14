"""Atendimento v2: filas editaveis, etiquetas, versoes do fluxo e campos de historico.

Revision ID: 0031
Revises: 0030
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None

SEED = [("comercial", "Comercial", "#1e73f8", False), ("financeiro", "Financeiro", "#0f8b8d", False),
        ("suporte", "Suporte", "#7b3fe4", False), ("geral", "Geral", "#6b7a99", True)]


def upgrade():
    q = op.create_table(
        "wa_queues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(40), nullable=False, unique=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("color", sa.String(9), nullable=False, server_default="#1e73f8"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("alert_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("alert_to", sa.JSON()),
        sa.Column("wait_alert_min", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_wa_queues_slug", "wa_queues", ["slug"])
    old = {}
    try:  # avisos que ja estavam configurados por fila
        raw = op.get_bind().execute(sa.text("select value from settings where key='atendimento.config'")).scalar()
        old = (json.loads(raw) if raw else {}).get("queues") or {}
    except Exception:  # noqa: BLE001
        old = {}
    op.bulk_insert(q, [{"slug": s, "name": n, "color": c, "sort": i, "active": True, "system": sysq,
                        "alert_enabled": bool((old.get(s) or {}).get("alert_enabled")), "alert_to": (old.get(s) or {}).get("alert_to") or []}
                       for i, (s, n, c, sysq) in enumerate(SEED)])
    op.create_table(
        "wa_tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(40), nullable=False, unique=True),
        sa.Column("color", sa.String(9), nullable=False, server_default="#6b7a99"),
    )
    op.create_table(
        "wa_flow_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("saved_by", sa.String(255)),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_wa_flow_versions_saved_at", "wa_flow_versions", ["saved_at"])
    op.add_column("wa_conversations", sa.Column("closed_reason", sa.String(16)))
    op.add_column("wa_conversations", sa.Column("first_response_at", sa.DateTime(timezone=True)))
    op.add_column("wa_conversations", sa.Column("tags", sa.JSON()))
    op.add_column("wa_conversations", sa.Column("contact_name", sa.String(255)))


def downgrade():
    for c in ("contact_name", "tags", "first_response_at", "closed_reason"):
        op.drop_column("wa_conversations", c)
    op.drop_table("wa_flow_versions")
    op.drop_table("wa_tags")
    op.drop_table("wa_queues")

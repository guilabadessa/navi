"""Chamados: fila apagada nao trava mais (ON DELETE SET NULL) e numeracao por sequencia do banco (sem corrida).

Revision ID: 0026
Revises: 0025
"""
import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_constraint("tickets_queue_id_fkey", "tickets", type_="foreignkey")
    op.create_foreign_key("tickets_queue_id_fkey", "tickets", "ticket_queues", ["queue_id"], ["id"], ondelete="SET NULL")

    # sequencia continua de onde a numeracao manual (SELECT MAX+1) parou, sem repetir nem pular numero existente
    op.execute("CREATE SEQUENCE IF NOT EXISTS ticket_number_seq OWNED BY tickets.number")
    op.execute("SELECT setval('ticket_number_seq', COALESCE((SELECT MAX(number) FROM tickets), 1000))")
    op.execute("ALTER TABLE tickets ALTER COLUMN number SET DEFAULT nextval('ticket_number_seq')")


def downgrade():
    op.execute("ALTER TABLE tickets ALTER COLUMN number DROP DEFAULT")
    op.execute("DROP SEQUENCE IF EXISTS ticket_number_seq")
    op.drop_constraint("tickets_queue_id_fkey", "tickets", type_="foreignkey")
    op.create_foreign_key("tickets_queue_id_fkey", "tickets", "ticket_queues", ["queue_id"], ["id"])

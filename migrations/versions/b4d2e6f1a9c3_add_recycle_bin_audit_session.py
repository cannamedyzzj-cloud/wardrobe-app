"""add recycle bin, audit log, session version

Revision ID: b4d2e6f1a9c3
Revises: 8a3f1c02d4e5
Create Date: 2026-08-02 12:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b4d2e6f1a9c3'
down_revision = '8a3f1c02d4e5'
branch_labels = None
depends_on = None


def upgrade():
    # 1. Garment: 回收站字段
    with op.batch_alter_table('garments') as batch_op:
        batch_op.add_column(sa.Column('deleted_at', sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column('deleted_by_user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_garments_deleted_by', 'users', ['deleted_by_user_id'], ['id'])

    # 2. User: session_version
    with op.batch_alter_table('users') as batch_op:
        batch_op.add_column(sa.Column('session_version', sa.Integer(), nullable=True, server_default='0'))

    # 3. AuditLog 表
    op.create_table('audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('actor_user_id', sa.Integer(), nullable=True),
        sa.Column('wardrobe_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(50), nullable=False),
        sa.Column('target_type', sa.String(50), nullable=True),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('summary', sa.String(500), nullable=True),
        sa.Column('metadata_json', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_logs') as batch_op:
        batch_op.create_index('ix_audit_created', ['created_at'])
        batch_op.create_index('ix_audit_actor', ['actor_user_id'])
        batch_op.create_index('ix_audit_action', ['action'])
        batch_op.create_foreign_key('fk_audit_actor', 'users', ['actor_user_id'], ['id'])


def downgrade():
    with op.batch_alter_table('audit_logs') as batch_op:
        batch_op.drop_index('ix_audit_action')
        batch_op.drop_index('ix_audit_actor')
        batch_op.drop_index('ix_audit_created')
    op.drop_table('audit_logs')
    
    with op.batch_alter_table('users') as batch_op:
        batch_op.drop_column('session_version')
    
    with op.batch_alter_table('garments') as batch_op:
        batch_op.drop_constraint('fk_garments_deleted_by', type_='foreignkey')
        batch_op.drop_column('deleted_by_user_id')
        batch_op.drop_column('deleted_at')

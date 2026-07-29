"""make wardrobe_id not null

Revision ID: 8a3f1c02d4e5
Revises: 0c5f4679eeb1
Create Date: 2026-07-29 17:10:00.000000

第二阶段迁移：所有业务表的 wardrobe_id 改为 NOT NULL
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '8a3f1c02d4e5'
down_revision = '0c5f4679eeb1'
branch_labels = None
depends_on = None


TABLES = ['categories', 'brands', 'color_presets', 'location_presets', 'garments']


def upgrade():
    # 先确保没有 NULL 值（防止数据不一致）
    for table in TABLES:
        op.execute(f"UPDATE {table} SET wardrobe_id = 1 WHERE wardrobe_id IS NULL")
    
    # 使用 batch 模式修改为 NOT NULL（SQLite 兼容）
    for table in TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column('wardrobe_id',
                                  existing_type=sa.Integer(),
                                  nullable=False)


def downgrade():
    for table in TABLES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column('wardrobe_id',
                                  existing_type=sa.Integer(),
                                  nullable=True)

"""add multi-user models and wardrobe_id

Revision ID: 0c5f4679eeb1
Revises: 92824743f327
Create Date: 2026-07-29 16:46:00.680998

"""
from alembic import op
import sqlalchemy as sa


revision = '0c5f4679eeb1'
down_revision = '92824743f327'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=80), nullable=False),
    sa.Column('display_name', sa.String(length=100), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('is_system_admin', sa.Boolean(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_users_username'), ['username'], unique=True)

    op.create_table('wardrobes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=100), nullable=False),
    sa.Column('owner_user_id', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], name='fk_wardrobes_owner'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('wardrobes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_wardrobes_owner_user_id'), ['owner_user_id'], unique=False)

    op.create_table('wardrobe_members',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('wardrobe_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE', name='fk_wm_user'),
    sa.ForeignKeyConstraint(['wardrobe_id'], ['wardrobes.id'], ondelete='CASCADE', name='fk_wm_wardrobe'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('wardrobe_id', 'user_id', name='uq_wardrobe_member')
    )
    with op.batch_alter_table('wardrobe_members', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_wardrobe_members_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_wardrobe_members_wardrobe_id'), ['wardrobe_id'], unique=False)

    with op.batch_alter_table('brands', schema=None) as batch_op:
        batch_op.add_column(sa.Column('wardrobe_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_brands_wardrobe_id'), ['wardrobe_id'], unique=False)
        batch_op.create_foreign_key('fk_brands_wardrobe', 'wardrobes', ['wardrobe_id'], ['id'])

    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.add_column(sa.Column('wardrobe_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_categories_wardrobe_id'), ['wardrobe_id'], unique=False)
        batch_op.create_foreign_key('fk_categories_wardrobe', 'wardrobes', ['wardrobe_id'], ['id'])

    with op.batch_alter_table('color_presets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('wardrobe_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_color_presets_wardrobe_id'), ['wardrobe_id'], unique=False)
        batch_op.create_foreign_key('fk_colors_wardrobe', 'wardrobes', ['wardrobe_id'], ['id'])

    with op.batch_alter_table('garments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('wardrobe_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('created_by_user_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('updated_by_user_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_garments_wardrobe_id'), ['wardrobe_id'], unique=False)
        batch_op.create_foreign_key('fk_garments_wardrobe', 'wardrobes', ['wardrobe_id'], ['id'])
        batch_op.create_foreign_key('fk_garments_created_by', 'users', ['created_by_user_id'], ['id'])
        batch_op.create_foreign_key('fk_garments_updated_by', 'users', ['updated_by_user_id'], ['id'])

    with op.batch_alter_table('location_presets', schema=None) as batch_op:
        batch_op.add_column(sa.Column('wardrobe_id', sa.Integer(), nullable=True))
        batch_op.create_index(batch_op.f('ix_location_presets_wardrobe_id'), ['wardrobe_id'], unique=False)
        batch_op.create_foreign_key('fk_locations_wardrobe', 'wardrobes', ['wardrobe_id'], ['id'])


def downgrade():
    with op.batch_alter_table('location_presets', schema=None) as batch_op:
        batch_op.drop_constraint('fk_locations_wardrobe', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_location_presets_wardrobe_id'))
        batch_op.drop_column('wardrobe_id')

    with op.batch_alter_table('garments', schema=None) as batch_op:
        batch_op.drop_constraint('fk_garments_updated_by', type_='foreignkey')
        batch_op.drop_constraint('fk_garments_created_by', type_='foreignkey')
        batch_op.drop_constraint('fk_garments_wardrobe', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_garments_wardrobe_id'))
        batch_op.drop_column('updated_by_user_id')
        batch_op.drop_column('created_by_user_id')
        batch_op.drop_column('wardrobe_id')

    with op.batch_alter_table('color_presets', schema=None) as batch_op:
        batch_op.drop_constraint('fk_colors_wardrobe', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_color_presets_wardrobe_id'))
        batch_op.drop_column('wardrobe_id')

    with op.batch_alter_table('categories', schema=None) as batch_op:
        batch_op.drop_constraint('fk_categories_wardrobe', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_categories_wardrobe_id'))
        batch_op.drop_column('wardrobe_id')

    with op.batch_alter_table('brands', schema=None) as batch_op:
        batch_op.drop_constraint('fk_brands_wardrobe', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_brands_wardrobe_id'))
        batch_op.drop_column('wardrobe_id')

    with op.batch_alter_table('wardrobe_members', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_wardrobe_members_wardrobe_id'))
        batch_op.drop_index(batch_op.f('ix_wardrobe_members_user_id'))

    op.drop_table('wardrobe_members')
    with op.batch_alter_table('wardrobes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_wardrobes_owner_user_id'))

    op.drop_table('wardrobes')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_users_username'))

    op.drop_table('users')

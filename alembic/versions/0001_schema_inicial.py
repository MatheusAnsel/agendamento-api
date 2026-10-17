"""schema inicial

Revision ID: 0001
Revises: 
Create Date: 2026-10-17 18:42:19.854065

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # btree_gist permite combinar igualdade (resource_id) e sobreposicao de intervalos
    # na constraint de exclusao de bookings.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table('tenants',
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('slug', sa.String(length=80), nullable=False),
    sa.Column('timezone', sa.String(length=64), server_default='America/Sao_Paulo', nullable=False),
    sa.Column('availability_mode', sa.String(length=20), server_default='rules', nullable=False),
    sa.Column('auto_confirm', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('min_notice_minutes', sa.Integer(), server_default='60', nullable=False),
    sa.Column('max_advance_days', sa.Integer(), server_default='60', nullable=False),
    sa.Column('allowed_origins', postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
    sa.Column('form_config', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text('\'{"required_fields": ["name", "phone"], "optional_fields": ["email", "notes"], "custom_fields": []}\'::jsonb'), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("availability_mode IN ('rules', 'open_dates')", name=op.f('ck_tenants_availability_mode')),
    sa.CheckConstraint('max_advance_days > 0', name=op.f('ck_tenants_max_advance_positive')),
    sa.CheckConstraint('min_notice_minutes >= 0', name=op.f('ck_tenants_min_notice_non_negative')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenants')),
    sa.UniqueConstraint('slug', name='uq_tenants_slug')
    )
    op.create_table('admin_users',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_admin_users_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_users')),
    sa.UniqueConstraint('tenant_id', 'email', name='uq_admin_users_tenant_email')
    )
    op.create_index(op.f('ix_admin_users_tenant_id'), 'admin_users', ['tenant_id'], unique=False)
    op.create_table('api_keys',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('label', sa.String(length=80), server_default='default', nullable=False),
    sa.Column('key_prefix', sa.String(length=16), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_api_keys_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_api_keys')),
    sa.UniqueConstraint('key_hash', name='uq_api_keys_key_hash')
    )
    op.create_index(op.f('ix_api_keys_tenant_id'), 'api_keys', ['tenant_id'], unique=False)
    op.create_table('customers',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('phone', sa.String(length=20), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=True),
    sa.Column('consent_lgpd_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_customers_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_customers')),
    sa.UniqueConstraint('tenant_id', 'phone', name='uq_customers_tenant_phone')
    )
    op.create_index(op.f('ix_customers_tenant_id'), 'customers', ['tenant_id'], unique=False)
    op.create_table('resources',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_resources_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resources'))
    )
    op.create_index(op.f('ix_resources_tenant_id'), 'resources', ['tenant_id'], unique=False)
    op.create_table('services',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('duration_minutes', sa.Integer(), nullable=False),
    sa.Column('buffer_minutes', sa.Integer(), server_default='0', nullable=False),
    sa.Column('capacity', sa.Integer(), server_default='1', nullable=False),
    sa.Column('price_cents', sa.Integer(), nullable=True),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint('buffer_minutes >= 0', name=op.f('ck_services_buffer_non_negative')),
    sa.CheckConstraint('capacity >= 1', name=op.f('ck_services_capacity_positive')),
    sa.CheckConstraint('duration_minutes > 0', name=op.f('ck_services_duration_positive')),
    sa.CheckConstraint('price_cents IS NULL OR price_cents >= 0', name=op.f('ck_services_price_non_negative')),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_services_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_services'))
    )
    op.create_index(op.f('ix_services_tenant_id'), 'services', ['tenant_id'], unique=False)
    op.create_table('blocks',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('resource_id', sa.UUID(), nullable=True),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('reason', sa.String(length=200), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('end_at > start_at', name=op.f('ck_blocks_end_after_start')),
    sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], name=op.f('fk_blocks_resource_id_resources'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_blocks_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_blocks'))
    )
    op.create_index(op.f('ix_blocks_resource_id'), 'blocks', ['resource_id'], unique=False)
    op.create_index(op.f('ix_blocks_tenant_id'), 'blocks', ['tenant_id'], unique=False)
    op.create_table('bookings',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('resource_id', sa.UUID(), nullable=False),
    sa.Column('service_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('start_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('occupied_until', sa.DateTime(timezone=True), nullable=False),
    sa.Column('is_exclusive', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('status', sa.String(length=20), server_default='pendente', nullable=False),
    sa.Column('price_cents', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('custom_data', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('idempotency_key', sa.String(length=80), nullable=True),
    sa.Column('cancelled_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_reason', sa.String(length=200), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    postgresql.ExcludeConstraint((sa.column('resource_id'), '='), (sa.text("tstzrange(start_at, occupied_until, '[)')"), '&&'), where=sa.text("is_exclusive AND status <> 'cancelado'"), using='gist', name='ex_bookings_no_overlap'),
    sa.CheckConstraint("status IN ('pendente', 'confirmado', 'concluido', 'cancelado', 'nao_compareceu')", name=op.f('ck_bookings_status')),
    sa.CheckConstraint('end_at > start_at', name=op.f('ck_bookings_end_after_start')),
    sa.CheckConstraint('occupied_until >= end_at', name=op.f('ck_bookings_occupied_covers_end')),
    sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], name=op.f('fk_bookings_customer_id_customers'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], name=op.f('fk_bookings_resource_id_resources'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], name=op.f('fk_bookings_service_id_services'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_bookings_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_bookings')),
    sa.UniqueConstraint('tenant_id', 'idempotency_key', name='uq_bookings_tenant_idempotency'),
    sa.UniqueConstraint('token', name='uq_bookings_token')
    )
    op.create_index(op.f('ix_bookings_customer_id'), 'bookings', ['customer_id'], unique=False)
    op.create_index('ix_bookings_resource_start', 'bookings', ['resource_id', 'start_at'], unique=False)
    op.create_index('ix_bookings_tenant_start', 'bookings', ['tenant_id', 'start_at'], unique=False)
    op.create_table('date_exceptions',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('resource_id', sa.UUID(), nullable=True),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=True),
    sa.Column('end_time', sa.Time(), nullable=True),
    sa.Column('reason', sa.String(length=200), nullable=True),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("(kind = 'closed' AND start_time IS NULL AND end_time IS NULL) OR (kind = 'custom_hours' AND start_time IS NOT NULL AND end_time IS NOT NULL AND end_time > start_time)", name=op.f('ck_date_exceptions_times_match_kind')),
    sa.CheckConstraint("kind IN ('closed', 'custom_hours')", name=op.f('ck_date_exceptions_kind')),
    sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], name=op.f('fk_date_exceptions_resource_id_resources'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_date_exceptions_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_date_exceptions'))
    )
    op.create_index(op.f('ix_date_exceptions_date'), 'date_exceptions', ['date'], unique=False)
    op.create_index(op.f('ix_date_exceptions_resource_id'), 'date_exceptions', ['resource_id'], unique=False)
    op.create_index(op.f('ix_date_exceptions_tenant_id'), 'date_exceptions', ['tenant_id'], unique=False)
    op.create_table('service_resources',
    sa.Column('service_id', sa.UUID(), nullable=False),
    sa.Column('resource_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], name=op.f('fk_service_resources_resource_id_resources'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], name=op.f('fk_service_resources_service_id_services'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('service_id', 'resource_id', name=op.f('pk_service_resources'))
    )
    op.create_table('weekly_rules',
    sa.Column('tenant_id', sa.UUID(), nullable=False),
    sa.Column('resource_id', sa.UUID(), nullable=False),
    sa.Column('weekday', sa.SmallInteger(), nullable=False),
    sa.Column('start_time', sa.Time(), nullable=False),
    sa.Column('end_time', sa.Time(), nullable=False),
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('end_time > start_time', name=op.f('ck_weekly_rules_end_after_start')),
    sa.CheckConstraint('weekday BETWEEN 0 AND 6', name=op.f('ck_weekly_rules_weekday_range')),
    sa.ForeignKeyConstraint(['resource_id'], ['resources.id'], name=op.f('fk_weekly_rules_resource_id_resources'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants.id'], name=op.f('fk_weekly_rules_tenant_id_tenants'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_weekly_rules'))
    )
    op.create_index(op.f('ix_weekly_rules_resource_id'), 'weekly_rules', ['resource_id'], unique=False)
    op.create_index(op.f('ix_weekly_rules_tenant_id'), 'weekly_rules', ['tenant_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema (a extensao btree_gist e mantida, pois pode ser usada por outros objetos)."""
    op.drop_index(op.f('ix_weekly_rules_tenant_id'), table_name='weekly_rules')
    op.drop_index(op.f('ix_weekly_rules_resource_id'), table_name='weekly_rules')
    op.drop_table('weekly_rules')
    op.drop_table('service_resources')
    op.drop_index(op.f('ix_date_exceptions_tenant_id'), table_name='date_exceptions')
    op.drop_index(op.f('ix_date_exceptions_resource_id'), table_name='date_exceptions')
    op.drop_index(op.f('ix_date_exceptions_date'), table_name='date_exceptions')
    op.drop_table('date_exceptions')
    op.drop_index('ix_bookings_tenant_start', table_name='bookings')
    op.drop_index('ix_bookings_resource_start', table_name='bookings')
    op.drop_index(op.f('ix_bookings_customer_id'), table_name='bookings')
    op.drop_table('bookings')
    op.drop_index(op.f('ix_blocks_tenant_id'), table_name='blocks')
    op.drop_index(op.f('ix_blocks_resource_id'), table_name='blocks')
    op.drop_table('blocks')
    op.drop_index(op.f('ix_services_tenant_id'), table_name='services')
    op.drop_table('services')
    op.drop_index(op.f('ix_resources_tenant_id'), table_name='resources')
    op.drop_table('resources')
    op.drop_index(op.f('ix_customers_tenant_id'), table_name='customers')
    op.drop_table('customers')
    op.drop_index(op.f('ix_api_keys_tenant_id'), table_name='api_keys')
    op.drop_table('api_keys')
    op.drop_index(op.f('ix_admin_users_tenant_id'), table_name='admin_users')
    op.drop_table('admin_users')
    op.drop_table('tenants')

"""Add skincare_products catalog table and seed initial items

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-22

"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create skincare_products table
    op.create_table(
        "skincare_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("active_ingredient", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("usage_instructions", sa.Text(), nullable=True),
        sa.Column("default_time", sa.String(length=32), nullable=False, server_default=sa.text("'evening'")),
        sa.Column("schedule_days", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id"),
    )

    # Seed the initial products
    products = sa.table(
        "skincare_products",
        sa.column("name", sa.String),
        sa.column("type", sa.String),
        sa.column("active_ingredient", sa.String),
        sa.column("description", sa.Text),
        sa.column("usage_instructions", sa.Text),
        sa.column("default_time", sa.String),
        sa.column("schedule_days", sa.JSON),
        sa.column("active", sa.Boolean),
    )

    op.bulk_insert(
        products,
        [
            {
                "name": "Дифферин (Ретиноид)",
                "type": "Ретиноид",
                "active_ingredient": "Адапален 0.1%",
                "description": "Регулирует дифференцировку клеток фолликулов, снижает образование микрокомедонов и выраженность воспалений.",
                "usage_instructions": "Наносить тонким слоем на абсолютно сухую очищенную кожу. 5 раз в неделю (Пн, Ср, Чт, Пт, Вс).",
                "default_time": "evening",
                "schedule_days": [1, 3, 4, 5, 0],
                "active": True,
            },
            {
                "name": "Азелик (Азелаин)",
                "type": "Азелаин",
                "active_ingredient": "Азелаиновая кислота 15%",
                "description": "Оказывает противомикробное и противовоспалительное действие, осветляет поствоспалительную пигментацию (ПВГ / PIH).",
                "usage_instructions": "Используется совместно с ретиноидом. 5 раз в неделю (Пн, Ср, Чт, Пт, Вс).",
                "default_time": "evening",
                "schedule_days": [1, 3, 4, 5, 0],
                "active": True,
            },
            {
                "name": "Кислотный пилинг",
                "type": "Кислотный пилинг",
                "active_ingredient": "AHA/BHA кислоты",
                "description": "Глубоко отшелушивает ороговевшие клетки, выравнивает рельеф, очищает поры и ускоряет регенерацию.",
                "usage_instructions": "Нанести на 10-15 минут, смыть прохладной водой. Строго 2 раза в неделю, не совмещать с ретиноидами.",
                "default_time": "evening",
                "schedule_days": [2, 6],
                "active": True,
            },
            {
                "name": "Сыворотка + SPF",
                "type": "Ниацинамид + SPF",
                "active_ingredient": "Ниацинамид + Цинк / SPF 50+",
                "description": "Регулирует себум, укрепляет защитный барьер кожи, блокирует ультрафиолет и защищает от пигментации.",
                "usage_instructions": "Наносить утром. SPF обязателен при использовании ретиноидов и кислот круглый год.",
                "default_time": "morning",
                "schedule_days": [1, 2, 3, 4, 5, 6, 0],
                "active": True,
            },
            {
                "name": "Увлажняющий крем",
                "type": "Увлажнение",
                "active_ingredient": "Базовый крем",
                "description": "Интенсивно увлажняет, восстанавливает гидролипидный барьер, предотвращает сухость, стянутость и шелушение.",
                "usage_instructions": "Завершающий этап ухода. Наносить вечером через 15-20 минут после нанесения активных сывороток или ретиноидов.",
                "default_time": "both",
                "schedule_days": [1, 2, 3, 4, 5, 6, 0],
                "active": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("skincare_products")

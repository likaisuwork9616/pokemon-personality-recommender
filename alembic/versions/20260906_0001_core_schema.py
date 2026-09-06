"""Create the core Pokémon relational schema.

Revision ID: 20260906_0001
Revises:
Create Date: 2026-09-06
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260906_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Install pgvector and create the core relational tables."""

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "pokemon",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("pokedex_number", sa.Integer(), nullable=False),
        sa.Column(
            "form_key",
            sa.String(length=80),
            server_default=sa.text("'default'"),
            nullable=False,
        ),
        sa.Column("name_zh", sa.String(length=120), nullable=False),
        sa.Column("name_en", sa.String(length=120), nullable=False),
        sa.Column("category_zh", sa.String(length=160), nullable=True),
        sa.Column("genus", sa.String(length=160), nullable=True),
        sa.Column("generation", sa.SmallInteger(), nullable=False),
        sa.Column("habitat", sa.String(length=120), nullable=True),
        sa.Column("color", sa.String(length=80), nullable=True),
        sa.Column("shape", sa.String(length=120), nullable=True),
        sa.Column("growth_rate", sa.String(length=40), nullable=True),
        sa.Column("abilities", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("hidden_ability", sa.String(length=120), nullable=True),
        sa.Column("egg_groups", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("height_m", sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column("weight_kg", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("capture_rate", sa.SmallInteger(), nullable=True),
        sa.Column(
            "is_legendary",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_mythical",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_baby",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_outlier",
            sa.SmallInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "lof_outlier",
            sa.SmallInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "capture_rate IS NULL OR capture_rate BETWEEN 0 AND 255",
            name="ck_pokemon_capture_rate_range",
        ),
        sa.CheckConstraint(
            "generation BETWEEN 1 AND 9",
            name="ck_pokemon_generation_range",
        ),
        sa.CheckConstraint(
            "height_m IS NULL OR height_m > 0",
            name="ck_pokemon_height_positive",
        ),
        sa.CheckConstraint(
            "is_outlier IN (-1, 1)",
            name="ck_pokemon_is_outlier_label",
        ),
        sa.CheckConstraint(
            "length(trim(form_key)) > 0",
            name="ck_pokemon_form_key_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(name_en)) > 0",
            name="ck_pokemon_name_en_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(name_zh)) > 0",
            name="ck_pokemon_name_zh_not_blank",
        ),
        sa.CheckConstraint(
            "lof_outlier IN (-1, 1)",
            name="ck_pokemon_lof_outlier_label",
        ),
        sa.CheckConstraint(
            "pokedex_number > 0",
            name="ck_pokemon_pokedex_number_positive",
        ),
        sa.CheckConstraint(
            "weight_kg IS NULL OR weight_kg > 0",
            name="ck_pokemon_weight_positive",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pokemon"),
        sa.UniqueConstraint(
            "pokedex_number",
            "form_key",
            name="uq_pokemon_dex_form",
        ),
    )
    op.create_index(
        "ix_pokemon_active_dex",
        "pokemon",
        ["is_active", "pokedex_number", "form_key"],
        unique=False,
    )
    op.create_index(
        "ix_pokemon_generation_active",
        "pokemon",
        ["generation", "is_active"],
        unique=False,
    )

    op.create_table(
        "types",
        sa.Column("id", sa.SmallInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_en", sa.String(length=40), nullable=False),
        sa.Column("name_zh", sa.String(length=40), nullable=False),
        sa.CheckConstraint(
            "length(trim(code)) > 0",
            name="ck_types_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(name_en)) > 0",
            name="ck_types_name_en_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(name_zh)) > 0",
            name="ck_types_name_zh_not_blank",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_types"),
        sa.UniqueConstraint("code", name="uq_types_code"),
        sa.UniqueConstraint("name_en", name="uq_types_name_en"),
        sa.UniqueConstraint("name_zh", name="uq_types_name_zh"),
    )

    op.create_table(
        "pokemon_types",
        sa.Column("pokemon_id", sa.BigInteger(), nullable=False),
        sa.Column("type_id", sa.SmallInteger(), nullable=False),
        sa.Column("slot", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("slot IN (1, 2)", name="ck_pokemon_types_slot_valid"),
        sa.ForeignKeyConstraint(
            ["pokemon_id"],
            ["pokemon.id"],
            name="fk_pokemon_types_pokemon_id_pokemon",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["type_id"],
            ["types.id"],
            name="fk_pokemon_types_type_id_types",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("pokemon_id", "type_id", name="pk_pokemon_types"),
        sa.UniqueConstraint("pokemon_id", "slot", name="uq_pokemon_type_slot"),
    )
    op.create_index(
        "ix_pokemon_types_type_pokemon",
        "pokemon_types",
        ["type_id", "pokemon_id"],
        unique=False,
    )

    op.create_table(
        "pokemon_stats",
        sa.Column("pokemon_id", sa.BigInteger(), nullable=False),
        sa.Column("hp", sa.SmallInteger(), nullable=True),
        sa.Column("attack", sa.SmallInteger(), nullable=True),
        sa.Column("defense", sa.SmallInteger(), nullable=True),
        sa.Column("sp_attack", sa.SmallInteger(), nullable=True),
        sa.Column("sp_defense", sa.SmallInteger(), nullable=True),
        sa.Column("speed", sa.SmallInteger(), nullable=True),
        sa.Column("base_stat_total", sa.SmallInteger(), nullable=True),
        sa.Column("scaled_hp", sa.Double(), nullable=True),
        sa.Column("scaled_attack", sa.Double(), nullable=True),
        sa.Column("scaled_defense", sa.Double(), nullable=True),
        sa.Column("scaled_sp_attack", sa.Double(), nullable=True),
        sa.Column("scaled_sp_defense", sa.Double(), nullable=True),
        sa.Column("scaled_speed", sa.Double(), nullable=True),
        sa.Column("scaled_height_m", sa.Double(), nullable=True),
        sa.Column("scaled_weight_kg", sa.Double(), nullable=True),
        sa.CheckConstraint(
            "attack IS NULL OR attack >= 0",
            name="ck_pokemon_stats_attack_nonnegative",
        ),
        sa.CheckConstraint(
            "base_stat_total = hp + attack + defense + sp_attack + sp_defense + speed",
            name="ck_pokemon_stats_base_stat_total_consistent",
        ),
        sa.CheckConstraint(
            "base_stat_total IS NULL OR base_stat_total >= 0",
            name="ck_pokemon_stats_base_stat_total_nonnegative",
        ),
        sa.CheckConstraint(
            "defense IS NULL OR defense >= 0",
            name="ck_pokemon_stats_defense_nonnegative",
        ),
        sa.CheckConstraint(
            "hp IS NULL OR hp >= 0",
            name="ck_pokemon_stats_hp_nonnegative",
        ),
        sa.CheckConstraint(
            "sp_attack IS NULL OR sp_attack >= 0",
            name="ck_pokemon_stats_sp_attack_nonnegative",
        ),
        sa.CheckConstraint(
            "sp_defense IS NULL OR sp_defense >= 0",
            name="ck_pokemon_stats_sp_defense_nonnegative",
        ),
        sa.CheckConstraint(
            "speed IS NULL OR speed >= 0",
            name="ck_pokemon_stats_speed_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["pokemon_id"],
            ["pokemon.id"],
            name="fk_pokemon_stats_pokemon_id_pokemon",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("pokemon_id", name="pk_pokemon_stats"),
    )

    op.create_table(
        "pokemon_descriptions",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("pokemon_id", sa.BigInteger(), nullable=False),
        sa.Column("language_code", sa.String(length=10), nullable=False),
        sa.Column("description_kind", sa.String(length=40), nullable=False),
        sa.Column("source_key", sa.String(length=100), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "length(content_hash) = 64",
            name="ck_pokemon_descriptions_content_hash_length",
        ),
        sa.CheckConstraint(
            "length(trim(content)) > 0",
            name="ck_pokemon_descriptions_content_not_blank",
        ),
        sa.CheckConstraint(
            "description_kind IN ('description', 'flavor_text', 'analysis', 'admin_note')",
            name="ck_pokemon_descriptions_description_kind_valid",
        ),
        sa.CheckConstraint(
            "length(trim(language_code)) > 0",
            name="ck_pokemon_descriptions_language_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(source_key)) > 0",
            name="ck_pokemon_descriptions_source_key_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["pokemon_id"],
            ["pokemon.id"],
            name="fk_pokemon_descriptions_pokemon_id_pokemon",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pokemon_descriptions"),
        sa.UniqueConstraint(
            "pokemon_id",
            "language_code",
            "description_kind",
            "source_key",
            name="uq_pokemon_description_source",
        ),
    )
    op.create_index(
        "ix_pokemon_descriptions_pokemon",
        "pokemon_descriptions",
        ["pokemon_id"],
        unique=False,
    )
    op.create_index(
        "uq_pokemon_descriptions_primary",
        "pokemon_descriptions",
        ["pokemon_id", "language_code", "description_kind"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )

    op.create_table(
        "pokemon_images",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("pokemon_id", sa.BigInteger(), nullable=False),
        sa.Column("image_kind", sa.String(length=30), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "image_kind IN ('artwork', 'sprite')",
            name="ck_pokemon_images_image_kind_valid",
        ),
        sa.CheckConstraint(
            "length(trim(image_url)) > 0",
            name="ck_pokemon_images_image_url_not_blank",
        ),
        sa.ForeignKeyConstraint(
            ["pokemon_id"],
            ["pokemon.id"],
            name="fk_pokemon_images_pokemon_id_pokemon",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pokemon_images"),
        sa.UniqueConstraint(
            "pokemon_id",
            "image_kind",
            name="uq_pokemon_image_kind",
        ),
    )
    op.create_index(
        "ix_pokemon_images_pokemon",
        "pokemon_images",
        ["pokemon_id"],
        unique=False,
    )
    op.create_index(
        "uq_pokemon_images_primary",
        "pokemon_images",
        ["pokemon_id"],
        unique=True,
        postgresql_where=sa.text("is_primary"),
    )


def downgrade() -> None:
    """Remove all core tables and the extension owned by this migration."""

    op.drop_index("uq_pokemon_images_primary", table_name="pokemon_images")
    op.drop_index("ix_pokemon_images_pokemon", table_name="pokemon_images")
    op.drop_table("pokemon_images")

    op.drop_index(
        "uq_pokemon_descriptions_primary",
        table_name="pokemon_descriptions",
    )
    op.drop_index(
        "ix_pokemon_descriptions_pokemon",
        table_name="pokemon_descriptions",
    )
    op.drop_table("pokemon_descriptions")

    op.drop_table("pokemon_stats")
    op.drop_index("ix_pokemon_types_type_pokemon", table_name="pokemon_types")
    op.drop_table("pokemon_types")
    op.drop_table("types")

    op.drop_index("ix_pokemon_generation_active", table_name="pokemon")
    op.drop_index("ix_pokemon_active_dex", table_name="pokemon")
    op.drop_table("pokemon")

    op.execute("DROP EXTENSION IF EXISTS vector")

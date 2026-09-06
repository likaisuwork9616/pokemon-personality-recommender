"""Core relational models for imported and admin-managed Pokémon data."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Double,
    Computed,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import TSVECTOR

from app.db.base import Base


class Pokemon(Base):
    """One Pokémon species or form exposed by the catalog."""

    __tablename__ = "pokemon"
    __table_args__ = (
        UniqueConstraint("pokedex_number", "form_key", name="uq_pokemon_dex_form"),
        CheckConstraint("pokedex_number > 0", name="pokedex_number_positive"),
        CheckConstraint("length(trim(form_key)) > 0", name="form_key_not_blank"),
        CheckConstraint("length(trim(name_zh)) > 0", name="name_zh_not_blank"),
        CheckConstraint("length(trim(name_en)) > 0", name="name_en_not_blank"),
        CheckConstraint("generation BETWEEN 1 AND 9", name="generation_range"),
        CheckConstraint("height_m IS NULL OR height_m > 0", name="height_positive"),
        CheckConstraint("weight_kg IS NULL OR weight_kg > 0", name="weight_positive"),
        CheckConstraint(
            "capture_rate IS NULL OR capture_rate BETWEEN 0 AND 255",
            name="capture_rate_range",
        ),
        CheckConstraint("is_outlier IN (-1, 1)", name="is_outlier_label"),
        CheckConstraint("lof_outlier IN (-1, 1)", name="lof_outlier_label"),
        Index("ix_pokemon_active_dex", "is_active", "pokedex_number", "form_key"),
        Index("ix_pokemon_generation_active", "generation", "is_active"),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    pokedex_number: Mapped[int] = mapped_column(Integer, nullable=False)
    form_key: Mapped[str] = mapped_column(
        String(80),
        nullable=False,
        default="default",
        server_default=text("'default'"),
    )
    name_zh: Mapped[str] = mapped_column(String(120), nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    category_zh: Mapped[str | None] = mapped_column(String(160))
    genus: Mapped[str | None] = mapped_column(String(160))
    generation: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    habitat: Mapped[str | None] = mapped_column(String(120))
    color: Mapped[str | None] = mapped_column(String(80))
    shape: Mapped[str | None] = mapped_column(String(120))
    growth_rate: Mapped[str | None] = mapped_column(String(40))
    abilities: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    hidden_ability: Mapped[str | None] = mapped_column(String(120))
    egg_groups: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    height_m: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    capture_rate: Mapped[int | None] = mapped_column(SmallInteger)
    is_legendary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    is_mythical: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    is_baby: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    is_outlier: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    lof_outlier: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    type_links: Mapped[list[PokemonType]] = relationship(
        back_populates="pokemon",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    stats: Mapped[PokemonStats | None] = relationship(
        back_populates="pokemon",
        cascade="all, delete-orphan",
        passive_deletes=True,
        uselist=False,
    )
    descriptions: Mapped[list[PokemonDescription]] = relationship(
        back_populates="pokemon",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    images: Mapped[list[PokemonImage]] = relationship(
        back_populates="pokemon",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    knowledge_documents: Mapped[list[PokemonKnowledgeDocument]] = relationship(
        back_populates="pokemon",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Type(Base):
    """Canonical Pokémon elemental type lookup."""

    __tablename__ = "types"
    __table_args__ = (
        UniqueConstraint("code", name="uq_types_code"),
        UniqueConstraint("name_en", name="uq_types_name_en"),
        UniqueConstraint("name_zh", name="uq_types_name_zh"),
        CheckConstraint("length(trim(code)) > 0", name="code_not_blank"),
        CheckConstraint("length(trim(name_en)) > 0", name="name_en_not_blank"),
        CheckConstraint("length(trim(name_zh)) > 0", name="name_zh_not_blank"),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger,
        Identity(always=True),
        primary_key=True,
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name_en: Mapped[str] = mapped_column(String(40), nullable=False)
    name_zh: Mapped[str] = mapped_column(String(40), nullable=False)

    pokemon_links: Mapped[list[PokemonType]] = relationship(
        back_populates="type_record",
        passive_deletes=True,
    )


class PokemonType(Base):
    """Ordered many-to-many association between Pokémon and types."""

    __tablename__ = "pokemon_types"
    __table_args__ = (
        UniqueConstraint("pokemon_id", "slot", name="uq_pokemon_type_slot"),
        CheckConstraint("slot IN (1, 2)", name="slot_valid"),
        Index("ix_pokemon_types_type_pokemon", "type_id", "pokemon_id"),
    )

    pokemon_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("pokemon.id", ondelete="CASCADE"),
        primary_key=True,
    )
    type_id: Mapped[int] = mapped_column(
        SmallInteger,
        ForeignKey("types.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    slot: Mapped[int] = mapped_column(SmallInteger, nullable=False)

    pokemon: Mapped[Pokemon] = relationship(back_populates="type_links")
    type_record: Mapped[Type] = relationship(back_populates="pokemon_links")


class PokemonStats(Base):
    """One-to-one battle and normalized feature values for a Pokémon."""

    __tablename__ = "pokemon_stats"
    __table_args__ = (
        CheckConstraint("hp IS NULL OR hp >= 0", name="hp_nonnegative"),
        CheckConstraint("attack IS NULL OR attack >= 0", name="attack_nonnegative"),
        CheckConstraint("defense IS NULL OR defense >= 0", name="defense_nonnegative"),
        CheckConstraint(
            "sp_attack IS NULL OR sp_attack >= 0",
            name="sp_attack_nonnegative",
        ),
        CheckConstraint(
            "sp_defense IS NULL OR sp_defense >= 0",
            name="sp_defense_nonnegative",
        ),
        CheckConstraint("speed IS NULL OR speed >= 0", name="speed_nonnegative"),
        CheckConstraint(
            "base_stat_total IS NULL OR base_stat_total >= 0",
            name="base_stat_total_nonnegative",
        ),
        CheckConstraint(
            "base_stat_total = hp + attack + defense + sp_attack + sp_defense + speed",
            name="base_stat_total_consistent",
        ),
    )

    pokemon_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("pokemon.id", ondelete="CASCADE"),
        primary_key=True,
    )
    hp: Mapped[int | None] = mapped_column(SmallInteger)
    attack: Mapped[int | None] = mapped_column(SmallInteger)
    defense: Mapped[int | None] = mapped_column(SmallInteger)
    sp_attack: Mapped[int | None] = mapped_column(SmallInteger)
    sp_defense: Mapped[int | None] = mapped_column(SmallInteger)
    speed: Mapped[int | None] = mapped_column(SmallInteger)
    base_stat_total: Mapped[int | None] = mapped_column(SmallInteger)
    scaled_hp: Mapped[float | None] = mapped_column(Double)
    scaled_attack: Mapped[float | None] = mapped_column(Double)
    scaled_defense: Mapped[float | None] = mapped_column(Double)
    scaled_sp_attack: Mapped[float | None] = mapped_column(Double)
    scaled_sp_defense: Mapped[float | None] = mapped_column(Double)
    scaled_speed: Mapped[float | None] = mapped_column(Double)
    scaled_height_m: Mapped[float | None] = mapped_column(Double)
    scaled_weight_kg: Mapped[float | None] = mapped_column(Double)

    pokemon: Mapped[Pokemon] = relationship(back_populates="stats")


class PokemonDescription(Base):
    """Editable source-of-truth text used to derive retrieval documents."""

    __tablename__ = "pokemon_descriptions"
    __table_args__ = (
        UniqueConstraint(
            "pokemon_id",
            "language_code",
            "description_kind",
            "source_key",
            name="uq_pokemon_description_source",
        ),
        CheckConstraint(
            "description_kind IN ('description', 'flavor_text', 'analysis', 'admin_note')",
            name="description_kind_valid",
        ),
        CheckConstraint(
            "length(trim(language_code)) > 0",
            name="language_code_not_blank",
        ),
        CheckConstraint("length(trim(source_key)) > 0", name="source_key_not_blank"),
        CheckConstraint("length(trim(content)) > 0", name="content_not_blank"),
        CheckConstraint("length(content_hash) = 64", name="content_hash_length"),
        Index("ix_pokemon_descriptions_pokemon", "pokemon_id"),
        Index(
            "uq_pokemon_descriptions_primary",
            "pokemon_id",
            "language_code",
            "description_kind",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    pokemon_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("pokemon.id", ondelete="CASCADE"),
        nullable=False,
    )
    language_code: Mapped[str] = mapped_column(String(10), nullable=False)
    description_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    source_key: Mapped[str] = mapped_column(String(100), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    pokemon: Mapped[Pokemon] = relationship(back_populates="descriptions")
    knowledge_documents: Mapped[list[PokemonKnowledgeDocument]] = relationship(
        back_populates="source_description",
        passive_deletes=True,
    )


class PokemonImage(Base):
    """Artwork and sprite URLs associated with a Pokémon."""

    __tablename__ = "pokemon_images"
    __table_args__ = (
        UniqueConstraint("pokemon_id", "image_kind", name="uq_pokemon_image_kind"),
        CheckConstraint(
            "image_kind IN ('artwork', 'sprite')",
            name="image_kind_valid",
        ),
        CheckConstraint("length(trim(image_url)) > 0", name="image_url_not_blank"),
        Index("ix_pokemon_images_pokemon", "pokemon_id"),
        Index(
            "uq_pokemon_images_primary",
            "pokemon_id",
            unique=True,
            postgresql_where=text("is_primary"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=True),
        primary_key=True,
    )
    pokemon_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("pokemon.id", ondelete="CASCADE"),
        nullable=False,
    )
    image_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    image_url: Mapped[str] = mapped_column(Text, nullable=False)
    is_primary: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    pokemon: Mapped[Pokemon] = relationship(back_populates="images")


class PokemonKnowledgeDocument(Base):
    """Immutable, versioned RAG document derived from a traceable source."""

    __tablename__ = "pokemon_knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "pokemon_id",
            "source_key",
            "version",
            name="uq_knowledge_document_version",
        ),
        CheckConstraint("length(trim(source_key)) > 0", name="source_key_not_blank"),
        CheckConstraint(
            "length(trim(document_kind)) > 0",
            name="document_kind_not_blank",
        ),
        CheckConstraint(
            "length(trim(language_code)) > 0",
            name="language_code_not_blank",
        ),
        CheckConstraint("length(trim(content)) > 0", name="content_not_blank"),
        CheckConstraint("length(content_hash) = 64", name="content_hash_length"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "status IN ('ready', 'stale', 'failed')",
            name="status_valid",
        ),
        Index(
            "ix_knowledge_documents_pokemon_current",
            "pokemon_id",
            "is_current",
            "status",
        ),
        Index(
            "uq_knowledge_documents_current_source",
            "pokemon_id",
            "source_key",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    pokemon_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("pokemon.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_description_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "pokemon_descriptions.id",
            name="fk_knowledge_document_source_description",
            ondelete="SET NULL",
        ),
    )
    source_key: Mapped[str] = mapped_column(String(120), nullable=False)
    document_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    language_code: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ready",
        server_default=text("'ready'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    pokemon: Mapped[Pokemon] = relationship(back_populates="knowledge_documents")
    source_description: Mapped[PokemonDescription | None] = relationship(
        back_populates="knowledge_documents"
    )
    chunks: Mapped[list[PokemonKnowledgeChunk]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class PokemonKnowledgeChunk(Base):
    """Smallest traceable retrieval and citation unit for a document."""

    __tablename__ = "pokemon_knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "chunk_index",
            "content_hash",
            name="uq_knowledge_chunk_version",
        ),
        CheckConstraint("chunk_index >= 0", name="chunk_index_nonnegative"),
        CheckConstraint("length(trim(content)) > 0", name="content_not_blank"),
        CheckConstraint("length(content_hash) = 64", name="content_hash_length"),
        CheckConstraint("char_count > 0", name="char_count_positive"),
        CheckConstraint("token_count >= 0", name="token_count_nonnegative"),
        CheckConstraint(
            "status IN ('ready', 'stale', 'failed')",
            name="status_valid",
        ),
        Index(
            "ix_knowledge_chunks_document_current",
            "document_id",
            "is_current",
            "status",
        ),
        Index(
            "uq_knowledge_chunks_current_index",
            "document_id",
            "chunk_index",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        Index(
            "ix_knowledge_chunks_textsearch",
            "textsearch",
            postgresql_using="gin",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    document_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey(
            "pokemon_knowledge_documents.id",
            name="fk_knowledge_chunk_document",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    lexical_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    textsearch: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('simple', coalesce(lexical_text, ''))",
            persisted=True,
        ),
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="ready",
        server_default=text("'ready'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    document: Mapped[PokemonKnowledgeDocument] = relationship(back_populates="chunks")

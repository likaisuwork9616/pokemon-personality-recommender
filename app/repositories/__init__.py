"""Database repositories used by application services."""

from app.repositories.admin import AdminPokemonRepository
from app.repositories.admin_audit import AdminAuditRepository
from app.repositories.pokemon import PokemonRepository
from app.repositories.personality import PersonalityCatalog, PersonalityRepository
from app.repositories.retrieval import LexicalSearchHit, RetrievalRepository
from app.repositories.reindex import (
    IndexSourceState,
    PokemonIndexState,
    PokemonReindexRepository,
)
from app.repositories.vector import (
    EmbeddingCandidate,
    VectorRepository,
    VectorSearchHit,
)

__all__ = [
    "AdminPokemonRepository",
    "AdminAuditRepository",
    "EmbeddingCandidate",
    "LexicalSearchHit",
    "IndexSourceState",
    "PokemonIndexState",
    "PokemonRepository",
    "PersonalityCatalog",
    "PersonalityRepository",
    "PokemonReindexRepository",
    "RetrievalRepository",
    "VectorRepository",
    "VectorSearchHit",
]

"""Database repositories used by application services."""

from app.repositories.admin import AdminPokemonRepository
from app.repositories.admin_audit import AdminAuditRepository
from app.repositories.evaluation_admin import EvaluationAnnotationRepository
from app.repositories.recommendation_feedback import RecommendationFeedbackRepository
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
    "EvaluationAnnotationRepository",
    "RecommendationFeedbackRepository",
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

"""Shared catalog provider and atomic, model-specific scorer snapshots."""
from threading import Lock
from app.settings import MbtiCatalogSettings
from app.services import mbti_catalog
from app.services.mbti_scoring import MbtiScorer
from app.repositories.mbti_catalog import MbtiCatalogRepository


class MbtiCatalogProvider:
    def __init__(self, source="bundled", session_factory=None):
        if source not in {"bundled", "database"}:
            raise ValueError("MBTI_CATALOG_SOURCE must be bundled or database")
        self.source = source
        self.session_factory = session_factory
        self._lock = Lock()
        self._scorers = {}
        self.refresh_healthy = True

    def catalog(self):
        if self.source == "bundled":
            return mbti_catalog.get_mbti_catalog()
        with self.session_factory() as session:
            session.connection(execution_options={"isolation_level": "REPEATABLE READ", "postgresql_readonly": True})
            return MbtiCatalogRepository(session).load()

    def scorer(self, encoder, model_key, encode_lock):
        # Revision read on every request gives each process an independent refresh.
        with self._lock:
            previous = self._scorers.get(model_key)
            try:
                catalog = self.catalog()
                identity = (catalog.revision, catalog.content_hash)
                if previous and previous[0] == identity:
                    self.refresh_healthy = True
                    return previous[1]
                with encode_lock:
                    scorer = MbtiScorer.from_encoder(catalog, encoder)
                self._scorers[model_key] = (identity, scorer)
                self.refresh_healthy = True
                return scorer
            except Exception:
                self.refresh_healthy = False
                if previous:
                    return previous[1]
                raise


def configured_mbti_provider(session_factory=None):
    source = MbtiCatalogSettings.from_env().source
    if source == "database" and session_factory is None:
        from app.db.session import get_session_factory
        session_factory = get_session_factory()
    return MbtiCatalogProvider(source, session_factory)

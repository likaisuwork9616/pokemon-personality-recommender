"""Transactional SQL catalog; only validated complete snapshots are published."""
import json
from dataclasses import asdict, replace
from datetime import date
from decimal import Decimal

from sqlalchemy import select, delete, func, text
from app.db.models import MbtiProfileRow, MbtiWeightedTermRow, MbtiCatalogState
from app.personality_vocabulary import canonicalize_personality_text
from app.services.mbti_catalog import _catalog_from_payload, get_mbti_catalog


class CatalogConflict(RuntimeError):
    pass


class MbtiCatalogRepository:
    def __init__(self, session):
        self.session = session

    def load(self):
        state = self.session.get(MbtiCatalogState, 1)
        if state is None or state.status != "ready":
            raise RuntimeError("MBTI catalog has not been initialized or published")
        profiles = self.session.scalars(select(MbtiProfileRow).order_by(MbtiProfileRow.code)).all()
        terms = self.session.scalars(select(MbtiWeightedTermRow).order_by(
            MbtiWeightedTermRow.profile_code, MbtiWeightedTermRow.normalized_term)).all()
        by_code = {p.code: [] for p in profiles}
        for term in terms:
            if term.normalized_term != canonicalize_personality_text(term.term):
                raise RuntimeError("MBTI normalized term mismatch")
            if term.profile_code not in by_code:
                raise RuntimeError("MBTI orphan term")
            by_code[term.profile_code].append({"term": term.term, "weight": float(term.weight)})
        rows = []
        for profile in profiles:
            row = {column.name: getattr(profile, column.name) for column in profile.__table__.columns
                   if column.name not in {"created_at", "updated_at"}}
            row["reviewed_at"] = row["reviewed_at"].isoformat()
            row["weighted_terms"] = by_code[profile.code]
            rows.append(row)
        catalog = _catalog_from_payload({"version": state.source_version, "revision": state.revision,
            "reviewed_at": state.reviewed_at.isoformat(), "profiles": rows})
        if catalog.content_hash != state.content_hash:
            raise RuntimeError("MBTI catalog hash mismatch")
        return replace(catalog, source="database")

    def _insert_profile(self, profile):
        row = json.loads(json.dumps(asdict(profile)))
        terms = row.pop("weighted_terms")
        row["reviewed_at"] = date.fromisoformat(row["reviewed_at"])
        self.session.add(MbtiProfileRow(**row))
        self.session.flush()
        for term in terms:
            self.session.add(MbtiWeightedTermRow(profile_code=profile.code, term=term["term"],
                normalized_term=canonicalize_personality_text(term["term"]), weight=Decimal(str(term["weight"]))))

    def initialize(self, catalog=None):
        # Serialize concurrent initializers even before the singleton row exists.
        self.session.execute(text("SELECT pg_advisory_xact_lock(736284901)"))
        for model in (MbtiCatalogState, MbtiProfileRow, MbtiWeightedTermRow):
            if self.session.scalar(select(func.count()).select_from(model)):
                raise CatalogConflict("MBTI tables are not empty; initialization never overwrites data")
        catalog = catalog or get_mbti_catalog()
        for profile in catalog.profiles:
            self._insert_profile(profile)
        self.session.add(MbtiCatalogState(id=1, revision=catalog.revision, source_version=catalog.version,
            reviewed_at=date.fromisoformat(catalog.reviewed_at), content_hash=catalog.content_hash, status="ready"))
        self.session.flush()
        return self.load()

    def update_profile(self, code, profile, expected_revision):
        state = self.session.scalar(select(MbtiCatalogState).where(MbtiCatalogState.id == 1).with_for_update().execution_options(populate_existing=True))
        if state is None or state.status != "ready":
            raise RuntimeError("MBTI catalog is unavailable")
        if state.revision != expected_revision:
            raise CatalogConflict("MBTI catalog changed; reload before saving")
        current = self.load()
        if profile["code"] != code or code not in current.codes:
            raise ValueError("MBTI code cannot be changed")
        rows = [asdict(p) if p.code != code else profile for p in current.profiles]
        # dataclasses produce tuples; normalize to JSON shapes before validation.
        payload = json.loads(json.dumps({"version": current.version, "revision": current.revision + 1,
            "reviewed_at": current.reviewed_at, "profiles": rows}))
        updated = _catalog_from_payload(payload)
        if updated.content_hash == current.content_hash:
            return current
        state.status = "editing"
        self.session.execute(delete(MbtiWeightedTermRow).where(MbtiWeightedTermRow.profile_code == code))
        row = self.session.get(MbtiProfileRow, code)
        values = json.loads(json.dumps(asdict(updated.profile_for(code))))
        terms = values.pop("weighted_terms")
        for field, value in values.items():
            setattr(row, field, date.fromisoformat(value) if field == "reviewed_at" else value)
        for term in terms:
            self.session.add(MbtiWeightedTermRow(profile_code=code, term=term["term"],
                normalized_term=canonicalize_personality_text(term["term"]), weight=Decimal(str(term["weight"]))))
        state.revision = updated.revision
        state.content_hash = updated.content_hash
        state.status = "ready"
        self.session.flush()
        return self.load()

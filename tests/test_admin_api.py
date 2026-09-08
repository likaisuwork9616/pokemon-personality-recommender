from __future__ import annotations

import io
import logging
import unittest
from datetime import datetime, timezone
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError

from app.api.admin import get_admin_personality_repository, get_admin_repository, get_reindex_job_repository, get_reindex_service
from app.main import create_app
from app.personality_vocabulary import canonicalize_personality_text
from app.repositories import AdminPokemonRepository
from app.repositories.personality_admin import AdminPersonalityRepository
from app.repositories.reindex import IndexSourceState, PokemonIndexState
from app.schemas.admin import AdminPokemonCreate, AdminPokemonUpdate
from app.services.admin_auth import AdminAuth, AdminAuthConfig
from app.services.reindex import PokemonReindexSummary


def namespace(**values):
    return SimpleNamespace(**values)


TYPE_NAMES = {
    "fire": ("Fire", "火"),
    "grass": ("Grass", "草"),
    "normal": ("Normal", "一般"),
    "poison": ("Poison", "毒"),
}


def pokemon_from_payload(
    payload: AdminPokemonCreate,
    *,
    identifier: int,
    is_active: bool = True,
):
    def type_link(slot: int, code: str):
        name_en, name_zh = TYPE_NAMES[code]
        return namespace(
            slot=slot,
            type_record=namespace(code=code, name_en=name_en, name_zh=name_zh),
        )

    return namespace(
        id=identifier,
        pokedex_number=payload.pokedex_number,
        form_key=payload.form_key,
        name_zh=payload.name_zh,
        name_en=payload.name_en,
        category_zh=payload.category_zh,
        genus=payload.genus,
        generation=payload.generation,
        habitat=payload.habitat,
        color=payload.color,
        shape=payload.shape,
        growth_rate=payload.growth_rate,
        abilities=payload.abilities,
        hidden_ability=payload.hidden_ability,
        egg_groups=payload.egg_groups,
        height_m=payload.height_m,
        weight_kg=payload.weight_kg,
        capture_rate=payload.capture_rate,
        is_legendary=payload.is_legendary,
        is_mythical=payload.is_mythical,
        is_baby=payload.is_baby,
        is_active=is_active,
        type_links=[
            type_link(slot, code)
            for slot, code in enumerate(payload.type_codes, start=1)
        ],
        stats=(namespace(**payload.stats.model_dump()) if payload.stats else None),
        descriptions=[
            namespace(
                id=identifier * 100 + index,
                language_code=item.language_code,
                description_kind=item.description_kind,
                source_key=item.source_key,
                content=item.content,
                content_hash=sha256(item.content.encode("utf-8")).hexdigest(),
                is_primary=item.is_primary,
            )
            for index, item in enumerate(payload.descriptions, start=1)
        ],
        images=[
            namespace(
                id=identifier * 10 + index,
                image_kind=item.image_kind,
                image_url=str(item.image_url),
                is_primary=item.is_primary,
            )
            for index, item in enumerate(payload.images, start=1)
        ],
    )


class FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeAdminRepository:
    def __init__(self) -> None:
        self.session = FakeSession()
        payload = AdminPokemonCreate(
            pokedex_number=1,
            name_zh="妙蛙種子",
            name_en="Bulbasaur",
            generation=1,
            type_codes=["grass", "poison"],
            abilities="Overgrow",
            egg_groups="Monster, Grass",
            descriptions=[
                {
                    "language_code": "mul",
                    "description_kind": "analysis",
                    "source_key": "admin:analysis",
                    "content": "沉著而重視夥伴。",
                    "is_primary": True,
                }
            ],
        )
        self.items = {1: pokemon_from_payload(payload, identifier=1)}
        self.raise_conflict = False

    def list_all(self, *, q=None, page=1, page_size=20):
        items = sorted(
            self.items.values(),
            key=lambda item: (item.pokedex_number, item.form_key, item.id),
        )
        if q:
            query = q.casefold()
            items = [
                item
                for item in items
                if query in item.name_zh.casefold() or query in item.name_en.casefold()
            ]
        total = len(items)
        start = (page - 1) * page_size
        return items[start : start + page_size], total

    def get(self, pokemon_id):
        return self.items.get(pokemon_id)

    def create(self, payload):
        if self.raise_conflict:
            raise IntegrityError("duplicate", {}, None)
        identifier = max(self.items) + 1
        pokemon = pokemon_from_payload(payload, identifier=identifier)
        self.items[identifier] = pokemon
        return pokemon

    def update(self, pokemon, payload: AdminPokemonUpdate):
        for field in payload.model_fields_set:
            value = getattr(payload, field)
            if field == "type_codes":
                replacement = AdminPokemonCreate(
                    pokedex_number=pokemon.pokedex_number,
                    form_key=pokemon.form_key,
                    name_zh=pokemon.name_zh,
                    name_en=pokemon.name_en,
                    generation=pokemon.generation,
                    type_codes=value,
                )
                pokemon.type_links = pokemon_from_payload(
                    replacement,
                    identifier=pokemon.id,
                ).type_links
            elif field == "descriptions":
                pokemon.descriptions = pokemon_from_payload(
                    AdminPokemonCreate(
                        pokedex_number=pokemon.pokedex_number,
                        form_key=pokemon.form_key,
                        name_zh=pokemon.name_zh,
                        name_en=pokemon.name_en,
                        generation=pokemon.generation,
                        type_codes=[link.type_record.code for link in pokemon.type_links],
                        descriptions=value or [],
                    ),
                    identifier=pokemon.id,
                ).descriptions
            elif field == "images":
                pokemon.images = pokemon_from_payload(
                    AdminPokemonCreate(
                        pokedex_number=pokemon.pokedex_number,
                        form_key=pokemon.form_key,
                        name_zh=pokemon.name_zh,
                        name_en=pokemon.name_en,
                        generation=pokemon.generation,
                        type_codes=[link.type_record.code for link in pokemon.type_links],
                        images=value or [],
                    ),
                    identifier=pokemon.id,
                ).images
            elif field == "stats":
                pokemon.stats = namespace(**value.model_dump()) if value else None
            else:
                setattr(pokemon, field, value)
        return pokemon

    @staticmethod
    def set_active(pokemon, active):
        pokemon.is_active = active
        return pokemon


class FakeReindexService:
    def __init__(self) -> None:
        self.repository = namespace(session=FakeSession())
        self.calls = 0

    @staticmethod
    def _state(status="stale"):
        return PokemonIndexState(
            pokemon_id=1,
            status=status,
            sources=(
                IndexSourceState(
                    source_key="analysis_text",
                    status=status,
                    current_document_id=None,
                    current_version=None,
                    staged_document_id=None,
                    staged_version=2,
                    total_chunks=1,
                    ready_chunks=1 if status == "ready" else 0,
                    last_error=None,
                ),
            ),
        )

    def status(self, _pokemon_id):
        return self._state()

    def rebuild(self, _pokemon_id):
        self.calls += 1
        return PokemonReindexSummary(
            pokemon_id=1,
            embedding_model_id=7,
            discovered=1,
            embedded=1,
            failed=0,
            index=self._state("ready"),
        )


class FakeReindexJobRepository:
    def __init__(self) -> None:
        self.session = FakeSession()
        self.jobs = {}

    def enqueue(self, pokemon_id):
        if pokemon_id != 1:
            raise LookupError(pokemon_id)
        existing = next((job for job in self.jobs.values() if job.pokemon_id == pokemon_id and job.status in {"queued", "running"}), None)
        if existing:
            return existing, False
        job = namespace(
            id=uuid4(), pokemon_id=pokemon_id, status="queued",
            progress_current=0, progress_total=0, embedded=0, failed=0,
            message="等待 worker 處理", last_error=None,
            queued_at=datetime.now(timezone.utc), started_at=None, finished_at=None,
        )
        self.jobs[job.id] = job
        return job, True

    def get(self, job_id):
        return self.jobs.get(job_id)


class FakePersonalityRepository:
    def __init__(self) -> None:
        self.session = FakeSession()
        self.trait = namespace(
            code="loyal_guardian", name_zh="忠誠守護者", vector_index=10, is_active=True,
            synonyms=[namespace(term="承諾", language_code="zh-Hant", weight=2.0, is_active=True)],
        )
        self.current_revision = 1

    def list_traits(self):
        return [self.trait]

    def catalog(self):
        return namespace(
            trait_names=tuple(f"特質{index}" for index in range(16)),
            synonyms_by_trait={f"特質{index}": (f"詞{index}",) for index in range(16)},
        )

    def revision(self):
        return self.current_revision

    def bump_revision(self):
        self.current_revision += 1
        return self.current_revision

    def get_trait(self, code):
        return self.trait if code == self.trait.code else None

    def rename_trait(self, trait, name_zh):
        display, normalized = AdminPersonalityRepository.normalize_trait_name(name_zh)
        if canonicalize_personality_text(trait.name_zh) == normalized:
            return False
        trait.name_zh = display
        return True

    def add_synonym(self, trait, **values):
        display, normalized = AdminPersonalityRepository.normalize_term(values["term"])
        item = namespace(**{**values, "term": display, "normalized_term": normalized})
        trait.synonyms.append(item)
        return item

    def get_synonym(self, trait_code, term):
        if trait_code != self.trait.code:
            return None
        normalized = canonicalize_personality_text(term)
        return next(
            (
                item
                for item in self.trait.synonyms
                if canonicalize_personality_text(item.term) == normalized
            ),
            None,
        )

    def update_synonym(self, item, **values):
        changed = False
        for key, value in values.items():
            if key == "term":
                display, normalized = AdminPersonalityRepository.normalize_term(value)
                if normalized == canonicalize_personality_text(item.term):
                    continue
                item.term = display
                item.normalized_term = normalized
                changed = True
            elif getattr(item, key) != value:
                setattr(item, key, value)
                changed = True
        return changed

class RefreshingEngine:
    def __init__(self) -> None:
        self.refresh_calls = 0
        self.personality_refresh_calls = 0
        self.personality_refresh_healthy = True
        self.personality_refresh_failure_message: str | None = None

    def refresh_profiles(self):
        self.refresh_calls += 1

    def refresh_personality_catalog(self, _catalog, *, revision=None):
        self.personality_refresh_calls += 1
        if self.personality_refresh_failure_message is not None:
            self.personality_refresh_healthy = False
            raise RuntimeError(self.personality_refresh_failure_message)
        self.personality_refresh_healthy = True


class AdminApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeAdminRepository()
        self.reindex_service = FakeReindexService()
        self.reindex_jobs = FakeReindexJobRepository()
        self.personality_repository = FakePersonalityRepository()
        self.runtime_engine = RefreshingEngine()
        self.auth = AdminAuth(
            AdminAuthConfig(
                password="portfolio-admin-password",
                session_secret="s" * 32,
                session_ttl_seconds=600,
            ),
            clock=lambda: 1_700_000_000,
        )
        self.application = create_app(
            lambda: self.runtime_engine,
            admin_auth=self.auth,
        )
        self.application.dependency_overrides[get_admin_repository] = (
            lambda: self.repository
        )
        self.application.dependency_overrides[get_reindex_service] = (
            lambda: self.reindex_service
        )
        self.application.dependency_overrides[get_reindex_job_repository] = (
            lambda: self.reindex_jobs
        )
        self.application.dependency_overrides[get_admin_personality_repository] = (
            lambda: self.personality_repository
        )
        self.context = TestClient(self.application)
        self.client = self.context.__enter__()

    def tearDown(self) -> None:
        self.context.__exit__(None, None, None)

    def login(self) -> tuple[str, str]:
        response = self.client.post(
            "/api/v1/admin/session",
            json={"password": "portfolio-admin-password"},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["csrf_token"], response.headers["set-cookie"]

    def test_authentication_cookie_and_generic_login_failure(self):
        self.assertEqual(
            self.client.get("/api/v1/admin/pokemon").status_code,
            401,
        )

        failed = self.client.post(
            "/api/v1/admin/session",
            json={"password": "wrong-password-do-not-echo"},
        )
        self.assertEqual(failed.status_code, 401)
        self.assertNotIn("wrong-password-do-not-echo", failed.text)

        _csrf, set_cookie = self.login()
        normalized = set_cookie.casefold()
        self.assertIn("httponly", normalized)
        self.assertIn("samesite=strict", normalized)
        self.assertNotIn("portfolio-admin-password", set_cookie)
        self.assertEqual(
            self.client.get("/api/v1/admin/session").json()["authenticated"],
            True,
        )

    def test_crud_deactivate_restore_and_csrf(self):
        csrf, _set_cookie = self.login()

        denied = self.client.post(
            "/api/v1/admin/pokemon/1/deactivate",
        )
        self.assertEqual(denied.status_code, 403)
        denied = self.client.post(
            "/api/v1/admin/pokemon/1/deactivate",
            headers={"X-CSRF-Token": "wrong"},
        )
        self.assertEqual(denied.status_code, 403)

        headers = {"X-CSRF-Token": csrf}
        created = self.client.post(
            "/api/v1/admin/pokemon",
            headers=headers,
            json={
                "pokedex_number": 4,
                "name_zh": "小火龍",
                "name_en": "Charmander",
                "generation": 1,
                "type_codes": ["fire"],
                "descriptions": [
                    {
                        "language_code": "mul",
                        "description_kind": "analysis",
                        "source_key": "admin:analysis",
                        "content": "充滿熱情，也願意保護朋友。",
                        "is_primary": True,
                    }
                ],
            },
        )
        self.assertEqual(created.status_code, 201)
        pokemon_id = created.json()["id"]
        self.assertEqual(created.json()["types"][0]["code"], "fire")
        self.assertEqual(
            created.json()["descriptions"][0]["description_kind"],
            "analysis",
        )

        updated = self.client.patch(
            f"/api/v1/admin/pokemon/{pokemon_id}",
            headers=headers,
            json={"name_zh": "小火龍（更新）"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json()["name_zh"], "小火龍（更新）")

        inactive = self.client.post(
            f"/api/v1/admin/pokemon/{pokemon_id}/deactivate",
            headers=headers,
        )
        self.assertFalse(inactive.json()["is_active"])
        listing = self.client.get("/api/v1/admin/pokemon").json()
        self.assertIn(pokemon_id, [item["id"] for item in listing["items"]])

        restored = self.client.post(
            f"/api/v1/admin/pokemon/{pokemon_id}/restore",
            headers=headers,
        )
        self.assertTrue(restored.json()["is_active"])
        self.assertEqual(self.repository.session.commits, 4)
        self.assertEqual(self.runtime_engine.refresh_calls, 4)

    def test_database_conflict_rolls_back_and_returns_409(self):
        csrf, _set_cookie = self.login()
        self.repository.raise_conflict = True

        response = self.client.post(
            "/api/v1/admin/pokemon",
            headers={"X-CSRF-Token": csrf},
            json={
                "pokedex_number": 1,
                "name_zh": "重複",
                "name_en": "Duplicate",
                "generation": 1,
                "type_codes": ["normal"],
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["code"], "pokemon_conflict")
        self.assertEqual(self.repository.session.rollbacks, 1)

    def test_logout_requires_csrf_and_clears_session(self):
        csrf, _set_cookie = self.login()

        response = self.client.delete(
            "/api/v1/admin/session",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            self.client.get("/api/v1/admin/session").status_code,
            401,
        )

    def test_index_status_and_rebuild_require_the_expected_auth_guards(self):
        csrf, _set_cookie = self.login()

        status_response = self.client.get(
            "/api/v1/admin/pokemon/1/index-status"
        )
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.json()["status"], "stale")
        self.assertEqual(
            status_response.json()["sources"][0]["source_key"],
            "analysis_text",
        )

        denied = self.client.post("/api/v1/admin/pokemon/1/reindex")
        self.assertEqual(denied.status_code, 403)
        rebuilt = self.client.post(
            "/api/v1/admin/pokemon/1/reindex",
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(rebuilt.status_code, 202)
        self.assertEqual(rebuilt.json()["status"], "queued")
        self.assertEqual(rebuilt.json()["progress_current"], 0)
        self.assertEqual(self.reindex_jobs.session.commits, 1)

        job_id = rebuilt.json()["id"]
        polled = self.client.get(f"/api/v1/admin/reindex-jobs/{job_id}")
        self.assertEqual(polled.status_code, 200)
        self.assertEqual(polled.json()["status"], "queued")

        job = self.reindex_jobs.get(next(iter(self.reindex_jobs.jobs)))
        job.status = "succeeded"
        job.progress_current = job.progress_total = job.embedded = 1
        completed = self.client.get(f"/api/v1/admin/reindex-jobs/{job_id}")
        self.assertEqual(completed.json()["index"]["status"], "stale")
        self.assertEqual(self.runtime_engine.refresh_calls, 1)

    def test_admin_page_and_openapi_are_exposed(self):
        page = self.client.get("/admin")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="admin-login-form"', page.text)
        self.assertIn('id="vocabulary-synonym-form"', page.text)
        self.assertIn('/static/js/admin.js', page.text)

        paths = self.application.openapi()["paths"]
        self.assertIn("/api/v1/admin/session", paths)
        self.assertIn("/api/v1/admin/pokemon/{pokemon_id}", paths)
        self.assertIn("/api/v1/admin/pokemon/{pokemon_id}/reindex", paths)
        self.assertIn("/api/v1/admin/reindex-jobs/{job_id}", paths)
        self.assertIn("/api/v1/admin/personality/traits", paths)

    def test_personality_vocabulary_crud_is_authenticated_and_csrf_protected(self):
        self.assertEqual(self.client.get("/api/v1/admin/personality/traits").status_code, 401)
        csrf, _set_cookie = self.login()
        headers = {"X-CSRF-Token": csrf}

        listing = self.client.get("/api/v1/admin/personality/traits")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()[0]["synonyms"][0]["term"], "承諾")

        denied = self.client.post(
            "/api/v1/admin/personality/traits/loyal_guardian/synonyms",
            json={"term": "守約"},
        )
        self.assertEqual(denied.status_code, 403)
        created = self.client.post(
            "/api/v1/admin/personality/traits/loyal_guardian/synonyms",
            headers=headers,
            json={"term": "守約", "language_code": "zh-Hant", "weight": 2.5},
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["weight"], 2.5)

        updated = self.client.patch(
            "/api/v1/admin/personality/traits/loyal_guardian/synonyms",
            headers=headers,
            json={"original_term": "守約", "weight": 3.0, "is_active": False},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertFalse(updated.json()["is_active"])

        slash = self.client.post(
            "/api/v1/admin/personality/traits/loyal_guardian/synonyms",
            headers=headers,
            json={"term": "care/share", "language_code": "en", "weight": 1.5},
        )
        self.assertEqual(slash.status_code, 201)
        slash_updated = self.client.patch(
            "/api/v1/admin/personality/traits/loyal_guardian/synonyms",
            headers=headers,
            json={"original_term": "care/share", "weight": 2.0},
        )
        self.assertEqual(slash_updated.status_code, 200)
        self.assertEqual(slash_updated.json()["term"], "care/share")

        null_update = self.client.patch(
            "/api/v1/admin/personality/traits/loyal_guardian/synonyms",
            headers=headers,
            json={"original_term": "care/share", "weight": None},
        )
        self.assertEqual(null_update.status_code, 422)
        self.assertEqual(self.personality_repository.session.commits, 4)
        self.assertEqual(self.runtime_engine.personality_refresh_calls, 4)

    def test_normalized_vocabulary_noops_skip_transaction_and_refresh(self):
        self.personality_repository.trait.name_zh = "Guardian"
        self.personality_repository.trait.synonyms.append(
            namespace(
                term="Reliable",
                normalized_term="reliable",
                language_code="en",
                weight=2.0,
                is_active=True,
            )
        )
        csrf, _set_cookie = self.login()
        headers = {"X-CSRF-Token": csrf}

        trait_noop = self.client.patch(
            "/api/v1/admin/personality/traits/loyal_guardian",
            headers=headers,
            json={"name_zh": "ＧＵＡＲＤＩＡＮ"},
        )
        synonym_noop = self.client.patch(
            "/api/v1/admin/personality/traits/loyal_guardian/synonyms",
            headers=headers,
            json={"original_term": "ＲＥＬＩＡＢＬＥ", "term": "reliable"},
        )

        self.assertEqual(trait_noop.status_code, 200)
        self.assertEqual(trait_noop.json()["name_zh"], "Guardian")
        self.assertEqual(trait_noop.headers["x-personality-refresh-status"], "ready")
        self.assertEqual(synonym_noop.status_code, 200)
        self.assertEqual(synonym_noop.json()["term"], "Reliable")
        self.assertEqual(synonym_noop.headers["x-personality-refresh-status"], "ready")
        self.assertEqual(self.personality_repository.session.commits, 0)
        self.assertEqual(self.personality_repository.current_revision, 1)
        self.assertEqual(self.runtime_engine.personality_refresh_calls, 0)

        control_character = self.client.post(
            "/api/v1/admin/personality/traits/loyal_guardian/synonyms",
            headers=headers,
            json={"term": "守\u200b護"},
        )
        expanded_too_long = self.client.post(
            "/api/v1/admin/personality/traits/loyal_guardian/synonyms",
            headers=headers,
            json={"term": "ß" * 80},
        )
        self.assertEqual(control_character.status_code, 422)
        self.assertEqual(expanded_too_long.status_code, 422)
        self.assertEqual(self.personality_repository.session.commits, 0)
        self.assertEqual(self.runtime_engine.personality_refresh_calls, 0)

    def test_committed_personality_refresh_failure_is_pending_and_observable(self):
        csrf, _set_cookie = self.login()
        headers = {"X-CSRF-Token": csrf}
        private_marker = "PRIVATE-PERSONALITY-REFRESH-DETAIL"
        self.runtime_engine.personality_refresh_failure_message = private_marker
        stream = io.StringIO()
        logger = logging.getLogger("pokemon.admin")
        handler = logging.StreamHandler(stream)
        previous_level = logger.level
        logger.setLevel(logging.WARNING)
        logger.addHandler(handler)
        try:
            pending = self.client.post(
                "/api/v1/admin/personality/traits/loyal_guardian/synonyms",
                headers=headers,
                json={"term": "暫存詞", "language_code": "zh-Hant", "weight": 2.0},
            )
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)

        self.assertEqual(pending.status_code, 202)
        self.assertEqual(
            pending.headers["x-personality-refresh-status"],
            "pending",
        )
        self.assertEqual(self.personality_repository.session.commits, 1)
        self.assertEqual(self.personality_repository.session.rollbacks, 0)
        self.assertEqual(self.personality_repository.current_revision, 2)
        self.assertIsNotNone(
            self.personality_repository.get_synonym("loyal_guardian", "暫存詞")
        )

        degraded = self.client.get("/health/ready")
        degraded_metrics = self.client.get("/metrics").text
        log_output = stream.getvalue()
        self.assertEqual(degraded.status_code, 503)
        self.assertEqual(degraded.json()["reason"], "personality_refresh_pending")
        self.assertIn("personality_refresh_failed", log_output)
        self.assertIn("RuntimeError", log_output)
        self.assertNotIn(private_marker, log_output)
        self.assertIn("pokemon_personality_refresh_failures_total 1", degraded_metrics)
        self.assertIn("pokemon_personality_refresh_healthy 0", degraded_metrics)

        self.runtime_engine.personality_refresh_failure_message = None
        recovered = self.client.patch(
            "/api/v1/admin/personality/traits/loyal_guardian/synonyms",
            headers=headers,
            json={"original_term": "暫存詞", "weight": 2.5},
        )

        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(
            recovered.headers["x-personality-refresh-status"],
            "ready",
        )
        self.assertEqual(self.client.get("/health/ready").json(), {"status": "ready"})
        recovered_metrics = self.client.get("/metrics").text
        self.assertIn("pokemon_personality_refresh_failures_total 1", recovered_metrics)
        self.assertIn("pokemon_personality_refresh_healthy 1", recovered_metrics)


class AdminSchemaTests(unittest.TestCase):
    def test_update_rejects_empty_null_required_and_duplicate_children(self):
        invalid_payloads = (
            {},
            {"name_zh": None},
            {"type_codes": ["fire", "FIRE"]},
            {
                "images": [
                    {
                        "image_kind": "artwork",
                        "image_url": "https://example.test/one.png",
                        "is_primary": True,
                    },
                    {
                        "image_kind": "sprite",
                        "image_url": "https://example.test/two.png",
                        "is_primary": True,
                    },
                ]
            },
        )

        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                AdminPokemonUpdate.model_validate(payload)


class _Rows:
    def __iter__(self):
        return iter(())


class _RecordingSession:
    def __init__(self) -> None:
        self.statements = []

    def scalar(self, statement):
        self.statements.append(statement)
        return 0

    def scalars(self, statement):
        self.statements.append(statement)
        return _Rows()


class AdminRepositorySqlTests(unittest.TestCase):
    def test_admin_list_includes_inactive_and_has_stable_order(self):
        session = _RecordingSession()
        repository = AdminPokemonRepository(session)

        items, total = repository.list_all(
            q="100%_hero",
            page=2,
            page_size=25,
        )

        self.assertEqual((items, total), ([], 0))
        sql = "\n".join(
            str(statement.compile(dialect=postgresql.dialect()))
            for statement in session.statements
        )
        self.assertNotIn("WHERE pokemon.is_active", sql)
        self.assertNotIn("AND pokemon.is_active", sql)
        self.assertIn("ORDER BY pokemon.pokedex_number, pokemon.form_key, pokemon.id", sql)
        self.assertIn("ESCAPE", sql)


if __name__ == "__main__":
    unittest.main()

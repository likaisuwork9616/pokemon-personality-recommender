from __future__ import annotations

import copy
import json
import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from uuid import uuid4
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text, select, update, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.db.models import MbtiProfileRow, MbtiWeightedTermRow, MbtiCatalogState, AdminAuditLog
from app.repositories.mbti_catalog import MbtiCatalogRepository, CatalogConflict
from app.services.mbti_catalog import get_mbti_catalog, _catalog_from_payload
from app.services.mbti_provider import MbtiCatalogProvider
from app.services.mbti_scoring import MbtiScorer
from app.main import create_app
from app.api.deps import get_session
from app.services.admin_auth import AdminAuth, AdminAuthConfig, AdminAccount


class Encoder:
    def __init__(self):
        self.fail = False
        self.calls = 0

    def encode(self, values, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("encoder unavailable")
        return np.eye(1,384)[0] if isinstance(values,str) else np.tile(np.eye(1, 384)[0], (len(values), 1))


class CanonicalCatalogTests(unittest.TestCase):
    def test_hash_ignores_storage_order_numeric_representation_and_revision(self):
        catalog = get_mbti_catalog()
        payload = {"version": catalog.version, "revision": catalog.revision + 1,
            "reviewed_at": catalog.reviewed_at, "profiles": [asdict(p) for p in catalog.profiles]}
        payload = json.loads(json.dumps(payload))
        for profile in payload["profiles"]:
            profile["weighted_terms"].reverse()
            for term in profile["weighted_terms"]:
                if term["weight"].is_integer():
                    term["weight"] = int(term["weight"])
        self.assertEqual(_catalog_from_payload(payload).content_hash, catalog.content_hash)


@unittest.skipUnless(os.getenv("TEST_DATABASE_URL"), "Requires disposable PostgreSQL TEST_DATABASE_URL")
class MbtiDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.admin = create_engine(os.environ["TEST_DATABASE_URL"])
        self.schema = "test_mbti_" + uuid4().hex
        with self.admin.begin() as c:
            c.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        self.engine = create_engine(os.environ["TEST_DATABASE_URL"],
            connect_args={"options": f"-csearch_path={self.schema},public"})
        Base.metadata.create_all(self.engine, checkfirst=False)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False, autoflush=False)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.engine.dispose()
        with self.admin.begin() as c:
            c.execute(text(f'DROP SCHEMA "{self.schema}" CASCADE'))
        self.admin.dispose()

    def initialize(self):
        with self.sessions.begin() as s:
            return MbtiCatalogRepository(s).initialize()

    def changed(self, catalog, suffix="新增的合作行為描述。"):
        row = json.loads(json.dumps(asdict(catalog.profiles[0])))
        row["summary"] += suffix
        return row

    def test_initialize_roundtrip_rejects_second_run_and_never_overwrites(self):
        original = get_mbti_catalog()
        catalog = self.initialize()
        self.assertEqual(catalog.content_hash, original.content_hash)
        self.assertEqual(catalog.source, "database")
        self.assertEqual(len(catalog.profiles), 16)
        self.assertEqual(sum(len(p.weighted_terms) for p in catalog.profiles), 256)
        with self.assertRaises(CatalogConflict), self.sessions.begin() as s:
            MbtiCatalogRepository(s).initialize()
        with self.sessions.begin() as s:
            updated = MbtiCatalogRepository(s).update_profile(catalog.codes[0], self.changed(catalog), 1)
        self.assertEqual(updated.revision, 2)
        self.assertNotEqual(updated.content_hash, catalog.content_hash)
        self.assertEqual(MbtiCatalogProvider("database", self.sessions).catalog(), updated)
        with self.assertRaises(CatalogConflict), self.sessions.begin() as s:
            MbtiCatalogRepository(s).initialize()
        with self.sessions.begin() as s:
            unchanged = MbtiCatalogRepository(s).update_profile(updated.codes[0], asdict(updated.profiles[0]), 2)
        self.assertEqual(unchanged.revision, 2)

    def test_invalid_edit_rollback_and_optimistic_revision(self):
        catalog = self.initialize()
        invalid = self.changed(catalog)
        invalid["weighted_terms"][1] = invalid["weighted_terms"][0]
        with self.assertRaises(RuntimeError), self.sessions.begin() as s:
            MbtiCatalogRepository(s).update_profile(catalog.codes[0], invalid, 1)
        self.assertEqual(MbtiCatalogProvider("database", self.sessions).catalog(), catalog)
        with self.sessions.begin() as s:
            MbtiCatalogRepository(s).update_profile(catalog.codes[0], self.changed(catalog), 1)
        with self.assertRaises(CatalogConflict), self.sessions.begin() as s:
            MbtiCatalogRepository(s).update_profile(catalog.codes[0], self.changed(catalog, "第二位編輯者。"), 1)

    def test_stale_session_identity_map_cannot_overwrite_another_editor(self):
        catalog = self.initialize()
        with self.sessions() as stale:
            repo = MbtiCatalogRepository(stale)
            cached_state = stale.get(MbtiCatalogState,1)
            previous = repo.load()
            with self.sessions.begin() as fresh:
                MbtiCatalogRepository(fresh).update_profile(catalog.codes[0],self.changed(catalog),1)
            with self.assertRaises(CatalogConflict):
                repo.update_profile(catalog.codes[0],self.changed(previous,"另一位編輯者。"),1)
            self.assertEqual(cached_state.revision,2)
            stale.rollback()

    def test_constraints_reject_null_blank_invalid_codes_weights_duplicates_and_orphans(self):
        self.initialize()
        statements = [
            "UPDATE mbti_profiles SET summary=NULL WHERE code='ENFJ'",
            "UPDATE mbti_profiles SET summary=' ' WHERE code='ENFJ'",
            "UPDATE mbti_profiles SET code='XXXX' WHERE code='ENFJ'",
            "UPDATE mbti_profiles SET strengths='[]'::jsonb WHERE code='ENFJ'",
            "UPDATE mbti_catalog_state SET revision=0",
            "UPDATE mbti_catalog_state SET content_hash='invalid'",
            "UPDATE mbti_catalog_state SET status='invalid'",
            "UPDATE mbti_weighted_terms SET normalized_term='same' WHERE profile_code='ENFJ'",
            "UPDATE mbti_weighted_terms SET profile_code='XXXX'",
            "UPDATE mbti_weighted_terms SET weight=NULL",
        ]
        statements += [f"UPDATE mbti_weighted_terms SET weight='{value}'::numeric" for value in
            ("NaN", "Infinity", "-Infinity", "0", "5.1", "-1")]
        for statement in statements:
            with self.subTest(statement=statement), self.assertRaises(IntegrityError):
                with self.engine.begin() as c:
                    c.execute(text(statement))

    def test_corrupt_hash_normalization_and_missing_types_are_not_published(self):
        self.initialize()
        for statement in (
            "UPDATE mbti_catalog_state SET content_hash=repeat('0',64)",
            "UPDATE mbti_weighted_terms SET normalized_term='wrong' WHERE id=(SELECT min(id) FROM mbti_weighted_terms)",
            "DELETE FROM mbti_profiles WHERE code='ENFJ'",
            "UPDATE mbti_profiles SET source_urls='[\"http://unsafe.example\"]'::jsonb WHERE code='ENFJ'",
        ):
            with self.sessions() as s:
                s.execute(text(statement))
                with self.assertRaises(RuntimeError):
                    MbtiCatalogRepository(s).load()
                s.rollback()

    def test_readonly_two_workers_refresh_and_failed_encoding_keeps_complete_snapshot(self):
        original = self.initialize()
        workers = [MbtiCatalogProvider("database", self.sessions) for _ in range(2)]
        encoders = [Encoder(), Encoder()]
        key = (7, "encoder", "v1", 384, True)
        old = [p.scorer(e, key, threading.Lock()) for p,e in zip(workers,encoders)]
        # Readers see the previous published version during an uncommitted edit.
        with self.sessions() as writing:
            updated = MbtiCatalogRepository(writing).update_profile(original.codes[0], self.changed(original), 1)
            with ThreadPoolExecutor(1) as executor:
                self.assertEqual(executor.submit(workers[0].catalog).result(timeout=5).revision, 1)
            writing.commit()
        encoders[0].fail = True
        self.assertIs(workers[0].scorer(encoders[0], key, threading.Lock()), old[0])
        self.assertFalse(workers[0].refresh_healthy)
        self.assertEqual(workers[1].scorer(encoders[1], key, threading.Lock()).catalog.revision, 2)
        encoders[0].fail = False
        self.assertEqual(workers[0].scorer(encoders[0], key, threading.Lock()).catalog.revision, 2)
        self.assertEqual(old[0].catalog.revision, 1)
        before = encoders[0].calls
        workers[0].scorer(encoders[0], (8, "encoder", "v2", 384, True), threading.Lock())
        self.assertGreater(encoders[0].calls, before)
        statements = []
        def record(conn, cursor, statement, *args): statements.append(statement)
        event.listen(self.engine, "before_cursor_execute", record)
        workers[0].catalog()
        self.assertFalse(any(s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for s in statements))

    def test_database_and_bundled_scores_match(self):
        database = self.initialize()
        encoder = Encoder()
        scorers = [MbtiScorer.from_encoder(c, encoder) for c in (get_mbti_catalog(), database)]
        for query in ("合作與分享", "安靜觀察", "I guide my friends"):
            vectors = [s.affinity(query, np.eye(1,384)[0]) for s in scorers]
            np.testing.assert_allclose(*vectors)
            self.assertEqual(scorers[0].score_components(.5,vectors[0],vectors[0],mbti="INFP"),
                             scorers[1].score_components(.5,vectors[1],vectors[1],mbti="INFP"))

    def test_inflight_recommendation_keeps_the_captured_catalog_during_edit(self):
        from tests.test_recommendation_service import HybridRecommendationEngineTests, _candidate
        catalog = self.initialize()
        engine, _, _, retriever, _ = HybridRecommendationEngineTests()._engine([
            _candidate(1,.03), _candidate(2,.02), _candidate(3,.01)])
        engine.profile_engine.st_model = Encoder()
        engine.mbti_provider = MbtiCatalogProvider("database",self.sessions)
        entered, release = threading.Event(), threading.Event()
        original_retrieve = retriever.retrieve
        def paused(**kwargs):
            entered.set()
            if not release.wait(5): raise RuntimeError("test timed out")
            return original_retrieve(**kwargs)
        retriever.retrieve = paused
        with ThreadPoolExecutor(1) as executor:
            inflight = executor.submit(engine.recommend,"合作與分享",mbti="ENFJ")
            self.assertTrue(entered.wait(5))
            try:
                with self.sessions.begin() as s:
                    updated = MbtiCatalogRepository(s).update_profile("ENFJ", self.changed(catalog),1)
            finally:
                release.set()
            results = inflight.result(timeout=5)
        self.assertTrue(all(row["mbti_profile"]["summary"] == catalog.profile_for("ENFJ").summary for row in results))
        next_results = engine.recommend("合作與分享",mbti="ENFJ")
        self.assertTrue(all(row["mbti_profile"]["summary"] == updated.profile_for("ENFJ").summary for row in next_results))

    def test_new_migration_downgrade_and_upgrade_preserve_legacy_tables(self):
        from alembic import command
        from alembic.config import Config
        with self.engine.begin() as c:
            for table in ("mbti_catalog_state", "mbti_weighted_terms", "mbti_profiles"):
                c.execute(text(f"DROP TABLE {table}"))
            c.execute(text("CREATE TABLE alembic_version (version_num varchar(32) PRIMARY KEY)"))
            c.execute(text("INSERT INTO alembic_version VALUES ('20260929_0010')"))
            c.execute(text("INSERT INTO personality_traits (code,name_zh,vector_index) VALUES ('sentinel','保留舊資料',0)"))
        url = self.engine.url.update_query_dict({"options":f"-csearch_path={self.schema},public"}).render_as_string(hide_password=False)
        config = Config("alembic.ini")
        config.get_main_option("script_location")
        config.config_file_name = None  # Keep the test process logging configuration.
        with patch.dict(os.environ,{"DATABASE_URL":url}):
            command.upgrade(config,"head")
            self.assertEqual(len(self.initialize().profiles),16)
            command.downgrade(config,"20260929_0010")
            with self.engine.connect() as c:
                self.assertEqual(c.execute(text("SELECT name_zh FROM personality_traits WHERE code='sentinel'")).scalar(),"保留舊資料")
                self.assertEqual(c.execute(text("SELECT count(*) FROM information_schema.tables WHERE table_schema=:schema AND table_name LIKE 'mbti_%'"),{"schema":self.schema}).scalar(),0)
            command.upgrade(config,"head")
            self.assertEqual(len(self.initialize().profiles),16)

    def test_concurrent_initializers_publish_only_one_catalog(self):
        def initialize_once():
            try:
                with self.sessions.begin() as s:
                    MbtiCatalogRepository(s).initialize()
                return "initialized"
            except CatalogConflict:
                return "conflict"
        with ThreadPoolExecutor(2) as executor:
            results=list(executor.map(lambda _:initialize_once(),range(2)))
        self.assertCountEqual(results,["initialized","conflict"])
        self.assertEqual(len(MbtiCatalogProvider("database",self.sessions).catalog().profiles),16)

    def test_failed_initialization_rolls_back_all_rows(self):
        with self.sessions() as s:
            repo = MbtiCatalogRepository(s)
            original = repo._insert_profile
            calls = []
            def failing(profile):
                original(profile)
                calls.append(profile.code)
                if len(calls) == 2: raise RuntimeError("deliberate failure")
            with self.assertRaises(RuntimeError), s.begin(), patch.object(repo,"_insert_profile",failing):
                repo.initialize()
        with self.engine.connect() as c:
            for table in ("mbti_profiles","mbti_weighted_terms","mbti_catalog_state"):
                self.assertEqual(c.execute(text(f"SELECT count(*) FROM {table}")).scalar(),0)
        self.assertEqual(len(self.initialize().profiles),16)

    def test_admin_auth_csrf_origin_validation_conflict_and_etag(self):
        catalog = self.initialize()
        auth = AdminAuth(AdminAuthConfig(password="test-admin-password", session_secret="s"*32,
            accounts=(AdminAccount("viewer", "viewer-password", "viewer"),)))
        app = create_app(lambda: object(), admin_auth=auth,
            mbti_provider=MbtiCatalogProvider("database", self.sessions))
        def session_dep():
            with self.sessions() as s: yield s
        app.dependency_overrides[get_session] = session_dep
        with TestClient(app) as client:
            url = "/api/v1/admin/mbti/profiles/ENFJ"
            payload = {"expected_revision":1,"profile":self.changed(catalog)}
            self.assertEqual(client.put(url,json=payload).status_code,401)
            login = client.post("/api/v1/admin/session", json={"username":"admin","password":"test-admin-password"})
            csrf = login.json()["csrf_token"]
            self.assertEqual(client.put(url,json=payload).status_code,403)
            headers = {"X-CSRF-Token":csrf,"Origin":"http://testserver"}
            for origin in ("http://other.example", "null", "", "http://testserver/path"):
                self.assertEqual(client.put(url,json=payload,headers={**headers,"Origin":origin}).status_code,403)
            original_etag = client.get("/api/v1/personality/traits").headers["etag"]
            invalid = copy.deepcopy(payload)
            invalid["profile"]["source_urls"] = ["http://unsafe.example"]
            self.assertEqual(client.put(url,json=invalid,headers=headers).status_code,422)
            success = client.put(url,json=payload,headers=headers)
            self.assertEqual(success.status_code,200,success.text)
            self.assertEqual(success.json()["revision"],2)
            public = client.get("/api/v1/personality/traits")
            self.assertEqual(public.json()["source"],"database")
            self.assertNotEqual(public.headers["etag"],original_etag)
            self.assertEqual(client.put(url,json=payload,headers=headers).status_code,409)
            with self.sessions() as s:
                self.assertEqual(len(s.scalars(select(AdminAuditLog)).all()),1)
            client.post("/api/v1/admin/session",json={"username":"viewer","password":"viewer-password"})
            self.assertEqual(client.put(url,json=payload,headers=headers).status_code,403)

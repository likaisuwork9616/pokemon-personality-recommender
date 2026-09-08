from __future__ import annotations

import unittest
from decimal import Decimal
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api.catalog import router
from app.api.deps import get_pokemon_repository
from app.repositories import PokemonRepository


def namespace(**values):
    return SimpleNamespace(**values)


def pokemon_fixture(identifier: int, *, name: str) -> SimpleNamespace:
    type_record = namespace(
        id=12,
        code="grass",
        name_en="Grass",
        name_zh="草",
    )
    return namespace(
        id=identifier,
        pokedex_number=identifier,
        form_key="default",
        name_zh=name,
        name_en=f"Pokemon {identifier}",
        category_zh="種子寶可夢",
        genus="Seed Pokemon",
        generation=1,
        is_legendary=False,
        is_mythical=False,
        is_baby=False,
        height_m=Decimal("0.70"),
        weight_kg=Decimal("6.90"),
        abilities="overgrow|chlorophyll",
        hidden_ability="chlorophyll",
        egg_groups="monster|plant",
        habitat="grassland",
        color="green",
        shape="quadruped",
        growth_rate="medium-slow",
        capture_rate=45,
        type_links=[namespace(slot=1, type_record=type_record)],
        images=[
            namespace(
                id=identifier * 10 + 2,
                image_kind="sprite",
                image_url=f"https://example.test/{identifier}-sprite.png",
                is_primary=False,
            ),
            namespace(
                id=identifier * 10 + 1,
                image_kind="artwork",
                image_url=f"https://example.test/{identifier}.png",
                is_primary=True,
            ),
        ],
        descriptions=[
            namespace(
                id=identifier * 100,
                language_code="zh-Hant",
                description_kind="description",
                source_key="csv:description_zh",
                content="會在陽光下休息。",
                content_hash="a" * 64,
                is_primary=True,
            ),
            namespace(
                id=identifier * 100 + 1,
                language_code="en",
                description_kind="flavor_text",
                source_key="csv:flavor_text_en",
                content="It rests in the sunlight.",
                content_hash="b" * 64,
                is_primary=True,
            ),
            namespace(
                id=identifier * 100 + 2,
                language_code="mul",
                description_kind="analysis",
                source_key="csv:analysis_text",
                content="沉著而重視夥伴。",
                content_hash="c" * 64,
                is_primary=True,
            ),
            namespace(
                id=identifier * 100 + 3,
                language_code="zh-Hant",
                description_kind="admin_note",
                source_key="admin:note",
                content="僅供管理員參考。",
                content_hash="d" * 64,
                is_primary=False,
            ),
        ],
        stats=namespace(
            hp=45,
            attack=49,
            defense=49,
            sp_attack=65,
            sp_defense=65,
            speed=45,
            base_stat_total=318,
        ),
    )


class FakePokemonRepository:
    def __init__(self) -> None:
        self.items = [
            pokemon_fixture(1, name="妙蛙種子"),
            pokemon_fixture(2, name="妙蛙草"),
        ]
        self.search_calls: list[dict] = []

    def search_catalog(self, **filters):
        self.search_calls.append(filters)
        return self.items, 5

    def get_catalog_detail(self, pokemon_id: int):
        return next((item for item in self.items if item.id == pokemon_id), None)


class CatalogApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakePokemonRepository()
        application = FastAPI()
        application.include_router(router)
        application.dependency_overrides[get_pokemon_repository] = (
            lambda: self.repository
        )
        self.client = TestClient(application)

    def test_list_returns_page_metadata_and_stable_repository_order(self):
        response = self.client.get("/api/v1/pokemon?page=2&page_size=2")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual((body["page"], body["page_size"]), (2, 2))
        self.assertEqual((body["total"], body["total_pages"]), (5, 3))
        self.assertEqual(
            [item["pokedex_number"] for item in body["items"]], [1, 2]
        )
        self.assertEqual(body["items"][0]["types"][0]["code"], "grass")
        self.assertEqual(
            body["items"][0]["image_url"], "https://example.test/1.png"
        )

    def test_all_search_and_filter_parameters_reach_repository(self):
        response = self.client.get(
            "/api/v1/pokemon",
            params={
                "q": "妙蛙",
                "page": 3,
                "page_size": 10,
                "type": "grass",
                "generation": 1,
                "is_legendary": "false",
                "is_mythical": "true",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.repository.search_calls[-1],
            {
                "q": "妙蛙",
                "page": 3,
                "page_size": 10,
                "type_code": "grass",
                "generation": 1,
                "is_legendary": False,
                "is_mythical": True,
            },
        )

    def test_detail_returns_relational_data(self):
        response = self.client.get("/api/v1/pokemon/1")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["name_zh"], "妙蛙種子")
        self.assertEqual(body["stats"]["base_stat_total"], 318)
        self.assertEqual(
            [
                (
                    item["language_code"],
                    item["description_kind"],
                    item["source_key"],
                )
                for item in body["descriptions"]
            ],
            [("zh-Hant", "description", "csv:description_zh")],
        )
        self.assertEqual(
            body["descriptions"][0]["paragraphs"],
            ["會在陽光下休息。"],
        )
        self.assertEqual(len(self.repository.items[0].descriptions), 4)
        self.assertEqual(
            [image["image_kind"] for image in body["images"]],
            ["artwork", "sprite"],
        )
        self.assertEqual(body["height_m"], 0.7)
        self.assertEqual(body["abilities"], "overgrow|chlorophyll")
        self.assertEqual(body["hidden_ability"], "chlorophyll")
        self.assertEqual(
            body["ability_details"],
            [
                {"code": "overgrow", "name_zh": "茂盛", "is_hidden": False},
                {
                    "code": "chlorophyll",
                    "name_zh": "葉綠素",
                    "is_hidden": True,
                },
            ],
        )
        self.assertEqual(body["egg_groups"], "monster|plant")
        self.assertEqual(
            body["egg_group_details"],
            [
                {"code": "monster", "name_zh": "怪獸"},
                {"code": "plant", "name_zh": "植物"},
            ],
        )
        self.assertEqual(
            body["habitat_detail"],
            {"code": "grassland", "name_zh": "草原"},
        )
        self.assertEqual(
            body["growth_rate_detail"],
            {"code": "medium-slow", "name_zh": "較慢"},
        )

    def test_inactive_or_unknown_detail_is_reported_as_not_found(self):
        response = self.client.get("/api/v1/pokemon/999")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "pokemon_not_found")

    def test_pagination_and_generation_are_validated(self):
        for params in (
            {"page": 0},
            {"page_size": 101},
            {"generation": 10},
        ):
            with self.subTest(params=params):
                response = self.client.get("/api/v1/pokemon", params=params)
                self.assertEqual(response.status_code, 422)

    def test_openapi_uses_public_type_query_name(self):
        application = FastAPI()
        application.include_router(router)
        parameters = application.openapi()["paths"]["/api/v1/pokemon"]["get"][
            "parameters"
        ]

        self.assertIn("type", {parameter["name"] for parameter in parameters})


class _ScalarRows:
    def unique(self):
        return self

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
        return _ScalarRows()


class CatalogRepositoryTests(unittest.TestCase):
    def test_search_sql_is_active_only_filtered_and_stably_sorted(self):
        session = _RecordingSession()
        repository = PokemonRepository(session)

        items, total = repository.search_catalog(
            q="100%_hero",
            page=2,
            page_size=25,
            type_code="Grass",
            generation=1,
            is_legendary=False,
            is_mythical=False,
        )

        self.assertEqual((items, total), ([], 0))
        sql = str(
            session.statements[-1].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("pokemon.is_active IS true", sql)
        self.assertIn("lower(types.code) = 'grass'", sql)
        self.assertIn("pokemon.generation = 1", sql)
        self.assertIn(
            "ORDER BY pokemon.pokedex_number, pokemon.form_key, pokemon.id",
            sql,
        )
        self.assertIn("LIMIT 25 OFFSET 25", sql)


if __name__ == "__main__":
    unittest.main()

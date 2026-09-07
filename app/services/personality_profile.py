"""In-memory Pokémon personality profiles backed by PostgreSQL records."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any

import jieba
import numpy as np
import pandas as pd

from app.services.embedding import DEFAULT_MODEL_NAME


TYPE_PERSONALITY_WEIGHTS: dict[str, tuple[float, ...]] = {
    "火": (1.8, 2.4, 2.0, 2.5, 0.5, 0.6, 0.4, 1.0, 0.6, 0.5, 0.6, 0.7, 1.2, 0.8, 1.5, 0.6),
    "水": (0.6, 0.5, 0.4, 0.5, 1.2, 1.5, 1.8, 0.8, 2.5, 2.6, 2.0, 1.2, 0.7, 0.8, 1.1, 0.9),
    "草": (1.4, 1.0, 0.8, 0.9, 0.7, 1.0, 2.2, 2.0, 2.6, 2.4, 2.0, 1.1, 0.9, 1.2, 1.3, 0.8),
    "電": (2.5, 2.6, 2.4, 2.0, 1.0, 0.9, 0.7, 1.2, 0.5, 0.6, 0.8, 0.9, 1.8, 1.3, 1.9, 1.0),
    "冰": (0.5, 0.6, 0.4, 0.5, 2.0, 2.4, 2.6, 1.2, 1.0, 0.8, 1.0, 1.3, 1.5, 1.4, 1.2, 1.0),
    "格鬥": (0.8, 1.2, 2.5, 2.8, 0.6, 0.7, 0.5, 1.0, 0.7, 0.6, 0.9, 1.2, 1.0, 0.8, 0.7, 0.6),
    "毒": (0.5, 0.6, 0.7, 0.8, 1.4, 1.6, 2.0, 1.1, 1.0, 0.9, 1.0, 1.3, 2.4, 2.2, 1.1, 1.0),
    "地面": (0.7, 0.8, 0.9, 2.2, 1.5, 1.4, 1.0, 0.9, 1.2, 1.0, 1.6, 2.5, 0.8, 0.7, 0.9, 1.1),
    "飛行": (2.2, 2.4, 2.0, 1.8, 1.2, 1.0, 0.9, 1.5, 1.0, 1.1, 1.3, 1.2, 0.9, 0.8, 2.6, 1.0),
    "超能力": (1.5, 1.6, 1.2, 1.0, 2.6, 2.5, 1.8, 2.4, 1.1, 1.2, 1.3, 2.5, 1.4, 2.0, 2.6, 1.5),
    "蟲": (1.0, 1.1, 0.9, 0.8, 1.2, 1.3, 1.5, 2.0, 1.4, 1.6, 1.8, 1.2, 0.9, 1.1, 2.2, 1.3),
    "岩石": (0.6, 0.7, 0.8, 2.0, 1.4, 1.6, 1.2, 0.9, 1.1, 1.0, 1.5, 2.6, 0.8, 0.9, 1.0, 1.1),
    "幽靈": (0.5, 0.6, 0.7, 0.8, 2.2, 2.6, 2.4, 1.5, 1.0, 0.9, 1.1, 1.3, 2.6, 2.8, 1.4, 1.2),
    "龍": (2.0, 2.2, 2.5, 2.8, 1.5, 1.6, 1.2, 2.0, 1.4, 1.2, 2.0, 2.6, 1.5, 1.8, 2.2, 1.3),
    "惡": (0.6, 0.8, 2.6, 2.8, 1.2, 1.4, 1.0, 0.9, 1.0, 0.8, 1.1, 1.5, 2.6, 2.8, 1.2, 1.1),
    "鋼": (0.5, 0.6, 0.7, 2.5, 1.8, 2.0, 1.5, 1.0, 1.2, 1.1, 2.6, 2.8, 1.0, 1.1, 1.3, 1.2),
    "妖精": (2.6, 2.4, 1.8, 1.5, 1.0, 1.2, 2.6, 2.8, 2.5, 2.6, 2.0, 1.5, 1.4, 1.6, 1.8, 1.2),
    "一般": (1.2, 1.0, 1.0, 1.2, 1.0, 1.0, 1.0, 1.0, 1.2, 1.1, 1.3, 1.2, 1.0, 1.0, 1.0, 1.0),
}

ENGLISH_TYPE_TO_ZH = {
    "Normal": "一般",
    "Fire": "火",
    "Water": "水",
    "Grass": "草",
    "Electric": "電",
    "Ice": "冰",
    "Fighting": "格鬥",
    "Poison": "毒",
    "Ground": "地面",
    "Flying": "飛行",
    "Psychic": "超能力",
    "Bug": "蟲",
    "Rock": "岩石",
    "Ghost": "幽靈",
    "Dragon": "龍",
    "Dark": "惡",
    "Steel": "鋼",
    "Fairy": "妖精",
}


class PokemonPersonalityProfile:
    """Build deterministic personality vectors for database-backed Pokémon."""

    def __init__(
        self,
        *,
        dataframe: pd.DataFrame,
        personality_traits: Sequence[str],
        persona_keywords: Mapping[str, Sequence[str]],
    ) -> None:
        self.traits = tuple(str(trait) for trait in personality_traits)
        self.persona_keywords = {
            str(trait): tuple(str(keyword) for keyword in keywords)
            for trait, keywords in persona_keywords.items()
        }
        if len(self.traits) != 16 or set(self.persona_keywords) != set(self.traits):
            raise ValueError("personality catalog must define all 16 ordered traits")
        if any(not self.persona_keywords[trait] for trait in self.traits):
            raise ValueError("every personality trait requires at least one keyword")

        self.df = dataframe.copy().fillna("")
        self.id_col = "pokedex_number"
        self.name_col = "name_zh"
        self.name_en_col = "name_en"
        self.type_col = "type_zh"
        self.type_1_col = "type_1"
        self.type_2_col = "type_2"
        self.cat_col = "category_zh"
        self.genus_col = "genus"
        self.desc_col = "description_zh"
        self.flavor_en_col = "flavor_text_en"
        self.analysis_col = "analysis_text"
        self.img_col = "image_url"
        self.sprite_col = "sprite_url"

        self._validate_columns()
        self.st_model = self._load_sentence_model()
        self.persona_vectors = self.build_persona_vectors()

    def _validate_columns(self) -> None:
        required_columns = (
            self.id_col,
            self.name_col,
            self.name_en_col,
            self.type_col,
            self.cat_col,
            self.desc_col,
            self.analysis_col,
            self.img_col,
        )
        missing = [column for column in required_columns if column not in self.df.columns]
        if missing:
            raise ValueError(f"Pokémon profile records are missing columns: {missing}")

    @staticmethod
    def _load_sentence_model() -> Any:
        from sentence_transformers import SentenceTransformer

        model_name = os.getenv("EMBEDDING_MODEL", DEFAULT_MODEL_NAME)
        token = os.getenv("HF_TOKEN") or None
        try:
            return SentenceTransformer(model_name, token=token)
        except TypeError:
            return SentenceTransformer(model_name, use_auth_token=token)

    @staticmethod
    def safe_get(row: pd.Series, column: str, default: str = "") -> Any:
        return row.get(column, default) if column in row.index else default

    @staticmethod
    def normalize_vec(vector: np.ndarray) -> np.ndarray:
        norm = np.linalg.norm(vector)
        return vector / norm if norm > 0 else vector

    def parse_types(self, row: pd.Series) -> list[str]:
        types = [
            value.strip()
            for value in str(self.safe_get(row, self.type_col, ""))
            .replace("，", ",")
            .split(",")
            if value.strip()
        ]
        if types:
            return types

        for column in (self.type_1_col, self.type_2_col):
            translated = ENGLISH_TYPE_TO_ZH.get(
                str(self.safe_get(row, column, "")).strip()
            )
            if translated:
                types.append(translated)
        return types

    def text_to_persona_vector(self, text: str) -> np.ndarray:
        normalized_text = str(text)
        words = set(jieba.lcut(normalized_text))
        lowered_text = normalized_text.lower()
        vector = np.zeros(len(self.traits))

        for index, trait in enumerate(self.traits):
            for keyword in self.persona_keywords[trait]:
                if (
                    keyword in normalized_text
                    or keyword in words
                    or keyword.lower() in lowered_text
                ):
                    vector[index] += 2.0
        return self.normalize_vec(vector)

    def build_persona_vectors(self) -> np.ndarray:
        vectors: list[np.ndarray] = []
        for _, row in self.df.iterrows():
            vector = np.zeros(len(self.traits))
            for pokemon_type in self.parse_types(row):
                weights = TYPE_PERSONALITY_WEIGHTS.get(pokemon_type)
                if weights is not None:
                    vector += np.asarray(weights, dtype=float)

            profile_text = " ".join(
                str(self.safe_get(row, column, ""))
                for column in (
                    self.cat_col,
                    self.genus_col,
                    self.desc_col,
                    self.flavor_en_col,
                    self.analysis_col,
                )
            )
            vector += self.text_to_persona_vector(profile_text)
            vectors.append(self.normalize_vec(vector))
        return np.asarray(vectors)

    def get_top_traits(self, vector: np.ndarray, top_n: int = 3) -> list[str]:
        indexes = np.argsort(-vector)[:top_n]
        return [self.traits[index] for index in indexes if vector[index] > 0]

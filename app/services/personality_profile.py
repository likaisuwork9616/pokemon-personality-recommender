"""Pokémon display metadata and the shared local sentence encoder."""

from __future__ import annotations

import os
from typing import Any

import pandas as pd

from app.services.embedding import DEFAULT_MODEL_NAME


class PokemonPersonalityProfile:
    """Keep metadata separate from indexed behavior used for MBTI matching."""

    def __init__(self, *, dataframe: pd.DataFrame, encoder: Any | None = None) -> None:
        self.df = dataframe.copy().fillna("")
        self.id_col = "pokedex_number"
        self.name_col = "name_zh"
        self.name_en_col = "name_en"
        self.type_col = "type_zh"
        self.type_1_col = "type_1"
        self.type_2_col = "type_2"
        self.cat_col = "category_zh"
        self.genus_col = "genus"
        self.img_col = "image_url"
        self.sprite_col = "sprite_url"
        self._validate_columns()
        self.st_model = encoder if encoder is not None else self._load_sentence_model()

    def _validate_columns(self) -> None:
        required = ("_database_id", self.id_col, self.name_col, self.name_en_col, self.type_col)
        missing = [column for column in required if column not in self.df.columns]
        if missing:
            raise ValueError(f"Pokémon metadata records are missing columns: {missing}")

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
        return row.get(column, default)


"""Validated runtime choices shared by MBTI entry points."""
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class MbtiCatalogSettings:
    source: str = "bundled"

    def __post_init__(self):
        if self.source not in {"bundled", "database"}:
            raise ValueError("MBTI_CATALOG_SOURCE must be bundled or database")

    @classmethod
    def from_env(cls):
        return cls(os.getenv("MBTI_CATALOG_SOURCE", "bundled").strip().lower())

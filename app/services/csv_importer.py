"""Strict, repeatable import of the canonical Pokemon CSV dataset."""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.repositories import PokemonRepository


DEFAULT_CSV_PATH = (
    Path(__file__).resolve().parents[2] / "pokemon_descript" / "pokedex_final.csv"
)

CSV_COLUMNS = (
    "pokedex_number",
    "name_zh",
    "name_en",
    "type_zh",
    "type_1",
    "type_2",
    "category_zh",
    "genus",
    "description_zh",
    "flavor_text_en",
    "analysis_text",
    "image_url",
    "sprite_url",
    "hp",
    "attack",
    "defense",
    "sp_attack",
    "sp_defense",
    "speed",
    "base_stat_total",
    "height_m",
    "weight_kg",
    "abilities",
    "hidden_ability",
    "generation",
    "is_legendary",
    "is_mythical",
    "is_baby",
    "color",
    "shape",
    "egg_groups",
    "habitat",
    "growth_rate",
    "capture_rate",
    "is_outlier",
    "lof_outlier",
    "scaled_hp",
    "scaled_attack",
    "scaled_defense",
    "scaled_sp_attack",
    "scaled_sp_defense",
    "scaled_speed",
    "scaled_height_m",
    "scaled_weight_kg",
)


@dataclass(frozen=True)
class TypeDefinition:
    code: str
    name_en: str
    name_zh: str


TYPE_DEFINITIONS = {
    definition.name_en: definition
    for definition in (
        TypeDefinition("normal", "Normal", "一般"),
        TypeDefinition("fire", "Fire", "火"),
        TypeDefinition("water", "Water", "水"),
        TypeDefinition("grass", "Grass", "草"),
        TypeDefinition("electric", "Electric", "電"),
        TypeDefinition("ice", "Ice", "冰"),
        TypeDefinition("fighting", "Fighting", "格鬥"),
        TypeDefinition("poison", "Poison", "毒"),
        TypeDefinition("ground", "Ground", "地面"),
        TypeDefinition("flying", "Flying", "飛行"),
        TypeDefinition("psychic", "Psychic", "超能力"),
        TypeDefinition("bug", "Bug", "蟲"),
        TypeDefinition("rock", "Rock", "岩石"),
        TypeDefinition("ghost", "Ghost", "幽靈"),
        TypeDefinition("dragon", "Dragon", "龍"),
        TypeDefinition("dark", "Dark", "惡"),
        TypeDefinition("steel", "Steel", "鋼"),
        TypeDefinition("fairy", "Fairy", "妖精"),
    )
}

GENERATION_VALUES = {
    "gen-i": 1,
    "gen-ii": 2,
    "gen-iii": 3,
    "gen-iv": 4,
    "gen-v": 5,
    "gen-vi": 6,
    "gen-vii": 7,
    "gen-viii": 8,
    "gen-ix": 9,
}


class CsvImportError(ValueError):
    """A CSV contract or row conversion error with row context."""


@dataclass(frozen=True)
class PokemonPayload:
    pokedex_number: int
    form_key: str
    name_zh: str
    name_en: str
    category_zh: str | None
    genus: str | None
    generation: int
    habitat: str | None
    color: str | None
    shape: str | None
    growth_rate: str | None
    abilities: str
    hidden_ability: str | None
    egg_groups: str
    height_m: Decimal | None
    weight_kg: Decimal | None
    capture_rate: int | None
    is_legendary: bool
    is_mythical: bool
    is_baby: bool
    is_outlier: int
    lof_outlier: int


@dataclass(frozen=True)
class StatsPayload:
    hp: int
    attack: int
    defense: int
    sp_attack: int
    sp_defense: int
    speed: int
    base_stat_total: int
    scaled_hp: float
    scaled_attack: float
    scaled_defense: float
    scaled_sp_attack: float
    scaled_sp_defense: float
    scaled_speed: float
    scaled_height_m: float
    scaled_weight_kg: float


@dataclass(frozen=True)
class DescriptionPayload:
    language_code: str
    description_kind: str
    source_key: str
    content: str
    content_hash: str
    is_primary: bool


@dataclass(frozen=True)
class ImagePayload:
    image_kind: str
    image_url: str
    is_primary: bool


@dataclass(frozen=True)
class ParsedPokemonRow:
    source_row: int
    pokemon: PokemonPayload
    type_codes: tuple[str, ...]
    stats: StatsPayload
    descriptions: tuple[DescriptionPayload, ...]
    images: tuple[ImagePayload, ...]


@dataclass(frozen=True)
class ImportSummary:
    processed: int
    created: int
    existing: int
    dry_run: bool


def _error(row_number: int, field: str, message: str) -> CsvImportError:
    return CsvImportError(f"CSV row {row_number}, field '{field}': {message}")


def _required_text(row: Mapping[str, str], field: str, row_number: int) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise _error(row_number, field, "value is required")
    return value


def _optional_text(
    row: Mapping[str, str],
    field: str,
    *,
    unknown_is_none: bool = False,
) -> str | None:
    value = (row.get(field) or "").strip()
    if not value or (unknown_is_none and value.casefold() == "unknown"):
        return None
    return value


def _integer(
    row: Mapping[str, str],
    field: str,
    row_number: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    raw = _required_text(row, field, row_number)
    try:
        numeric_value = Decimal(raw)
    except InvalidOperation as exc:
        raise _error(row_number, field, f"expected integer, got {raw!r}") from exc
    if not numeric_value.is_finite() or numeric_value != numeric_value.to_integral_value():
        raise _error(row_number, field, f"expected integer, got {raw!r}")
    value = int(numeric_value)
    if minimum is not None and value < minimum:
        raise _error(row_number, field, f"must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise _error(row_number, field, f"must be <= {maximum}")
    return value


def _decimal(
    row: Mapping[str, str], field: str, row_number: int
) -> Decimal:
    raw = _required_text(row, field, row_number)
    try:
        value = Decimal(raw)
    except InvalidOperation as exc:
        raise _error(row_number, field, f"expected decimal, got {raw!r}") from exc
    if not value.is_finite() or value <= 0:
        raise _error(row_number, field, "must be a finite positive number")
    return value


def _float(row: Mapping[str, str], field: str, row_number: int) -> float:
    raw = _required_text(row, field, row_number)
    try:
        value = float(raw)
    except ValueError as exc:
        raise _error(row_number, field, f"expected number, got {raw!r}") from exc
    if value != value or value in {float("inf"), float("-inf")}:
        raise _error(row_number, field, "must be finite")
    return value


def _boolean(row: Mapping[str, str], field: str, row_number: int) -> bool:
    raw = _required_text(row, field, row_number).casefold()
    if raw == "true":
        return True
    if raw == "false":
        return False
    raise _error(row_number, field, "expected True or False")


def _outlier(row: Mapping[str, str], field: str, row_number: int) -> int:
    value = _integer(row, field, row_number)
    if value not in {-1, 1}:
        raise _error(row_number, field, "expected -1 or 1")
    return value


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def parse_csv_row(
    row: Mapping[str, str], *, row_number: int = 2
) -> ParsedPokemonRow:
    """Convert one CSV dictionary into a fully typed aggregate payload."""

    missing = [column for column in CSV_COLUMNS if column not in row]
    unexpected = [column for column in row if column not in CSV_COLUMNS]
    if missing or unexpected:
        raise CsvImportError(
            f"CSV row {row_number} has invalid columns; "
            f"missing={missing}, unexpected={unexpected}"
        )
    if any(value is None for value in row.values()):
        raise CsvImportError(f"CSV row {row_number} has fewer values than columns")

    generation_raw = _required_text(row, "generation", row_number).casefold()
    try:
        generation = GENERATION_VALUES[generation_raw]
    except KeyError as exc:
        raise _error(row_number, "generation", f"unknown value {generation_raw!r}") from exc

    type_names = [_required_text(row, "type_1", row_number)]
    type_2 = _optional_text(row, "type_2", unknown_is_none=True)
    if type_2:
        type_names.append(type_2)
    try:
        type_definitions = [TYPE_DEFINITIONS[name] for name in type_names]
    except KeyError as exc:
        raise _error(row_number, "type_1/type_2", f"unknown type {exc.args[0]!r}") from exc

    type_zh = [
        value.strip()
        for value in (row.get("type_zh") or "").replace("，", ",").split(",")
        if value.strip()
    ]
    expected_type_zh = [definition.name_zh for definition in type_definitions]
    # Type: Null (#772) is the source dataset's sole missing translated type.
    if not type_zh and expected_type_zh == ["一般"]:
        type_zh = expected_type_zh
    if type_zh != expected_type_zh:
        raise _error(
            row_number,
            "type_zh",
            f"expected {expected_type_zh!r} from English type slots, got {type_zh!r}",
        )

    stats = StatsPayload(
        hp=_integer(row, "hp", row_number, minimum=0),
        attack=_integer(row, "attack", row_number, minimum=0),
        defense=_integer(row, "defense", row_number, minimum=0),
        sp_attack=_integer(row, "sp_attack", row_number, minimum=0),
        sp_defense=_integer(row, "sp_defense", row_number, minimum=0),
        speed=_integer(row, "speed", row_number, minimum=0),
        base_stat_total=_integer(row, "base_stat_total", row_number, minimum=0),
        scaled_hp=_float(row, "scaled_hp", row_number),
        scaled_attack=_float(row, "scaled_attack", row_number),
        scaled_defense=_float(row, "scaled_defense", row_number),
        scaled_sp_attack=_float(row, "scaled_sp_attack", row_number),
        scaled_sp_defense=_float(row, "scaled_sp_defense", row_number),
        scaled_speed=_float(row, "scaled_speed", row_number),
        scaled_height_m=_float(row, "scaled_height_m", row_number),
        scaled_weight_kg=_float(row, "scaled_weight_kg", row_number),
    )
    raw_stat_total = (
        stats.hp
        + stats.attack
        + stats.defense
        + stats.sp_attack
        + stats.sp_defense
        + stats.speed
    )
    if stats.base_stat_total != raw_stat_total:
        raise _error(
            row_number,
            "base_stat_total",
            f"expected sum of six stats ({raw_stat_total})",
        )

    description_values = (
        ("zh-Hant", "description", "csv:description_zh", "description_zh"),
        ("en", "flavor_text", "csv:flavor_text_en", "flavor_text_en"),
        ("mul", "analysis", "csv:analysis_text", "analysis_text"),
    )
    descriptions = tuple(
        DescriptionPayload(
            language_code=language_code,
            description_kind=kind,
            source_key=source_key,
            content=content,
            content_hash=_content_hash(content),
            is_primary=True,
        )
        for language_code, kind, source_key, field in description_values
        for content in [_required_text(row, field, row_number)]
    )

    images = (
        ImagePayload(
            image_kind="artwork",
            image_url=_required_text(row, "image_url", row_number),
            is_primary=True,
        ),
        ImagePayload(
            image_kind="sprite",
            image_url=_required_text(row, "sprite_url", row_number),
            is_primary=False,
        ),
    )

    return ParsedPokemonRow(
        source_row=row_number,
        pokemon=PokemonPayload(
            pokedex_number=_integer(row, "pokedex_number", row_number, minimum=1),
            form_key="default",
            name_zh=_required_text(row, "name_zh", row_number),
            name_en=_required_text(row, "name_en", row_number),
            category_zh=_optional_text(row, "category_zh"),
            genus=_optional_text(row, "genus"),
            generation=generation,
            habitat=_optional_text(row, "habitat", unknown_is_none=True),
            color=_optional_text(row, "color"),
            shape=_optional_text(row, "shape"),
            growth_rate=_optional_text(row, "growth_rate"),
            abilities=_required_text(row, "abilities", row_number),
            hidden_ability=_optional_text(
                row, "hidden_ability", unknown_is_none=True
            ),
            egg_groups=_required_text(row, "egg_groups", row_number),
            height_m=_decimal(row, "height_m", row_number),
            weight_kg=_decimal(row, "weight_kg", row_number),
            capture_rate=_integer(
                row, "capture_rate", row_number, minimum=0, maximum=255
            ),
            is_legendary=_boolean(row, "is_legendary", row_number),
            is_mythical=_boolean(row, "is_mythical", row_number),
            is_baby=_boolean(row, "is_baby", row_number),
            is_outlier=_outlier(row, "is_outlier", row_number),
            lof_outlier=_outlier(row, "lof_outlier", row_number),
        ),
        type_codes=tuple(definition.code for definition in type_definitions),
        stats=stats,
        descriptions=descriptions,
        images=images,
    )


def read_csv_records(path: str | Path = DEFAULT_CSV_PATH) -> list[ParsedPokemonRow]:
    """Read and validate the complete CSV before opening a DB transaction."""

    csv_path = Path(path)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        if len(fieldnames) != len(set(fieldnames)):
            raise CsvImportError("CSV header contains duplicate columns")
        missing = [column for column in CSV_COLUMNS if column not in fieldnames]
        unexpected = [column for column in fieldnames if column not in CSV_COLUMNS]
        if missing or unexpected:
            raise CsvImportError(
                f"CSV header is invalid; missing={missing}, unexpected={unexpected}"
            )
        records = [
            parse_csv_row(row, row_number=line_number)
            for line_number, row in enumerate(reader, start=2)
        ]

    if not records:
        raise CsvImportError("CSV contains no Pokemon rows")
    natural_keys = [
        (record.pokemon.pokedex_number, record.pokemon.form_key)
        for record in records
    ]
    if len(natural_keys) != len(set(natural_keys)):
        raise CsvImportError("CSV contains duplicate pokedex_number/form_key rows")
    return records


class CsvPokemonImporter:
    """Apply validated CSV records in one atomic, optionally rolled-back import."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        repository_factory: Callable[[Session], PokemonRepository] = PokemonRepository,
    ) -> None:
        self.session_factory = session_factory
        self.repository_factory = repository_factory

    def import_file(
        self,
        path: str | Path = DEFAULT_CSV_PATH,
        *,
        dry_run: bool = False,
    ) -> ImportSummary:
        return self.import_records(read_csv_records(path), dry_run=dry_run)

    def import_records(
        self,
        records: Iterable[ParsedPokemonRow],
        *,
        dry_run: bool = False,
    ) -> ImportSummary:
        materialized = list(records)
        session = self.session_factory()
        transaction = session.begin()
        created = 0
        existing = 0
        try:
            repository = self.repository_factory(session)
            type_ids = repository.seed_types(
                {definition.code: definition for definition in TYPE_DEFINITIONS.values()}
            )
            for record in materialized:
                found = repository.get_by_natural_key(
                    record.pokemon.pokedex_number,
                    record.pokemon.form_key,
                )
                if found is None:
                    created += 1
                else:
                    existing += 1
                repository.upsert_record(record, type_ids)

            if dry_run:
                transaction.rollback()
            else:
                transaction.commit()
        except Exception:
            if transaction.is_active:
                transaction.rollback()
            raise
        finally:
            session.close()

        return ImportSummary(
            processed=len(materialized),
            created=created,
            existing=existing,
            dry_run=dry_run,
        )

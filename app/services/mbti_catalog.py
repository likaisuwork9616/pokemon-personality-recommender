"""Validated, immutable MBTI content with no database or network dependency."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

from app.personality_vocabulary import canonicalize_personality_text


MBTI_CODES = (
    "ENFJ", "ENFP", "ENTJ", "ENTP", "ESFJ", "ESFP", "ESTJ", "ESTP",
    "INFJ", "INFP", "INTJ", "INTP", "ISFJ", "ISFP", "ISTJ", "ISTP",
)
_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "mbti_zh_hant.json"
_CODE_PATTERN = re.compile(r"[EI][SN][TF][JP](?:-[AT])?")
_TEXT_FIELDS = (
    "name_zh", "summary", "information_style", "decision_style",
    "interaction_style", "action_style", "stress_pattern",
)
_LIST_FIELDS = ("strengths", "blind_spots", "growth_tips")


def normalize_mbti(value: str | None) -> str | None:
    """Normalize a user-selected type; A/T is accepted only as an input suffix."""

    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("MBTI 請輸入四字母類型，例如 INFP，或留空。")
    normalized = unicodedata.normalize("NFKC", value).strip().upper()
    if not normalized:
        return None
    if not _CODE_PATTERN.fullmatch(normalized):
        raise ValueError("MBTI 格式不正確，請輸入 16 型之一，例如 INFP；可附加 -A 或 -T。")
    return normalized[:4]


@dataclass(frozen=True, slots=True)
class MbtiWeightedTerm:
    term: str
    weight: float


@dataclass(frozen=True, slots=True)
class MbtiProfile:
    code: str
    name_zh: str
    summary: str
    information_style: str
    decision_style: str
    interaction_style: str
    action_style: str
    strengths: tuple[str, ...]
    blind_spots: tuple[str, ...]
    stress_pattern: str
    growth_tips: tuple[str, ...]
    weighted_terms: tuple[MbtiWeightedTerm, ...]
    source_urls: tuple[str, ...]
    reviewed_at: str

    @property
    def matching_text(self) -> str:
        """Positive descriptive evidence; exclude cautions that negate traits."""

        return " ".join((
            self.summary, self.information_style, self.decision_style,
            self.interaction_style, self.action_style, *self.strengths,
        ))


@dataclass(frozen=True, slots=True)
class MbtiCatalog:
    version: str
    revision: int
    reviewed_at: str
    profiles: tuple[MbtiProfile, ...]
    content_hash: str

    @property
    def codes(self) -> tuple[str, ...]:
        return tuple(profile.code for profile in self.profiles)

    def profile_for(self, code: str) -> MbtiProfile:
        normalized = normalize_mbti(code)
        for profile in self.profiles:
            if profile.code == normalized:
                return profile
        raise ValueError("請先指定有效的 MBTI 四字母類型。")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"MBTI 資料的 {label} 必須是完整的非空白文字。")
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in value):
        raise RuntimeError(f"MBTI 資料的 {label} 不可包含控制或格式字元。")
    return value.strip()


def _text_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise RuntimeError(f"MBTI 資料的 {label} 必須是非空白文字清單。")
    result = tuple(_text(item, label) for item in value)
    normalized = tuple(canonicalize_personality_text(item) for item in result)
    if len(set(normalized)) != len(normalized):
        raise RuntimeError(f"MBTI 資料的 {label} 含有正規化後重複的文字。")
    return result


def _review_date(value: object, label: str) -> str:
    text = _text(value, label)
    try:
        parsed = date.fromisoformat(text)
    except ValueError as exc:
        raise RuntimeError(f"MBTI 資料的 {label} 必須使用 YYYY-MM-DD 日期。") from exc
    if parsed.isoformat() != text:
        raise RuntimeError(f"MBTI 資料的 {label} 必須使用 YYYY-MM-DD 日期。")
    return text


def _weighted_terms(value: object, code: str) -> tuple[MbtiWeightedTerm, ...]:
    if not isinstance(value, list) or len(value) < 12:
        raise RuntimeError(f"MBTI {code} 至少需要 12 個行為關鍵詞。")
    terms: list[MbtiWeightedTerm] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            raise RuntimeError(f"MBTI {code} 的關鍵詞必須包含 term 與 weight。")
        term = _text(item.get("term"), f"{code}.weighted_terms.term")
        normalized = canonicalize_personality_text(term)
        if len(term) > 80 or len(normalized) > 80:
            raise RuntimeError(f"MBTI {code} 的關鍵詞及正規化文字不可超過 80 個字元。")
        if normalized in seen:
            raise RuntimeError(f"MBTI {code} 的關鍵詞正規化後重複：{term}。")
        if normalized.upper() in MBTI_CODES or _CODE_PATTERN.fullmatch(normalized.upper()):
            raise RuntimeError(f"MBTI {code} 的關鍵詞必須描述行為，不可只填人格代碼。")
        weight = item.get("weight")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or not 0 < weight <= 5
            or not math.isfinite(weight)
        ):
            raise RuntimeError(f"MBTI {code} 關鍵詞的權重必須大於 0 且不超過 5。")
        seen.add(normalized)
        terms.append(MbtiWeightedTerm(term=term, weight=float(weight)))
    if not any(re.search(r"[\u3400-\u9fff]", item.term) for item in terms):
        raise RuntimeError(f"MBTI {code} 的行為關鍵詞必須包含中文。")
    if not any(re.search(r"[A-Za-z]", item.term) for item in terms):
        raise RuntimeError(f"MBTI {code} 的行為關鍵詞必須包含英文。")
    return tuple(terms)


def _profile(payload: object) -> MbtiProfile:
    if not isinstance(payload, dict):
        raise RuntimeError("MBTI 人格資料必須是物件。")
    code = _text(payload.get("code"), "code")
    if code not in MBTI_CODES:
        raise RuntimeError("MBTI 資料代碼必須是標準大寫四字母類型。")
    text_fields = {field: _text(payload.get(field), f"{code}.{field}") for field in _TEXT_FIELDS}
    if len(text_fields["name_zh"]) > 40:
        raise RuntimeError(f"MBTI {code} 的中文名稱不可超過 40 個字元。")
    list_fields = {
        field: _text_list(payload.get(field), f"{code}.{field}")
        for field in _LIST_FIELDS
    }
    all_text = " ".join((*text_fields.values(), *(item for items in list_fields.values() for item in items)))
    if len(re.findall(r"[\u3400-\u9fff]", all_text)) < 250:
        raise RuntimeError(f"MBTI {code} 的多面向個性說明至少需要 250 個中文字。")
    source_urls = _text_list(payload.get("source_urls"), f"{code}.source_urls")
    for url in source_urls:
        try:
            parsed = urlsplit(url)
            # Accessing port also rejects non-numeric or out-of-range ports.
            port = parsed.port
            hostname = parsed.hostname
        except ValueError as exc:
            raise RuntimeError(f"MBTI {code} 的來源必須是有效的 HTTPS 網址。") from exc
        if (
            parsed.scheme != "https" or not hostname or parsed.username or parsed.password
            or any(character.isspace() for character in parsed.netloc)
            or (port is not None and not 0 <= port <= 65535)
        ):
            raise RuntimeError(f"MBTI {code} 的來源必須是有效的 HTTPS 網址。")
    return MbtiProfile(
        code=code,
        **text_fields,
        **list_fields,
        weighted_terms=_weighted_terms(payload.get("weighted_terms"), code),
        source_urls=source_urls,
        reviewed_at=_review_date(payload.get("reviewed_at"), f"{code}.reviewed_at"),
    )


def _catalog_from_payload(payload: object) -> MbtiCatalog:
    if not isinstance(payload, dict):
        raise RuntimeError("MBTI 資料根節點必須是物件。")
    version = _text(payload.get("version"), "version")
    if version != "mbti-zh-hant-v1":
        raise RuntimeError("MBTI 資料版本不受支援。")
    revision = payload.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise RuntimeError("MBTI 資料修訂版必須是正整數。")
    reviewed_at = _review_date(payload.get("reviewed_at"), "reviewed_at")
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, list) or len(raw_profiles) != len(MBTI_CODES):
        raise RuntimeError("MBTI 資料必須恰好包含 16 種人格。")
    profiles = tuple(_profile(item) for item in raw_profiles)
    codes = tuple(profile.code for profile in profiles)
    if len(set(codes)) != len(codes):
        raise RuntimeError("MBTI 資料包含重複的人格代碼。")
    if set(codes) != set(MBTI_CODES):
        raise RuntimeError("MBTI 資料必須完整包含標準的 16 種人格。")
    if codes != MBTI_CODES:
        raise RuntimeError("MBTI 人格必須依代碼字母順序排列。")
    canonical_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return MbtiCatalog(
        version=version,
        revision=revision,
        reviewed_at=reviewed_at,
        profiles=profiles,
        content_hash=hashlib.sha256(canonical_json.encode("utf-8")).hexdigest(),
    )


@lru_cache(maxsize=1)
def get_mbti_catalog() -> MbtiCatalog:
    """Read checked-in content once, failing clearly if the catalog is damaged."""

    try:
        payload = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("無法讀取 MBTI 個性資料，請檢查資料檔。") from exc
    return _catalog_from_payload(payload)

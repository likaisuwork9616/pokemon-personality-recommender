"""Versioned, deterministic rules for the Today Pokemon experience."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


TODAY_POKEMON_ALGORITHM_VERSION = "today-pokemon-v1"
ENTERTAINMENT_DISCLAIMER = (
    "今日運勢僅供娛樂與自我反思，不構成健康、財務、法律或其他專業建議。"
)


class ZodiacSign(StrEnum):
    ARIES = "aries"
    TAURUS = "taurus"
    GEMINI = "gemini"
    CANCER = "cancer"
    LEO = "leo"
    VIRGO = "virgo"
    LIBRA = "libra"
    SCORPIO = "scorpio"
    SAGITTARIUS = "sagittarius"
    CAPRICORN = "capricorn"
    AQUARIUS = "aquarius"
    PISCES = "pisces"


@dataclass(frozen=True)
class ZodiacProfile:
    code: ZodiacSign
    name_zh: str
    symbol: str
    date_range: str
    element: str
    modality: str
    trait_codes: tuple[str, ...]


TRAIT_LABELS = {
    "enthusiastic_leader": "熱情領導",
    "impulsive_adventurer": "勇於冒險",
    "social_charmer": "善於交流",
    "action_taker": "果斷行動",
    "calm_analyst": "冷靜分析",
    "strategic_planner": "策略規劃",
    "rational_observer": "理性觀察",
    "systems_thinker": "系統思考",
    "gentle_caregiver": "溫柔照顧",
    "emotional_empath": "情感共鳴",
    "loyal_guardian": "忠誠守護",
    "compassionate_supporter": "同理支持",
    "solitary_thinker": "獨立沉思",
    "introspective_conflict": "內省思考",
    "sensitive_creator": "敏銳創意",
    "observant_personality": "細心觀察",
}

TRAIT_QUERY_TERMS = {
    "enthusiastic_leader": ("熱情", "主動", "鼓舞"),
    "impulsive_adventurer": ("冒險", "探索", "勇敢"),
    "social_charmer": ("社交", "交流", "分享"),
    "action_taker": ("行動", "果斷", "實作"),
    "calm_analyst": ("冷靜", "分析", "沉著"),
    "strategic_planner": ("策略", "規劃", "有條理"),
    "rational_observer": ("理性", "客觀", "研究"),
    "systems_thinker": ("系統", "結構", "整體"),
    "gentle_caregiver": ("溫柔", "照顧", "體貼"),
    "emotional_empath": ("共感", "情感", "理解別人"),
    "loyal_guardian": ("忠誠", "守護", "可靠"),
    "compassionate_supporter": ("同理", "支持", "傾聽"),
    "solitary_thinker": ("獨立", "安靜", "沉思"),
    "introspective_conflict": ("內省", "反省", "想很多"),
    "sensitive_creator": ("敏感", "創意", "想像"),
    "observant_personality": ("觀察", "記錄", "留意"),
}

ZODIAC_PROFILES = {
    ZodiacSign.ARIES: ZodiacProfile(
        ZodiacSign.ARIES, "牡羊座", "♈", "3/21–4/19", "火", "開創",
        ("enthusiastic_leader", "impulsive_adventurer", "action_taker"),
    ),
    ZodiacSign.TAURUS: ZodiacProfile(
        ZodiacSign.TAURUS, "金牛座", "♉", "4/20–5/20", "土", "固定",
        ("loyal_guardian", "strategic_planner", "gentle_caregiver"),
    ),
    ZodiacSign.GEMINI: ZodiacProfile(
        ZodiacSign.GEMINI, "雙子座", "♊", "5/21–6/20", "風", "變動",
        ("social_charmer", "rational_observer", "sensitive_creator"),
    ),
    ZodiacSign.CANCER: ZodiacProfile(
        ZodiacSign.CANCER, "巨蟹座", "♋", "6/21–7/22", "水", "開創",
        ("gentle_caregiver", "emotional_empath", "loyal_guardian"),
    ),
    ZodiacSign.LEO: ZodiacProfile(
        ZodiacSign.LEO, "獅子座", "♌", "7/23–8/22", "火", "固定",
        ("enthusiastic_leader", "social_charmer", "action_taker"),
    ),
    ZodiacSign.VIRGO: ZodiacProfile(
        ZodiacSign.VIRGO, "處女座", "♍", "8/23–9/22", "土", "變動",
        ("calm_analyst", "strategic_planner", "observant_personality"),
    ),
    ZodiacSign.LIBRA: ZodiacProfile(
        ZodiacSign.LIBRA, "天秤座", "♎", "9/23–10/22", "風", "開創",
        ("social_charmer", "compassionate_supporter", "rational_observer"),
    ),
    ZodiacSign.SCORPIO: ZodiacProfile(
        ZodiacSign.SCORPIO, "天蠍座", "♏", "10/23–11/21", "水", "固定",
        ("loyal_guardian", "introspective_conflict", "calm_analyst"),
    ),
    ZodiacSign.SAGITTARIUS: ZodiacProfile(
        ZodiacSign.SAGITTARIUS, "射手座", "♐", "11/22–12/21", "火", "變動",
        ("impulsive_adventurer", "action_taker", "enthusiastic_leader"),
    ),
    ZodiacSign.CAPRICORN: ZodiacProfile(
        ZodiacSign.CAPRICORN, "摩羯座", "♑", "12/22–1/19", "土", "開創",
        ("strategic_planner", "calm_analyst", "loyal_guardian"),
    ),
    ZodiacSign.AQUARIUS: ZodiacProfile(
        ZodiacSign.AQUARIUS, "水瓶座", "♒", "1/20–2/18", "風", "固定",
        ("systems_thinker", "rational_observer", "sensitive_creator"),
    ),
    ZodiacSign.PISCES: ZodiacProfile(
        ZodiacSign.PISCES, "雙魚座", "♓", "2/19–3/20", "水", "變動",
        ("emotional_empath", "sensitive_creator", "compassionate_supporter"),
    ),
}

ELEMENT_TRAITS = {
    "火": ("enthusiastic_leader", "action_taker"),
    "土": ("strategic_planner", "loyal_guardian"),
    "風": ("social_charmer", "rational_observer"),
    "水": ("emotional_empath", "gentle_caregiver"),
}

MODALITY_TRAITS = {
    "開創": ("action_taker", "enthusiastic_leader"),
    "固定": ("loyal_guardian", "strategic_planner"),
    "變動": ("observant_personality", "impulsive_adventurer"),
}

TIME_BRANCH_RULES = {
    "子": ("水", "emotional_empath", ("水", "冰")),
    "丑": ("土", "strategic_planner", ("地面", "岩石")),
    "寅": ("木", "impulsive_adventurer", ("草", "飛行")),
    "卯": ("木", "gentle_caregiver", ("草", "妖精")),
    "辰": ("土", "systems_thinker", ("地面", "龍")),
    "巳": ("火", "action_taker", ("火", "格鬥")),
    "午": ("火", "enthusiastic_leader", ("火", "電")),
    "未": ("土", "compassionate_supporter", ("地面", "草")),
    "申": ("金", "rational_observer", ("鋼", "電")),
    "酉": ("金", "observant_personality", ("鋼", "飛行")),
    "戌": ("土", "loyal_guardian", ("岩石", "地面")),
    "亥": ("水", "sensitive_creator", ("水", "超能力")),
}

LUNAR_PHASE_RULES = {
    "月初": "action_taker",
    "漸盈": "strategic_planner",
    "望月前後": "emotional_empath",
    "漸虧": "introspective_conflict",
}

SEASON_RULES = {
    "春": ("木", "sensitive_creator"),
    "夏": ("火", "enthusiastic_leader"),
    "秋": ("金", "calm_analyst"),
    "冬": ("水", "solitary_thinker"),
}

SPRING_TERMS = frozenset(("立春", "雨水", "驚蟄", "春分", "清明", "穀雨"))
SUMMER_TERMS = frozenset(("立夏", "小滿", "芒種", "夏至", "小暑", "大暑"))
AUTUMN_TERMS = frozenset(("立秋", "處暑", "白露", "秋分", "寒露", "霜降"))
WINTER_TERMS = frozenset(("立冬", "小雪", "大雪", "冬至", "小寒", "大寒"))

FACET_TRAITS = {
    "work_study": frozenset(
        ("action_taker", "calm_analyst", "strategic_planner", "rational_observer", "systems_thinker")
    ),
    "relationships": frozenset(
        ("social_charmer", "gentle_caregiver", "emotional_empath", "loyal_guardian", "compassionate_supporter")
    ),
    "vitality": frozenset(
        ("enthusiastic_leader", "impulsive_adventurer", "action_taker", "sensitive_creator")
    ),
}

ACTION_TEMPLATES = {
    "overall": "今天適合先選定一件最在意的事，和你的代表寶可夢一起穩穩推進。",
    "work_study": "把最重要的工作或學習任務排在前面，先完成一個清楚的小目標。",
    "relationships": "主動向在意的人傳達一句關心，真誠比華麗的說法更有力量。",
    "vitality": "安排一段能活動身體或轉換環境的時間，替今天補充新的節奏。",
}

REMINDER_TEMPLATES = {
    "overall": "不用要求每件事同時到位，保留調整空間也算是前進。",
    "work_study": "別把行程排得太滿，卡住時先拆小步驟再繼續。",
    "relationships": "回應之前先確認彼此真正的意思，能少掉不必要的誤會。",
    "vitality": "留意休息與補水，感到疲累時不必勉強維持原本速度。",
}


def season_for_solar_term(term: str) -> str:
    if term in SPRING_TERMS:
        return "春"
    if term in SUMMER_TERMS:
        return "夏"
    if term in AUTUMN_TERMS:
        return "秋"
    if term in WINTER_TERMS:
        return "冬"
    raise ValueError(f"unsupported solar term: {term}")


def validate_today_pokemon_rules(active_trait_codes: set[str] | frozenset[str]) -> None:
    if set(ZODIAC_PROFILES) != set(ZodiacSign):
        raise RuntimeError("today Pokémon rules must define all twelve zodiac signs")
    configured = set(TRAIT_LABELS)
    referenced: set[str] = set()
    for profile in ZODIAC_PROFILES.values():
        referenced.update(profile.trait_codes)
    for values in ELEMENT_TRAITS.values():
        referenced.update(values)
    for values in MODALITY_TRAITS.values():
        referenced.update(values)
    referenced.update(value[1] for value in TIME_BRANCH_RULES.values())
    referenced.update(LUNAR_PHASE_RULES.values())
    referenced.update(value[1] for value in SEASON_RULES.values())
    referenced.update(*(set(values) for values in FACET_TRAITS.values()))
    if referenced - configured:
        raise RuntimeError("today Pokémon rules reference unknown personality traits")
    missing = configured - set(active_trait_codes)
    if missing:
        raise RuntimeError(
            "today Pokémon rules require active personality traits: "
            + ", ".join(sorted(missing))
        )

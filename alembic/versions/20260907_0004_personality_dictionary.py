"""Store personality traits and searchable synonyms in PostgreSQL.

Revision ID: 20260907_0004
Revises: 20260906_0003
Create Date: 2026-09-07
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260907_0004"
down_revision: str | None = "20260906_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TRAITS = (
    ("enthusiastic_leader", "熱情領導者", 0),
    ("impulsive_adventurer", "衝動冒險者", 1),
    ("social_charmer", "社交魅力型", 2),
    ("action_taker", "行動派", 3),
    ("calm_analyst", "冷靜分析師", 4),
    ("strategic_planner", "策略規劃者", 5),
    ("rational_observer", "理性觀察者", 6),
    ("systems_thinker", "系統思考者", 7),
    ("gentle_caregiver", "溫柔照顧者", 8),
    ("emotional_empath", "情感共鳴者", 9),
    ("loyal_guardian", "忠誠守護者", 10),
    ("compassionate_supporter", "同理心強者", 11),
    ("solitary_thinker", "孤獨思考者", 12),
    ("introspective_conflict", "矛盾內省者", 13),
    ("sensitive_creator", "敏感創作者", 14),
    ("observant_personality", "觀察型人格", 15),
)

SYNONYMS = {
    "enthusiastic_leader": (
        "領導", "主動", "自信", "帶領", "掌控", "熱血", "號召", "鼓舞",
        "熱情", "有主見", "leader", "confident", "proactive", "passionate",
    ),
    "impulsive_adventurer": (
        "衝動", "冒險", "刺激", "勇敢", "不怕", "挑戰", "探索", "大膽",
        "嘗試新事物", "追求自由", "adventure", "brave", "challenge", "daring",
    ),
    "social_charmer": (
        "社交", "外向", "聊天", "分享", "交流", "人氣", "吸引", "人群",
        "朋友", "聚會", "健談", "social", "chat", "popular", "outgoing", "share",
    ),
    "action_taker": (
        "行動", "快速", "執行", "效率", "做事", "立即", "運動", "實作",
        "說做就做", "動手", "果斷", "action", "fast", "efficient", "execute",
    ),
    "calm_analyst": (
        "冷靜", "理性", "分析", "思考", "邏輯", "判斷", "沉著", "客觀分析",
        "解決問題", "calm", "logical", "analysis", "analytical",
    ),
    "strategic_planner": (
        "計畫", "策略", "規劃", "安排", "設計", "佈局", "未雨綢繆",
        "深思熟慮", "有條理", "按部就班", "plan", "strategy", "design", "organized",
    ),
    "rational_observer": (
        "觀察", "客觀", "理解", "看清", "判斷", "研究", "細節", "察覺",
        "求證", "observe", "objective", "research", "detail",
    ),
    "systems_thinker": (
        "系統", "結構", "整體", "流程", "架構", "模型", "程式", "組織",
        "拆解問題", "規則", "system", "structure", "programming", "process",
    ),
    "gentle_caregiver": (
        "溫柔", "照顧", "體貼", "關心", "保護", "善良", "陪伴", "細心",
        "默默支持", "替人著想", "gentle", "care", "kind", "caring",
    ),
    "emotional_empath": (
        "共感", "情緒", "感受", "同理", "理解別人", "敏感", "情感",
        "感同身受", "察言觀色", "emotion", "empathy", "sensitive", "feeling",
    ),
    "loyal_guardian": (
        "忠誠", "承諾", "守護", "保護", "堅持", "可靠", "信任", "責任感",
        "守信用", "不離不棄", "loyal", "protect", "trust", "commitment", "reliable",
    ),
    "compassionate_supporter": (
        "同理", "理解", "包容", "接受", "寬容", "支持", "傾聽", "尊重",
        "陪伴", "願意幫忙", "幫助別人", "empathy", "support", "accept", "tolerant", "listen",
    ),
    "solitary_thinker": (
        "孤獨", "獨處", "安靜", "沉思", "內向", "慢熟", "一個人", "個人空間",
        "獨立", "不善言辭", "需要時間熟悉", "需要自己的空間", "alone", "quiet",
        "introvert", "reserved",
    ),
    "introspective_conflict": (
        "矛盾", "糾結", "內心", "掙扎", "思考自己", "自我懷疑", "反省",
        "內省", "想很多", "容易猶豫", "conflict", "struggle", "introspective", "self-doubt",
    ),
    "sensitive_creator": (
        "敏感", "創作", "想像", "靈感", "藝術", "情緒化", "畫畫", "音樂",
        "美感", "寫作", "創意", "浪漫", "creative", "art", "music", "imagination",
    ),
    "observant_personality": (
        "觀察", "安靜", "看著", "記錄", "理解世界", "旁觀", "細心觀察",
        "先觀察再行動", "留意", "observe", "record", "watch", "observant",
    ),
}


def upgrade() -> None:
    op.create_table(
        "personality_traits",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name_zh", sa.String(length=40), nullable=False),
        sa.Column("vector_index", sa.SmallInteger(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint(
            "length(trim(code)) > 0",
            name="ck_personality_traits_code_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(name_zh)) > 0",
            name="ck_personality_traits_name_zh_not_blank",
        ),
        sa.CheckConstraint(
            "vector_index BETWEEN 0 AND 15",
            name="ck_personality_traits_vector_index_range",
        ),
        sa.PrimaryKeyConstraint("code", name="pk_personality_traits"),
        sa.UniqueConstraint("name_zh", name="uq_personality_traits_name_zh"),
        sa.UniqueConstraint("vector_index", name="uq_personality_traits_vector_index"),
    )
    op.create_table(
        "personality_trait_synonyms",
        sa.Column("trait_code", sa.String(length=40), nullable=False),
        sa.Column("term", sa.String(length=80), nullable=False),
        sa.Column(
            "language_code",
            sa.String(length=10),
            server_default=sa.text("'zh-Hant'"),
            nullable=False,
        ),
        sa.Column(
            "weight",
            sa.Double(),
            server_default=sa.text("2.0"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.CheckConstraint(
            "length(trim(term)) > 0",
            name="ck_personality_trait_synonyms_term_not_blank",
        ),
        sa.CheckConstraint(
            "length(trim(language_code)) > 0",
            name="ck_personality_trait_synonyms_language_code_not_blank",
        ),
        sa.CheckConstraint(
            "weight > 0 AND weight <= 5",
            name="ck_personality_trait_synonyms_weight_range",
        ),
        sa.ForeignKeyConstraint(
            ["trait_code"],
            ["personality_traits.code"],
            name="fk_personality_synonym_trait",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "trait_code",
            "term",
            name="pk_personality_trait_synonyms",
        ),
    )
    op.create_index(
        "ix_personality_synonyms_active_term",
        "personality_trait_synonyms",
        ["is_active", "term"],
        unique=False,
    )

    trait_table = sa.table(
        "personality_traits",
        sa.column("code", sa.String()),
        sa.column("name_zh", sa.String()),
        sa.column("vector_index", sa.SmallInteger()),
        sa.column("is_active", sa.Boolean()),
    )
    synonym_table = sa.table(
        "personality_trait_synonyms",
        sa.column("trait_code", sa.String()),
        sa.column("term", sa.String()),
        sa.column("language_code", sa.String()),
        sa.column("weight", sa.Double()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        trait_table,
        [
            {
                "code": code,
                "name_zh": name_zh,
                "vector_index": vector_index,
                "is_active": True,
            }
            for code, name_zh, vector_index in TRAITS
        ],
    )
    op.bulk_insert(
        synonym_table,
        [
            {
                "trait_code": trait_code,
                "term": term,
                "language_code": "en" if term.isascii() else "zh-Hant",
                "weight": 2.0,
                "is_active": True,
            }
            for trait_code, terms in SYNONYMS.items()
            for term in terms
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_personality_synonyms_active_term",
        table_name="personality_trait_synonyms",
    )
    op.drop_table("personality_trait_synonyms")
    op.drop_table("personality_traits")

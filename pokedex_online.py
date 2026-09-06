# =====================
# 📦 匯入套件
# =====================

import os  # 用來處理檔案路徑與讀取環境變數，避免路徑寫死
from typing import Dict, List, Any  # 用來標註函式輸入/輸出型態，讓程式更好讀

import jieba  # 中文斷詞：把中文句子拆成詞，讓人格關鍵字比對更準
import numpy as np  # 向量與數學運算：人格向量、正規化、分數計算
import pandas as pd  # 讀取 pokedex_final.csv，並用 DataFrame 管理寶可夢資料
from dotenv import load_dotenv  # 載入 .env 裡面的 OPENAI_API_KEY、HF_TOKEN 等設定
from openai import OpenAI  # OpenAI Responses API：用來產生自然語言 AI 分析
from sentence_transformers import SentenceTransformer  # 將文字轉成語意向量 embedding
from sklearn.metrics.pairwise import cosine_similarity  # 計算使用者文字與寶可夢資料的相似度


# =====================
# 📂 路徑設定
# =====================

load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def resolve_csv_path() -> str:
    """
    函式用途：
    自動尋找 pokedex_final.csv 的位置，避免你換電腦或資料夾後路徑爆掉。

    尋找順序：
    1. .env 或系統環境變數 POKEDEX_CSV_PATH
    2. 與此 py 檔同層的 pokedex_final.csv
    3. pokemon_descript/pokedex_final.csv
    4. 舊版 pokemon_descript/pokedex.csv
    """

    candidates = [
        os.getenv("POKEDEX_CSV_PATH"),
        os.path.join(BASE_DIR, "pokedex_final.csv"),
        os.path.join(BASE_DIR, "pokemon_descript", "pokedex_final.csv"),
        os.path.join(BASE_DIR, "pokemon_descript", "pokedex.csv"),
    ]

    for path in candidates:
        if path and os.path.exists(path):
            return path

    raise FileNotFoundError(
        "❌ 找不到 pokedex_final.csv，請放在程式同層或 pokemon_descript 資料夾內。"
    )


FILE_PATH = resolve_csv_path()

# ✅ 重點更新：
# 你現在要比對「中文習性 + 英文習性」，所以建議用多語模型。
# 原本 all-MiniLM-L6-v2 偏英文，中文語意效果比較不穩。
# 這個模型支援中文與英文，適合你的中英混合 final.csv。
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
HF_TOKEN = os.getenv("HF_TOKEN") or None
API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_ID = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
client = OpenAI(api_key=API_KEY) if API_KEY else None


# =====================
# 🧠 16 型人格維度
# =====================

TRAITS = [
    "熱情領導者", "衝動冒險者", "社交魅力型", "行動派",
    "冷靜分析師", "策略規劃者", "理性觀察者", "系統思考者",
    "溫柔照顧者", "情感共鳴者", "忠誠守護者", "同理心強者",
    "孤獨思考者", "矛盾內省者", "敏感創作者", "觀察型人格",
]


# =====================
# 🧬 寶可夢屬性 → 人格權重
# =====================

TYPE_MAP = {
    "火": [1.8, 2.4, 2.0, 2.5, 0.5, 0.6, 0.4, 1.0, 0.6, 0.5, 0.6, 0.7, 1.2, 0.8, 1.5, 0.6],
    "水": [0.6, 0.5, 0.4, 0.5, 1.2, 1.5, 1.8, 0.8, 2.5, 2.6, 2.0, 1.2, 0.7, 0.8, 1.1, 0.9],
    "草": [1.4, 1.0, 0.8, 0.9, 0.7, 1.0, 2.2, 2.0, 2.6, 2.4, 2.0, 1.1, 0.9, 1.2, 1.3, 0.8],
    "電": [2.5, 2.6, 2.4, 2.0, 1.0, 0.9, 0.7, 1.2, 0.5, 0.6, 0.8, 0.9, 1.8, 1.3, 1.9, 1.0],
    "冰": [0.5, 0.6, 0.4, 0.5, 2.0, 2.4, 2.6, 1.2, 1.0, 0.8, 1.0, 1.3, 1.5, 1.4, 1.2, 1.0],
    "格鬥": [0.8, 1.2, 2.5, 2.8, 0.6, 0.7, 0.5, 1.0, 0.7, 0.6, 0.9, 1.2, 1.0, 0.8, 0.7, 0.6],
    "毒": [0.5, 0.6, 0.7, 0.8, 1.4, 1.6, 2.0, 1.1, 1.0, 0.9, 1.0, 1.3, 2.4, 2.2, 1.1, 1.0],
    "地面": [0.7, 0.8, 0.9, 2.2, 1.5, 1.4, 1.0, 0.9, 1.2, 1.0, 1.6, 2.5, 0.8, 0.7, 0.9, 1.1],
    "飛行": [2.2, 2.4, 2.0, 1.8, 1.2, 1.0, 0.9, 1.5, 1.0, 1.1, 1.3, 1.2, 0.9, 0.8, 2.6, 1.0],
    "超能力": [1.5, 1.6, 1.2, 1.0, 2.6, 2.5, 1.8, 2.4, 1.1, 1.2, 1.3, 2.5, 1.4, 2.0, 2.6, 1.5],
    "蟲": [1.0, 1.1, 0.9, 0.8, 1.2, 1.3, 1.5, 2.0, 1.4, 1.6, 1.8, 1.2, 0.9, 1.1, 2.2, 1.3],
    "岩石": [0.6, 0.7, 0.8, 2.0, 1.4, 1.6, 1.2, 0.9, 1.1, 1.0, 1.5, 2.6, 0.8, 0.9, 1.0, 1.1],
    "幽靈": [0.5, 0.6, 0.7, 0.8, 2.2, 2.6, 2.4, 1.5, 1.0, 0.9, 1.1, 1.3, 2.6, 2.8, 1.4, 1.2],
    "龍": [2.0, 2.2, 2.5, 2.8, 1.5, 1.6, 1.2, 2.0, 1.4, 1.2, 2.0, 2.6, 1.5, 1.8, 2.2, 1.3],
    "惡": [0.6, 0.8, 2.6, 2.8, 1.2, 1.4, 1.0, 0.9, 1.0, 0.8, 1.1, 1.5, 2.6, 2.8, 1.2, 1.1],
    "鋼": [0.5, 0.6, 0.7, 2.5, 1.8, 2.0, 1.5, 1.0, 1.2, 1.1, 2.6, 2.8, 1.0, 1.1, 1.3, 1.2],
    "妖精": [2.6, 2.4, 1.8, 1.5, 1.0, 1.2, 2.6, 2.8, 2.5, 2.6, 2.0, 1.5, 1.4, 1.6, 1.8, 1.2],
    "一般": [1.2, 1.0, 1.0, 1.2, 1.0, 1.0, 1.0, 1.0, 1.2, 1.1, 1.3, 1.2, 1.0, 1.0, 1.0, 1.0],
}

EN_TYPE_TO_ZH = {
    "Normal": "一般", "Fire": "火", "Water": "水", "Grass": "草", "Electric": "電",
    "Ice": "冰", "Fighting": "格鬥", "Poison": "毒", "Ground": "地面", "Flying": "飛行",
    "Psychic": "超能力", "Bug": "蟲", "Rock": "岩石", "Ghost": "幽靈", "Dragon": "龍",
    "Dark": "惡", "Steel": "鋼", "Fairy": "妖精",
}


# =====================
# 🧠 使用者文字關鍵字 → 人格向量
# =====================

EMOTION_KEYWORDS = {
    "熱情領導者": ["領導", "主動", "自信", "帶領", "掌控", "熱血", "leader", "confident", "active"],
    "衝動冒險者": ["衝動", "冒險", "刺激", "勇敢", "不怕", "挑戰", "adventure", "brave", "challenge"],
    "社交魅力型": ["社交", "外向", "聊天", "人氣", "吸引", "人群", "朋友", "social", "chat", "popular"],
    "行動派": ["行動", "快速", "執行", "效率", "做事", "立即", "運動", "action", "fast", "efficient"],
    "冷靜分析師": ["冷靜", "理性", "分析", "思考", "邏輯", "判斷", "calm", "logical", "analysis"],
    "策略規劃者": ["計畫", "策略", "規劃", "安排", "設計", "佈局", "plan", "strategy", "design"],
    "理性觀察者": ["觀察", "客觀", "理解", "看清", "判斷", "研究", "observe", "objective", "research"],
    "系統思考者": ["系統", "結構", "整體", "流程", "架構", "模型", "程式", "system", "structure", "programming"],
    "溫柔照顧者": ["溫柔", "照顧", "體貼", "關心", "保護", "善良", "gentle", "care", "kind"],
    "情感共鳴者": ["共感", "情緒", "感受", "同理", "理解別人", "敏感", "emotion", "empathy", "sensitive"],
    "忠誠守護者": ["忠誠", "守護", "保護", "堅持", "可靠", "信任", "loyal", "protect", "trust"],
    "同理心強者": ["同理", "理解", "包容", "接受", "寬容", "支持", "empathy", "support", "accept"],
    "孤獨思考者": ["孤獨", "獨處", "安靜", "沉思", "內向", "一個人", "睡覺", "alone", "quiet", "introvert"],
    "矛盾內省者": ["矛盾", "糾結", "內心", "掙扎", "思考自己", "自我懷疑", "conflict", "struggle", "introspective"],
    "敏感創作者": ["敏感", "創作", "想像", "靈感", "藝術", "情緒化", "畫畫", "音樂", "creative", "art", "music"],
    "觀察型人格": ["觀察", "安靜", "看著", "記錄", "理解世界", "旁觀", "observe", "record", "watch"],
}


class PokemonRecommender:
    """
    類別用途：
    建立線上版寶可夢人格推薦系統。

    核心流程：
    1. 讀取 pokedex_final.csv
    2. 用 type_zh / type_1 / type_2 建立屬性人格向量
    3. 用中文習性 + 英文習性建立語意 embedding
    4. 使用者輸入後，比對人格相似度 + 語意相似度
    5. 回傳最符合的寶可夢
    """

    def __init__(self, path: str = FILE_PATH, dataframe: pd.DataFrame | None = None):
        """
        函式用途：
        初始化推薦系統，只在程式啟動時跑一次。
        """

        if dataframe is None:
            print("🚀 載入寶可夢資料：", path)
            self.df = pd.read_csv(path, encoding="utf-8").fillna("")
        else:
            print("🚀 從 PostgreSQL 載入寶可夢資料")
            self.df = dataframe.copy().fillna("")

        # 新版 pokedex_final.csv 欄位名稱
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

        print("🧠 載入語意模型：", EMBEDDING_MODEL)
        self.st_model = self._load_sentence_model()

        print("🧬 建立寶可夢人格向量...")
        self.persona_vectors = self.build_persona_vectors()

        print("⚡ 建立寶可夢中英語意向量...")
        self.pokemon_embeddings = self.build_embeddings()

        print("✅ 推薦系統準備完成！")

    def _validate_columns(self) -> None:
        """
        函式用途：
        檢查新版 CSV 是否有程式需要的欄位。
        """

        required_cols = [
            self.id_col, self.name_col, self.name_en_col, self.type_col,
            self.cat_col, self.desc_col, self.analysis_col, self.img_col,
        ]
        missing = [col for col in required_cols if col not in self.df.columns]
        if missing:
            raise ValueError(f"❌ pokedex_final.csv 缺少欄位：{missing}")

    def _load_sentence_model(self) -> SentenceTransformer:
        """
        函式用途：
        載入 SentenceTransformer embedding 模型。
        如果你有 HF_TOKEN，就用 token；沒有也可以跑公開模型。
        """

        try:
            return SentenceTransformer(EMBEDDING_MODEL, token=HF_TOKEN)
        except TypeError:
            return SentenceTransformer(EMBEDDING_MODEL, use_auth_token=HF_TOKEN)

    def safe_get(self, row: pd.Series, col: str, default: str = "") -> Any:
        """
        函式用途：
        安全取得欄位資料。
        如果 CSV 沒有某個欄位，就回傳空字串，避免程式爆掉。
        """

        return row.get(col, default) if col in row.index else default

    def tokenize(self, text: str) -> List[str]:
        """
        函式用途：
        將中文句子斷詞，讓關鍵字比對更準。
        """

        return jieba.lcut(str(text))

    def normalize_vec(self, vec: np.ndarray) -> np.ndarray:
        """
        函式用途：
        將向量正規化，避免數值太大影響比較。
        """

        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    def parse_types(self, row: pd.Series) -> List[str]:
        """
        函式用途：
        從新版 CSV 取得寶可夢屬性。

        優先使用：type_zh，例如：草, 毒
        備用使用：type_1 / type_2，例如：Grass / Poison
        """

        types: List[str] = []

        type_zh = str(self.safe_get(row, self.type_col, "")).replace("，", ",")
        for t in type_zh.split(","):
            t = t.strip()
            if t:
                types.append(t)

        if not types:
            for col in [self.type_1_col, self.type_2_col]:
                en_type = str(self.safe_get(row, col, "")).strip()
                zh_type = EN_TYPE_TO_ZH.get(en_type)
                if zh_type:
                    types.append(zh_type)

        return types

    def text_to_persona_vector(self, text: str) -> np.ndarray:
        """
        函式用途：
        把使用者輸入或寶可夢描述轉成 16 維人格向量。

        注意：
        這裡主要是規則關鍵字比對。
        真正的中英語意比對是在 build_embeddings() 與 recommend() 裡完成。
        """

        text = str(text)
        vec = np.zeros(len(TRAITS))
        words = set(self.tokenize(text))
        lower_text = text.lower()

        for i, trait in enumerate(TRAITS):
            for keyword in EMOTION_KEYWORDS[trait]:
                kw = keyword.lower()
                if keyword in text or keyword in words or kw in lower_text:
                    vec[i] += 2.0

        return self.normalize_vec(vec)

    def build_persona_vectors(self) -> np.ndarray:
        """
        函式用途：
        替每一隻寶可夢建立人格向量。

        向量來源：
        1. type_zh 屬性權重
        2. 中文描述 description_zh
        3. 英文 flavor_text_en
        4. 中英整合習性 analysis_text
        """

        vectors = []

        for _, row in self.df.iterrows():
            vec = np.zeros(len(TRAITS))

            for poke_type in self.parse_types(row):
                if poke_type in TYPE_MAP:
                    vec += np.array(TYPE_MAP[poke_type], dtype=float)

            persona_text = " ".join([
                str(self.safe_get(row, self.cat_col, "")),
                str(self.safe_get(row, self.genus_col, "")),
                str(self.safe_get(row, self.desc_col, "")),
                str(self.safe_get(row, self.flavor_en_col, "")),
                str(self.safe_get(row, self.analysis_col, "")),
            ])
            vec += self.text_to_persona_vector(persona_text)

            vectors.append(self.normalize_vec(vec))

        return np.array(vectors)

    def build_search_text(self, row: pd.Series) -> str:
        """
        函式用途：
        組合給 embedding 使用的文字。

        ✅ 這是本次最重要的修改：
        語意比對不只看中文，現在會同時看：
        1. 中文名稱 name_zh
        2. 英文名稱 name_en
        3. 中文屬性 type_zh
        4. 英文屬性 type_1 / type_2
        5. 中文分類 category_zh
        6. 英文分類 genus
        7. 中文習性/介紹 description_zh
        8. 英文習性/介紹 flavor_text_en
        9. 中英整合分析 analysis_text
        10. 英文能力、棲地、顏色、外型等欄位
        """

        # 用標籤寫清楚欄位意思，embedding 比較容易理解語意。
        parts = [
            f"中文名稱: {self.safe_get(row, self.name_col)}",
            f"English name: {self.safe_get(row, self.name_en_col)}",
            f"中文屬性: {self.safe_get(row, self.type_col)}",
            f"English types: {self.safe_get(row, self.type_1_col)} {self.safe_get(row, self.type_2_col)}",
            f"中文分類: {self.safe_get(row, self.cat_col)}",
            f"English genus: {self.safe_get(row, self.genus_col)}",
            f"中文習性與圖鑑描述: {self.safe_get(row, self.desc_col)}",
            f"English behavior and flavor text: {self.safe_get(row, self.flavor_en_col)}",
            f"中英整合習性分析: {self.safe_get(row, self.analysis_col)}",
            f"Abilities: {self.safe_get(row, 'abilities')}",
            f"Hidden ability: {self.safe_get(row, 'hidden_ability')}",
            f"Habitat: {self.safe_get(row, 'habitat')}",
            f"Color: {self.safe_get(row, 'color')}",
            f"Shape: {self.safe_get(row, 'shape')}",
            f"Egg groups: {self.safe_get(row, 'egg_groups')}",
        ]

        return "\n".join(str(p) for p in parts if str(p).strip())

    def build_embeddings(self) -> np.ndarray:
        """
        函式用途：
        把每隻寶可夢的「中文習性 + 英文習性」轉成語意向量。

        後續 recommend() 會把使用者輸入也轉成向量，
        再用 cosine_similarity 找出最相似的寶可夢。
        """

        texts = [self.build_search_text(row) for _, row in self.df.iterrows()]
        return self.st_model.encode(texts, normalize_embeddings=True)

    def get_top_traits(self, vec: np.ndarray, top_n: int = 3) -> List[str]:
        """
        函式用途：
        取得向量分數最高的前幾個人格特質，用於 debug 或解釋。
        """

        idxs = np.argsort(-vec)[:top_n]
        return [TRAITS[i] for i in idxs if vec[i] > 0]

    def build_matching_evidence(self, row: pd.Series, pokemon_traits: List[str]) -> List[Dict]:
        """建立可直接顯示、且能追溯到 CSV 來源欄位的匹配證據。"""

        evidence: List[Dict] = []
        for source, column in [
            ("analysis_text", self.analysis_col),
            ("description_zh", self.desc_col),
            ("flavor_text_en", self.flavor_en_col),
        ]:
            content = str(self.safe_get(row, column, "")).strip()
            if not content:
                continue
            evidence.append({
                "source": source,
                "text": content[:240],
                "matched_traits": pokemon_traits,
            })
            if len(evidence) == 2:
                break
        return evidence

    def recommend(self, user_text: str, top_k: int = 3) -> List[Dict]:
        """
        函式用途：
        根據使用者輸入，推薦最符合的寶可夢。

        分數來源：
        1. 人格向量相似度 persona_sims
        2. 中英語意相似度 semantic_sims
        3. 最後混合成 final_sims
        """

        user_text = str(user_text).strip()
        if not user_text:
            raise ValueError("❌ 使用者輸入不可為空。")

        # 使用者文字 → 人格向量
        user_persona_vec = self.text_to_persona_vector(user_text)
        persona_sims = cosine_similarity([user_persona_vec], self.persona_vectors)[0]

        # 使用者文字 → 語意向量
        # 因為模型是多語模型，所以使用者輸入中文或英文都可以跟中英寶可夢資料比對。
        user_embedding = self.st_model.encode(user_text, normalize_embeddings=True)
        semantic_sims = cosine_similarity([user_embedding], self.pokemon_embeddings)[0]

        # 如果使用者文字有明顯人格關鍵字，就提高人格分數權重。
        # 如果沒有明顯關鍵字，就讓語意搜尋佔比較高。
        alpha = min(0.8, 0.35 + np.linalg.norm(user_persona_vec) * 0.35)
        final_sims = alpha * persona_sims + (1 - alpha) * semantic_sims

        if not 1 <= top_k <= 10:
            raise ValueError("❌ top_k 必須介於 1 到 10。")

        # 使用穩定排序確保相同輸入可重現；資料列索引作為同分時的固定順序。
        ranked_indexes = np.argsort(-final_sims, kind="stable")[:top_k]
        results: List[Dict] = []
        seen_pokedex_numbers = set()

        for idx in ranked_indexes:
            row = self.df.iloc[int(idx)]
            pokedex_number = (
                int(row[self.id_col])
                if str(row[self.id_col]).isdigit()
                else row[self.id_col]
            )
            if pokedex_number in seen_pokedex_numbers:
                continue
            seen_pokedex_numbers.add(pokedex_number)
            semantic_score = float(np.clip(semantic_sims[idx], 0, 1))
            personality_score = float(np.clip(persona_sims[idx], 0, 1))
            total_score = float(np.clip(final_sims[idx], 0, 1))
            pokemon_traits = self.get_top_traits(self.persona_vectors[idx])
            score_percent = total_score * 100

            results.append({
            "rank": len(results) + 1,
            "pokedex_number": pokedex_number,
            "name": self.safe_get(row, self.name_col),
            "name_en": self.safe_get(row, self.name_en_col),
            "type": self.safe_get(row, self.type_col),
            "type_en": ", ".join([str(self.safe_get(row, self.type_1_col)), str(self.safe_get(row, self.type_2_col))]).strip(", "),
            "category": self.safe_get(row, self.cat_col),
            "genus": self.safe_get(row, self.genus_col),
            "desc": self.safe_get(row, self.desc_col),
            "flavor_text_en": self.safe_get(row, self.flavor_en_col),
            "analysis_text": self.safe_get(row, self.analysis_col),
            "search_text": self.build_search_text(row),
            "img": self.safe_get(row, self.img_col) or self.safe_get(row, self.sprite_col),
            "sprite": self.safe_get(row, self.sprite_col),
            "scores": {
                "semantic": semantic_score,
                "personality": personality_score,
                "total": total_score,
            },
            "matching_evidence": self.build_matching_evidence(row, pokemon_traits),
            "score": score_percent,
            "score_ratio": score_percent / 100,
            "user_traits": self.get_top_traits(user_persona_vec),
            "pokemon_traits": pokemon_traits,
            "stats": {
                "hp": self.safe_get(row, "hp"),
                "attack": self.safe_get(row, "attack"),
                "defense": self.safe_get(row, "defense"),
                "sp_attack": self.safe_get(row, "sp_attack"),
                "sp_defense": self.safe_get(row, "sp_defense"),
                "speed": self.safe_get(row, "speed"),
                "base_stat_total": self.safe_get(row, "base_stat_total"),
            },
            })

        return results

    def explain_offline(self, user_text: str, pokemon: Dict) -> str:
        """
        函式用途：
        沒有 OpenAI API Key 或 OpenAI 暫時失敗時，使用的備用解釋。
        """

        user_traits = "、".join(pokemon.get("user_traits", [])) or "語意特徵"
        poke_traits = "、".join(pokemon.get("pokemon_traits", [])) or "圖鑑特徵"

        return (
            f"你輸入的內容偏向「{user_traits}」，系統同時比對中文習性與英文習性後，"
            f"發現 {pokemon['name']} / {pokemon['name_en']} 的屬性、分類、圖鑑描述與「{poke_traits}」特徵最接近，"
            f"因此推薦牠作為最符合你的寶可夢。"
        )

    def explain(self, user_text: str, pokemon: Dict) -> str:
        """
        函式用途：
        呼叫 OpenAI Responses API 產生 60～80 字自然解釋。

        ✅ 這次也更新 prompt：
        讓 OpenAI 模型同時看到中文習性與英文習性，
        避免它只根據中文描述或只根據寶可夢名稱亂猜。
        """

        if client is None:
            return self.explain_offline(user_text, pokemon)

        prompt = f"""
你是一位寶可夢人格分析師。

使用者輸入：{user_text}

推薦寶可夢：{pokemon['name']} / {pokemon['name_en']}
中文屬性：{pokemon['type']}
英文屬性：{pokemon['type_en']}
中文分類：{pokemon['category']}
英文分類：{pokemon['genus']}

使用者人格特徵：{', '.join(pokemon.get('user_traits', []))}
寶可夢人格特徵：{', '.join(pokemon.get('pokemon_traits', []))}

中文習性與圖鑑描述：
{pokemon['desc'][:600]}

英文習性與 flavor text：
{pokemon['flavor_text_en'][:600]}

中英整合習性分析：
{pokemon['analysis_text'][:900]}

請用繁體中文 60～80 字自然說明，
為什麼這隻寶可夢適合代表這位使用者。
不要亂編不存在的設定，理由要根據中文習性、英文習性、屬性、分類與人格特徵。
"""

        try:
            response = client.responses.create(
                model=MODEL_ID,
                instructions=(
                    "你是寶可夢人格推薦解釋器。只能根據提供的寶可夢資料說明，"
                    "不可補充未提供的設定，也不要把相似分數描述成心理診斷或統計機率。"
                ),
                input=prompt,
                max_output_tokens=250,
                store=False,
            )
            explanation = response.output_text.strip()
            if not explanation:
                raise RuntimeError("OpenAI API 未回傳文字內容。")
            return explanation
        except Exception as e:
            return f"{self.explain_offline(user_text, pokemon)}\n\n⚠️ OpenAI 解釋暫時失敗：{e}"


def main() -> None:
    """
    函式用途：
    讓這個檔案可以直接在終端機測試。
    """

    engine = PokemonRecommender(FILE_PATH)

    while True:
        text = input("\n請輸入你的個性描述（exit 離開）：\n> ").strip()
        if text.lower() == "exit":
            break

        results = engine.recommend(text, top_k=3)

        print("\n========================")
        print("✨ Top 3 分析結果 ✨")
        print("========================")
        for result in results:
            explanation = engine.explain(text, result)
            print(f"\n第 {result['rank']} 名：#{result['pokedex_number']} {result['name']} / {result['name_en']}")
            print(f"屬性：{result['type']} / {result['type_en']}")
            print(f"分類：{result['category']} / {result['genus']}")
            print(f"契合度：{result['score']:.2f}%")
            print(f"圖片：{result['img']}")
            print(f"AI 分析：{explanation}")


if __name__ == "__main__":
    main()

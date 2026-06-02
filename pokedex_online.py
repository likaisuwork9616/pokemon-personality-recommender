# =====================
# 📦 匯入模組
# =====================

import pandas as pd  # 👉 用來讀取 CSV（寶可夢資料）
import numpy as np   # 👉 向量運算（人格向量 / 相似度）
import os            # 👉 處理檔案路徑
import jieba         # 👉 中文斷詞（讓關鍵字比對更準確）

from dotenv import load_dotenv  # 👉 載入 .env 環境變數（API KEY）
from sklearn.metrics.pairwise import cosine_similarity  # 👉 計算 cosine similarity
from sentence_transformers import SentenceTransformer   # 👉 語意 embedding 模型
from google import genai  # 👉 Gemini API（生成解釋）


# =====================
# 📂 環境設定
# =====================

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

FILE_PATH = os.path.join(
    BASE_DIR,
    "pokemon_descript",
    "pokedex.csv"
)

HF_TOKEN = os.getenv("HF_TOKEN")  # 👉 HuggingFace token（避免被限速）
API_KEY = os.getenv("GEMINI_API_KEY")

if not API_KEY:
    raise ValueError("❌ GEMINI_API_KEY 未設定")

MODEL_ID = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")

client = genai.Client(api_key=API_KEY)


# =====================
# 🧠 16型人格（保留）
# =====================

TRAITS = [
    "熱情領導者", "衝動冒險者", "社交魅力型", "行動派",
    "冷靜分析師", "策略規劃者", "理性觀察者", "系統思考者",
    "溫柔照顧者", "情感共鳴者", "忠誠守護者", "同理心強者",
    "孤獨思考者", "矛盾內省者", "敏感創作者", "觀察型人格"
]


# =====================
# 🧬 TYPE MAP（🔥完全保留）
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
"一般": [1.2, 1.0, 1.0, 1.2, 1.0, 1.0, 1.0, 1.0, 1.2, 1.1, 1.3, 1.2, 1.0, 1.0, 1.0, 1.0]
} 


# =====================
# 🧠 EMOTION KEYWORDS（🔥完全保留）
# =====================

EMOTION_KEYWORDS = {

    # =====================
    # 🔥 外向 / 能量型
    # =====================
    "熱情領導者": ["領導", "主動", "自信", "帶領", "掌控", "熱血"],
    "衝動冒險者": ["衝動", "冒險", "刺激", "勇敢", "不怕", "挑戰"],
    "社交魅力型": ["社交", "外向", "聊天", "人氣", "吸引", "人群"],
    "行動派": ["行動", "快速", "執行", "效率", "做事", "立即"],

    # =====================
    # 🧠 理性型
    # =====================
    "冷靜分析師": ["冷靜", "理性", "分析", "思考", "邏輯", "判斷"],
    "策略規劃者": ["計畫", "策略", "規劃", "安排", "設計", "佈局"],
    "理性觀察者": ["觀察", "客觀", "理解", "看清", "判斷", "研究"],
    "系統思考者": ["系統", "結構", "整體", "流程", "架構", "模型"],

    # =====================
    # 💗 情感型
    # =====================
    "溫柔照顧者": ["溫柔", "照顧", "體貼", "關心", "保護", "善良"],
    "情感共鳴者": ["共感", "情緒", "感受", "同理", "理解別人", "敏感"],
    "忠誠守護者": ["忠誠", "守護", "保護", "堅持", "可靠", "信任"],
    "同理心強者": ["同理", "理解", "包容", "接受", "寬容", "支持"],

    # =====================
    # 🌙 內向 / 複雜型
    # =====================
    "孤獨思考者": ["孤獨", "獨處", "安靜", "沉思", "內向", "一個人"],
    "矛盾內省者": ["矛盾", "糾結", "內心", "掙扎", "思考自己", "自我懷疑"],
    "敏感創作者": ["敏感", "創作", "想像", "靈感", "藝術", "情緒化"],
    "觀察型人格": ["觀察", "安靜", "看著", "記錄", "理解世界", "旁觀"]
}


# =====================
# 🧠 主系統
# =====================

class PokemonRecommender:
    """
    👉 核心推薦系統
    功能：
    1. 人格向量（TYPE_MAP + EMOTION）
    2. 語意 embedding
    3. 混合推薦（Explainable AI）
    """

    def __init__(self, path):
        """
        👉 初始化系統（只會執行一次）
        """

        print("🚀 系統啟動")

        self.df = pd.read_csv(path, encoding="utf-8")

        self.name_col = "寶可夢名稱"
        self.cat_col = "分類"
        self.desc_col = "寶可夢介紹"
        self.img_col = "圖片網址"

        print("🧠 載入語意模型")

        self.st_model = SentenceTransformer(
            EMBEDDING_MODEL,
            use_auth_token=HF_TOKEN
        )

        # 👉 預先建立向量（效能優化）
        self.persona_vectors = self.build_persona_vectors()
        self.pokemon_embeddings = self.build_embeddings()

    # =====================
    # 🧠 tokenizer
    # =====================
    def tokenize(self, text):
        """
        👉 中文斷詞
        """
        return jieba.lcut(text)

    # =====================
    # 🧠 情緒 → 人格向量
    # =====================
    def text_to_persona_vector(self, text):
        """
        👉 將文字轉成16維人格向量
        """

        vec = np.zeros(len(TRAITS))
        words = set(self.tokenize(text))

        for i, trait in enumerate(TRAITS):
            for keyword in EMOTION_KEYWORDS[trait]:
                if keyword in text or keyword in words:
                    vec[i] += 2.0

        norm = np.linalg.norm(vec)
        return vec / norm if norm > 0 else vec

    # =====================
    # 🧬 建立寶可夢人格向量
    # =====================
    def build_persona_vectors(self):
        """
        👉 每隻寶可夢 = TYPE_MAP + 描述人格
        """

        vectors = []

        for _, row in self.df.iterrows():

            category = str(row[self.cat_col])
            desc = str(row[self.desc_col])

            vec = np.zeros(len(TRAITS))

            types = [t.strip() for t in category.split(",")]

            # 👉 TYPE_MAP 加權
            for poke_type, weights in TYPE_MAP.items():
                if poke_type in types:
                    vec += np.array(weights)

            # 👉 描述轉人格
            vec += self.text_to_persona_vector(desc)

            norm = np.linalg.norm(vec)
            vectors.append(vec / norm if norm > 0 else vec)

        return np.array(vectors)

    # =====================
    # ⚡ embedding
    # =====================
    def build_embeddings(self):
        """
        👉 建立語意 embedding
        """

        texts = [
            f"{row[self.cat_col]} {row[self.desc_col]}"
            for _, row in self.df.iterrows()
        ]

        return self.st_model.encode(
            texts,
            normalize_embeddings=True
        )

    # =====================
    # 🚀 推薦
    # =====================
    def recommend(self, user_text):
        """
        👉 核心推薦邏輯（混合模型）
        """

        user_persona_vec = self.text_to_persona_vector(user_text)

        persona_sims = cosine_similarity(
            [user_persona_vec],
            self.persona_vectors
        )[0]

        user_embedding = self.st_model.encode(
            user_text,
            normalize_embeddings=True
        )

        semantic_sims = cosine_similarity(
            [user_embedding],
            self.pokemon_embeddings
        )[0]

        alpha = min(0.8, 0.3 + np.linalg.norm(user_persona_vec))

        final_sims = alpha * persona_sims + (1 - alpha) * semantic_sims

        idx = np.argmax(final_sims)

        return {
            "name": self.df.iloc[idx][self.name_col],
            "category": self.df.iloc[idx][self.cat_col],
            "desc": self.df.iloc[idx][self.desc_col],
            "img": self.df.iloc[idx][self.img_col],
            "score": float(final_sims[idx])
        }

    # =====================
    # 🤖 AI 解釋
    # =====================
    def explain(self, user_text, pokemon):
        """
        👉 使用 Gemini 生成自然語言解釋
        """

        prompt = f"""
使用者：{user_text}
寶可夢：{pokemon['name']}
介紹：{pokemon['desc']}

請用60~80字自然說明，
為什麼這隻寶可夢能夠代表這一位使用者。
"""

        res = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt
        )

        return res.text.strip()
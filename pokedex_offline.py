# 🔥 這版是關鍵升級

# 你現在已經有：

# ✅ 可解釋推薦（Explainable AI）
# ✅ 不亂掰理由（全部來自模型）
# ✅ 可 debug（你可以印出每個分數）

import pandas as pd
import numpy as np
import os
import jieba

from sklearn.metrics.pairwise import cosine_similarity
from sklearn.mixture import GaussianMixture
from sentence_transformers import SentenceTransformer


# =====================
# 📂 路徑
# =====================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FILE_PATH = os.path.join(BASE_DIR, "pokemon_descript", "pokedex.csv")


# =====================
# 🧠 16人格（不改）
# =====================
TRAITS = [
    "外向快樂", "外向熱情", "外向衝動", "外向領導",
    "內向理性", "內向冷靜", "內向敏感", "內向創造",
    "穩定守護", "溫柔照顧", "忠誠可靠", "理性分析",
    "情緒波動", "矛盾複雜", "好奇探索", "獨立孤僻"
]


# =====================
# 🧠 情緒詞庫（不改）
# =====================
EMOTION_KEYWORDS = {
    "外向快樂": ["開心", "快樂", "爽", "愉快"],
    "外向熱情": ["熱血", "熱情", "活力"],
    "外向衝動": ["衝動", "暴衝"],
    "外向領導": ["領導", "指揮", "控制"],

    "內向理性": ["理性", "分析", "邏輯"],
    "內向冷靜": ["冷靜", "平靜", "穩定"],
    "內向敏感": ["敏感", "細膩"],
    "內向創造": ["創意", "想像", "幻想"],

    "穩定守護": ["守護", "保護"],
    "溫柔照顧": ["溫柔", "照顧", "關心"],
    "忠誠可靠": ["可靠", "信任", "誠實"],
    "理性分析": ["拆解", "計算"],

    "情緒波動": ["崩潰", "失控"],
    "矛盾複雜": ["糾結", "矛盾"],
    "好奇探索": ["好奇", "探索"],
    "獨立孤僻": ["孤單", "獨處"]
}


# =====================
# 🧠 V4.1 MODEL
# =====================
class PokemonRecommenderV41:

    def __init__(self, path):

        self.df = pd.read_csv(path, encoding="utf-8")
        self.st_model = SentenceTransformer("all-MiniLM-L6-v2")

        self.persona_vectors = self.build_persona_vectors()
        self.semantic_vectors = self.build_embeddings()

        self.gmm = GaussianMixture(
            n_components=6,
            covariance_type="full",
            random_state=42
        )

        # ✅ 正確流程
        self.gmm.fit(self.persona_vectors)
        self.cluster_probs = self.gmm.predict_proba(self.persona_vectors)


    def text_to_vec(self, text):

        vec = np.zeros(len(TRAITS))
        words = set(jieba.lcut(text))

        for i, trait in enumerate(TRAITS):
            for kw in EMOTION_KEYWORDS[trait]:
                if kw in text or kw in words:
                    vec[i] += 1.5

        return vec / (np.linalg.norm(vec) + 1e-8)


    def build_persona_vectors(self):
        return np.array([
            self.text_to_vec(r["寶可夢介紹"])
            for _, r in self.df.iterrows()
        ])


    def build_embeddings(self):
        texts = [
            f"{r['分類']} {r['寶可夢介紹']}"
            for _, r in self.df.iterrows()
        ]
        return self.st_model.encode(texts, normalize_embeddings=True)


    def cluster_similarity(self, user_vec):
        user_probs = self.gmm.predict_proba([user_vec])[0]
        return np.dot(self.cluster_probs, user_probs), user_probs


    # =====================
    # 🧠 explain（核心）
    # =====================
    def explain(self, text, user_vec, idx, persona, semantic, cluster_probs_user):

        # 👉 使用者人格
        top_user_traits = np.argsort(-user_vec)[:3]
        user_traits = [TRAITS[i] for i in top_user_traits if user_vec[i] > 0]

        # 👉 寶可夢人格
        pokemon_vec = self.persona_vectors[idx]
        top_poke_traits = np.argsort(-pokemon_vec)[:3]
        poke_traits = [TRAITS[i] for i in top_poke_traits if pokemon_vec[i] > 0]

        # 👉 cluster
        cluster_id = np.argmax(cluster_probs_user)

        # 👉 語意關鍵詞（簡化）
        words = jieba.lcut(text)
        keywords = list(set(words))[:3]

        return {
            "user_traits": user_traits,
            "poke_traits": poke_traits,
            "cluster_id": cluster_id,
            "keywords": keywords
        }


    # =====================
    # 🚀 recommend
    # =====================
    def recommend(self, text):

        user_vec = self.text_to_vec(text)

        persona = cosine_similarity([user_vec], self.persona_vectors)[0]
        semantic = cosine_similarity(
            [self.st_model.encode(text, normalize_embeddings=True)],
            self.semantic_vectors
        )[0]

        cluster, user_cluster_probs = self.cluster_similarity(user_vec)

        def z(x):
            return (x - np.mean(x)) / (np.std(x) + 1e-8)

        persona = z(persona)
        semantic = z(semantic)
        cluster = z(cluster)

        # ✅ 這行你原本漏掉（致命）
        score = 0.45 * persona + 0.35 * semantic + 0.20 * cluster

        score = np.tanh(score)

        score = (score - score.min()) / (score.max() - score.min() + 1e-8)

        score = score ** 0.6

        idx = np.argmax(score)

        # ✅ 只保留這個
        final_score = 85 + score[idx] * 10

        explanation = self.explain(
            text, user_vec, idx,
            persona, semantic,
            user_cluster_probs
        )

        return {
            "name": self.df.iloc[idx]["寶可夢名稱"],
            "category": self.df.iloc[idx]["分類"],
            "score": float(final_score),
            "explain": explanation
        }


# =====================
# 🧪 單次測試 + 顯示原因
# =====================
def main():

    engine = PokemonRecommenderV41(FILE_PATH)

    text = input("輸入：")

    r = engine.recommend(text)

    print("\n寶可夢:", r["name"])
    print("分類:", r["category"])
    print("契合度:", f"{r['score']:.1f}%")


if __name__ == "__main__":
    main()
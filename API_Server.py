# =====================
# 📦 匯入套件
# =====================

import os  # 用來取得 CSV 路徑環境變數

from fastapi import FastAPI  # 建立 API 服務
from pydantic import BaseModel, Field  # 定義前端傳入資料格式與驗證規則

from pokedex_online import PokemonRecommender, FILE_PATH  # 匯入推薦系統與 CSV 路徑


# =====================
# 🚀 初始化 API
# =====================

app = FastAPI(
    title="Pokemon Personality Recommender API",
    description="根據 pokedex_final.csv 的新版欄位，推薦最符合使用者個性的寶可夢。",
    version="2.0.0",
)

# 只在 API 啟動時初始化一次模型，避免每次請求都重新載入 embedding 模型
CSV_PATH = os.getenv("POKEDEX_CSV_PATH", FILE_PATH)
engine = PokemonRecommender(CSV_PATH)


# =====================
# 📦 Request 格式
# =====================

class UserInput(BaseModel):
    """
    類別用途：
    定義前端 POST /recommend 時要傳入的 JSON 格式。

    範例：
    {
        "text": "我很內向但很溫柔，喜歡安靜思考，也會照顧朋友"
    }
    """

    text: str = Field(..., min_length=1, description="使用者的個性、興趣或生活習慣描述")


# =====================
# 🩺 健康檢查 API
# =====================

@app.get("/")
def home():
    """
    函式用途：
    確認 API 有正常啟動。
    """

    return {
        "message": "Pokemon Personality Recommender API is running.",
        "csv_path": CSV_PATH,
    }


@app.get("/health")
def health_check():
    """
    函式用途：
    給前端或部署平台檢查 API 是否正常。
    """

    return {"status": "ok"}


# =====================
# 🚀 主推薦 API
# =====================

@app.post("/recommend")
def recommend(user: UserInput):
    """
    函式用途：
    接收使用者文字，回傳推薦寶可夢與 AI 分析。
    """

    results = engine.recommend(user.text, top_k=3)
    explanations = [engine.explain(user.text, pokemon) for pokemon in results]

    return {
        "results": [
            {**pokemon, "explanation": explanation}
            for pokemon, explanation in zip(results, explanations)
        ],
    }

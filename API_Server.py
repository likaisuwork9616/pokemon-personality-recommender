# =====================
# 📦 匯入模組
# =====================

from fastapi import FastAPI  # 👉 建立 API 服務
from pydantic import BaseModel  # 👉 定義請求格式
from pokedex_online import PokemonRecommender  # 👉 載入推薦模型


# =====================
# 🚀 初始化 API
# =====================

app = FastAPI(title="Pokemon AI API")

engine = PokemonRecommender("pokemon_descript/pokedex.csv")


# =====================
# 📦 Request 格式
# =====================

class UserInput(BaseModel):
    """
    👉 定義前端傳入格式
    """
    text: str


# =====================
# 🚀 API Endpoint
# =====================

@app.post("/recommend")
def recommend(user: UserInput):
    """
    👉 主推薦 API
    """

    result = engine.recommend(user.text)
    explanation = engine.explain(user.text, result)

    return {
        "pokemon": result,
        "explanation": explanation
    }
# =====================
# 📦 匯入套件
# =====================

import random  # 讓打字機效果每次顯示 2～3 字，看起來更自然
import time  # 控制打字機效果的停頓時間

import gradio as gr  # 用 Python 快速建立網頁 UI

from pokedex_online import PokemonRecommender, FILE_PATH  # 匯入推薦模型與新版 CSV 路徑


# =====================
# 🚀 初始化模型
# =====================

# 只初始化一次，避免使用者每按一次按鈕就重新載入模型
engine = PokemonRecommender(FILE_PATH)


# =====================
# 🎮 輸入驗證函式
# =====================

def validate_input(text):
    """
    函式用途：
    驗證使用者輸入是否適合拿來做人格分析。

    規則：
    1. 至少 10 個字
    2. 不能只是重複字
    3. 不能只是測試文字或大量數字
    4. 最好包含情緒、個性、興趣、關係、行為相關詞
    """

    text = str(text).strip()

    if len(text) < 10:
        return False, "⚠️ 請至少輸入 10 個字！"

    if len(set(text)) <= 2:
        return False, "⚠️ 請輸入更有意義的內容，不要只重複同樣的字。"

    meaningless_inputs = [
        "一二三四五六七八九十",
        "1234567890",
        "abcdefghij",
        "ABCDEFGHIJ",
        "qwertyuiop",
        "測試測試測試測試測試",
        "哈哈哈哈哈哈哈哈哈哈",
        "呵呵呵呵呵呵呵呵呵呵",
    ]

    if text in meaningless_inputs:
        return False, "⚠️ 請不要輸入測試文字，請描述你的個性、興趣或喜好。"

    digit_count = sum(ch.isdigit() for ch in text)
    if digit_count / len(text) > 0.6:
        return False, "⚠️ 請不要只輸入數字，請描述你的個性或興趣。"

    meaningful_keywords = [
        "開心", "難過", "生氣", "害怕", "焦慮", "緊張", "快樂", "悲傷", "失落", "感動",
        "孤單", "寂寞", "興奮", "壓力", "煩躁", "內向", "外向", "冷靜", "熱情", "溫柔",
        "理性", "感性", "敏感", "衝動", "樂觀", "悲觀", "害羞", "自信", "安靜", "活潑",
        "成熟", "單純", "善良", "固執", "獨立", "朋友", "家人", "聊天", "陪伴", "照顧",
        "幫助", "保護", "信任", "依賴", "同理", "關心", "支持", "孤獨", "社交", "團隊",
        "思考", "觀察", "分析", "計畫", "冒險", "挑戰", "努力", "學習", "探索", "創作",
        "發呆", "睡覺", "紀錄", "研究", "領導", "遊戲", "音樂", "畫畫", "閱讀", "寫作",
        "唱歌", "跳舞", "運動", "旅行", "動漫", "電影", "攝影", "烹飪", "設計", "程式",
        "寶可夢", "貓", "狗", "健身", "散步",
    ]

    if not any(keyword in text for keyword in meaningful_keywords):
        return False, "⚠️ 請輸入和個性、情緒、興趣有關的內容，這樣分析才會準確。"

    return True, ""


# =====================
# 🎮 主推薦函式
# =====================

def predict(text):
    """
    函式用途：
    使用者按下「開始圖鑑分析」後執行。

    流程：
    1. 驗證輸入
    2. 呼叫推薦模型 recommend()
    3. 呼叫 AI 解釋 explain()
    4. 用 yield 做出打字機效果
    """

    is_valid, msg = validate_input(text)

    if not is_valid:
        yield (
            "❌ 輸入錯誤",
            "請重新輸入",
            "-",
            "0%",
            None,
            msg,
        )
        return

    yield (
        "🔍 分析中...",
        "正在比對圖鑑資料",
        "正在讀取新版 final.csv 欄位",
        "...",
        None,
        "🧠 AI 正在分析你的個性...",
    )

    try:
        result = engine.recommend(text)
        explanation = engine.explain(text, result)
    except Exception as e:
        yield (
            "❌ 系統錯誤",
            "請檢查 CSV 或模型設定",
            "-",
            "0%",
            None,
            f"錯誤訊息：{e}",
        )
        return

    i = 0
    while i < len(explanation):
        step = random.randint(2, 3)
        current_text = explanation[: i + step]

        yield (
            f"✨ #{result['pokedex_number']} {result['name']} / {result['name_en']}",
            f"🧬 屬性：{result['type']}",
            f"📘 分類：{result['category']}",
            f"🔥 {result['score']:.2f}%",
            result["img"],
            current_text,
        )

        i += step
        time.sleep(random.uniform(0.02, 0.05))


# =====================
# 🎨 CSS 樣式
# =====================

custom_css = """
body {
    margin: 0 !important;
    background: #073b66 !important;
    font-family: 'Segoe UI', 'Microsoft JhengHei', sans-serif;
}

.gradio-container {
    background: #073b66 !important;
}

#main_container {
    width: min(1800px, 99vw);
    margin: 0 auto;
}

#pokedex_header {
    background: linear-gradient(135deg, #e60012, #ff4d4d);
    border-radius: 0 0 28px 28px;
    padding: clamp(14px, 2.5vw, 28px);
    margin-bottom: 22px;
    box-shadow: 0 8px 22px rgba(0,0,0,0.22);
}

#pokedex_header h1,
#pokedex_header h2 {
    color: white !important;
    text-align: center;
    margin: 0;
}

#pokedex_header h1 {
    font-size: clamp(28px, 4vw, 42px);
    letter-spacing: 1px;
}

#pokedex_header h2 {
    font-size: clamp(16px, 2vw, 22px);
    margin-top: 8px;
}

#result_title h3,
#result_title {
    color: white !important;
}

#search_card,
#result_card {
    background: white !important;
    border-radius: 24px !important;
    padding: clamp(14px, 2vw, 22px) !important;
    box-shadow: 0 8px 24px rgba(0,0,0,0.12) !important;
    height: 100%;
}

#search_inner,
#pokemon_visual,
#pokemon_info {
    background: #24262b !important;
    border-radius: 18px !important;
    padding: 16px !important;
    height: 100%;
}

#search_inner h3 {
    color: white !important;
}

#dex_panel {
    background: #eaf4ff !important;
    border: 3px solid #2f80ed !important;
    border-radius: 24px !important;
    padding: clamp(12px, 1.8vw, 20px) !important;
}

#pokemon_visual img {
    max-height: 300px !important;
    object-fit: contain !important;
    border-radius: 18px !important;
    background: #f1f6ff !important;
}

textarea,
input {
    background: #fffef8 !important;
    color: #1f2937 !important;
    border-radius: 16px !important;
    border: 2px solid #dbe7f5 !important;
    font-size: 20px !important;
    padding: 14px !important;
}

textarea:focus,
input:focus {
    border-color: #2f80ed !important;
    box-shadow: 0 0 0 3px rgba(47,128,237,0.18) !important;
}

textarea::placeholder,
input::placeholder {
    font-size: 18px !important;
    color: #6b7280 !important;
}

label {
    color: white !important;
    font-weight: bold !important;
    font-size: 18px !important;
}

button {
    background: linear-gradient(135deg, #2f80ed, #1c5fd4) !important;
    color: white !important;
    border-radius: 999px !important;
    font-weight: bold !important;
    border: none !important;
    padding: 12px 20px !important;
    transition: 0.25s ease !important;
}

button:hover {
    transform: translateY(-2px);
    box-shadow: 0 8px 18px rgba(47,128,237,0.32) !important;
}

#analysis_box textarea {
    background: #fffdf3 !important;
    border: 2px solid #ffd966 !important;
    line-height: 1.8 !important;
    min-height: 260px !important;
    max-height: 260px !important;
    overflow-y: auto !important;
    font-size: 18px !important;
}

#hint_text {
    color: #cbd5e1 !important;
    text-align: center;
    font-size: 15px;
}

@media (max-width: 950px) {
    #main_container {
        width: 96vw;
    }

    #layout_row {
        flex-direction: column !important;
    }

    #pokemon_visual img {
        max-height: 230px !important;
    }

    #analysis_box textarea {
        max-height: 150px !important;
    }
}
"""


# =====================
# 🎮 建立 Gradio UI
# =====================

with gr.Blocks(css=custom_css, theme=gr.themes.Base()) as ui:
    with gr.Column(elem_id="main_container"):
        with gr.Group(elem_id="pokedex_header"):
            gr.Markdown("# 🎮 寶可夢人格圖鑑")

        with gr.Row(equal_height=True, elem_id="layout_row"):
            with gr.Column(scale=3, min_width=260):
                with gr.Group(elem_id="search_card"):
                    with gr.Group(elem_id="search_inner"):
                        gr.Markdown("### 🔍 個性搜尋")
                        gr.Markdown(
                            "<p id='hint_text'>請輸入至少 10 個字，描述你的個性、興趣、喜好或生活習慣。</p>"
                        )

                        user_input = gr.Textbox(
                            label="你的個性描述",
                            placeholder="例如：我很內向但對朋友很溫柔，喜歡自己思考，也喜歡安靜地完成事情。",
                            lines=9,
                        )

                        submit_btn = gr.Button("開始圖鑑分析")

            with gr.Column(scale=7, min_width=780):
                with gr.Group(elem_id="result_card"):
                    with gr.Group(elem_id="result_title"):
                        gr.Markdown("### 📘 圖鑑分析結果")

                    with gr.Group(elem_id="dex_panel"):
                        with gr.Row(equal_height=True):
                            with gr.Column(scale=2.8, min_width=280, elem_id="pokemon_visual"):
                                image_output = gr.Image(
                                    label="寶可夢圖片",
                                    type="filepath",
                                    height=300,
                                )

                            with gr.Column(scale=4.2, min_width=420, elem_id="pokemon_info"):
                                name_output = gr.Textbox(label="寶可夢名稱", interactive=False)
                                type_output = gr.Textbox(label="屬性", interactive=False)
                                category_output = gr.Textbox(label="分類", interactive=False)
                                score_output = gr.Textbox(label="人格契合度", interactive=False)

                                with gr.Group(elem_id="analysis_box"):
                                    explanation_output = gr.Textbox(
                                        label="AI 分析",
                                        lines=5,
                                        interactive=False,
                                    )

        submit_btn.click(
            fn=predict,
            inputs=user_input,
            outputs=[
                name_output,
                type_output,
                category_output,
                score_output,
                image_output,
                explanation_output,
            ],
        )


# =====================
# 🚀 啟動網站
# =====================

if __name__ == "__main__":
    # share=False：只在本機開啟
    # inbrowser=True：啟動後自動打開瀏覽器
    ui.launch(inbrowser=True)

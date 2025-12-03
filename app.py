
import streamlit as st
import google.generativeai as genai
import pandas as pd
from PIL import Image
import json
import os
import time
import re

# --- セキュリティ対策 ---
# Streamlit CloudのSecretsからキーを読み込む
try:
    api_key = st.secrets["GOOGLE_API_KEY"]
except:
    api_key = os.environ.get("GOOGLE_API_KEY", "")

st.set_page_config(page_title="Jagrad総力戦", layout="wide")
st.title("🎰 Jagradデータ一覧 (Gemini総力戦モデル)")
st.write("Googleの複数のAIモデルがチームを組み、総がかりで画像を解析します。")

# --- 機種選択 ---
MODELS_DB = {
    "アイムジャグラーEX(6号機)": {"border": 300},
    "マイジャグラーV": {"border": 270},
    "ファンキージャグラー2": {"border": 300},
    "ハッピージャグラーV III": {"border": 280},
    "ゴーゴージャグラー3": {"border": 250},
}
selected_model = st.sidebar.selectbox("機種を選択", list(MODELS_DB.keys()))
target_border = MODELS_DB[selected_model]["border"]
st.sidebar.info(f"設定: {selected_model}\n高設定目安: REG 1/{target_border}以下")

# --- AIチーム ---
model_team = ['gemini-2.0-flash-exp', 'gemini-1.5-pro', 'gemini-1.5-flash', 'gemini-2.0-flash']

# --- メイン処理 ---
uploaded_files = st.file_uploader("データ一覧の画像をアップロード", type=['jpg', 'png', 'jpeg'], accept_multiple_files=True)

if uploaded_files and st.button("AI総動員で解析開始！"):
    if not api_key:
        st.error("APIキーが設定されていません。Streamlit CloudのSecretsを設定してください。")
        st.stop()
        
    genai.configure(api_key=api_key)
    progress_bar = st.progress(0)
    all_results = []
    
    for i, file in enumerate(uploaded_files):
        img = Image.open(file)
        # プロンプト
        prompt = """
        このスロットのデータ表の画像から、全ての行の数値を読み取ってください。
        以下のJSON形式のリストのみを出力してください。Markdown装飾不要。
        [{"台番号": "文字列", "累計": 整数, "BB": 整数, "RB": 整数}, ...]
        ※読み取れない項目は -1
        """
        response = None
        used_model_name = ""
        
        for model_name in model_team:
            try:
                model = genai.GenerativeModel(model_name)
                response = model.generate_content([prompt, img])
                used_model_name = model_name
                break
            except: continue
        
        if response:
            try:
                raw_text = response.text
                cleaned_text = re.sub(r'```json|```', '', raw_text).strip()
                match = re.search(r'\[.*\]', cleaned_text, re.DOTALL)
                if match:
                    data_list = json.loads(match.group(0))
                    for d in data_list:
                        def cn(v): return int(re.sub(r'\D', '', str(v))) if str(v).replace('-','').isdigit() else -1
                        total = cn(d.get("累計", d.get("total", -1)))
                        rb = cn(d.get("RB", d.get("reg", -1)))
                        prob = total / rb if (total>0 and rb>0) else 9999.0
                        status = "🔥 激アツ" if prob <= target_border else ("✨ チャンス" if prob <= target_border*1.1 else "☁️")
                        all_results.append({
                            "台番号": str(d.get("台番号", "不明")), "総回転": total, "BB": cn(d.get("BB", -1)), "RB": rb,
                            "REG確率": f"1/{prob:.1f}" if rb>0 else "-", "判定": status, "_sort": prob, "担当AI": used_model_name
                        })
            except: st.warning(f"⚠️ {file.name}: データ変換エラー")
        else: st.error(f"❌ {file.name}: 解析失敗(混雑中)")
        
        time.sleep(1)
        progress_bar.progress((i + 1) / len(uploaded_files))

    if all_results:
        st.success("解析完了！")
        df = pd.DataFrame(all_results).sort_values("_sort").drop(columns=["_sort"])
        def hl(row): return ['background-color: #ffcccc; color: red; font-weight: bold'] * len(row) if "🔥" in row["判定"] else (['background-color: #ffffcc; color: black'] * len(row) if "✨" in row["判定"] else ['']*len(row))
        st.dataframe(df.style.apply(hl, axis=1), use_container_width=True, hide_index=True)

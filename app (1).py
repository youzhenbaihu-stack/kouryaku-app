
import streamlit as st
import google.generativeai as genai
import pandas as pd
from PIL import Image
import json
import os
import time
import re
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime, date

# --- 設定 ---
st.set_page_config(page_title="Jagrad Pro", layout="wide")
st.title("🎰 Jagrad Pro (ホール記録 ＆ AI解析)")

# --- 1. 認証まわり (Gemini & Google Sheets) ---
try:
    # Gemini APIキー
    api_key = st.secrets["GOOGLE_API_KEY"]
    
    # Google Sheets 認証
    # SecretsからJSON文字列を読み込んで認証情報を作る
    json_str = st.secrets["gcp_service_account"]
    creds_dict = json.loads(json_str)
    scope = ['https://spreadsheets.google.com/feeds','https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    
    # シートを開く (名前は 'juggler_db' 固定)
    sheet = client.open("juggler_db").sheet1
    
except Exception as e:
    st.error(f"認証エラー: {e}")
    st.info("Streamlit CloudのSecrets設定を確認してください。")
    st.stop()

# --- 2. タブで機能を分ける ---
tab1, tab2, tab3 = st.tabs(["📸 AI解析", "📝 ホール記録", "📊 収支データ"])

# ==========================================
# タブ1: AI解析 (いつもの機能)
# ==========================================
with tab1:
    st.write("#### データカウンター解析")
    
    # 機種設定
    MODELS_DB = {
        "アイムジャグラーEX(6号機)": {"border": 300},
        "マイジャグラーV": {"border": 270},
        "ファンキージャグラー2": {"border": 300},
        "ハッピージャグラーV III": {"border": 280},
        "ゴーゴージャグラー3": {"border": 250},
    }
    selected_model = st.selectbox("機種を選択", list(MODELS_DB.keys()))
    target_border = MODELS_DB[selected_model]["border"]
    
    model_team = ['gemini-2.0-flash-exp', 'gemini-1.5-pro', 'gemini-1.5-flash']
    uploaded_files = st.file_uploader("画像をアップロード", type=['jpg', 'png'], accept_multiple_files=True)

    if uploaded_files and st.button("AI解析スタート"):
        genai.configure(api_key=api_key)
        progress_bar = st.progress(0)
        all_results = []
        
        for i, file in enumerate(uploaded_files):
            img = Image.open(file)
            prompt = """
            スロットデータ表の画像から数値を読み取ってください。
            JSONリストのみ出力: [{"台番号": "文字列", "累計": 整数, "BB": 整数, "RB": 整数}, ...]
            ※読めない場合は-1
            """
            response = None
            used_model = ""
            for m_name in model_team:
                try:
                    model = genai.GenerativeModel(m_name)
                    response = model.generate_content([prompt, img])
                    used_model = m_name
                    break
                except: continue
            
            if response:
                try:
                    raw = response.text
                    clean = re.sub(r'```json|```', '', raw).strip()
                    match = re.search(r'\[.*\]', clean, re.DOTALL)
                    if match:
                        data_list = json.loads(match.group(0))
                        for d in data_list:
                            def cn(v): return int(re.sub(r'\D', '', str(v))) if str(v).replace('-','').isdigit() else -1
                            total = cn(d.get("累計", d.get("total", -1)))
                            rb = cn(d.get("RB", d.get("reg", -1)))
                            prob = total / rb if (total>0 and rb>0) else 9999.0
                            status = "🔥 激アツ" if prob <= target_border else ("✨ チャンス" if prob <= target_border*1.1 else "☁️")
                            all_results.append({
                                "台番": str(d.get("台番号", "不明")), "総回転": total, "BB": cn(d.get("BB",-1)), "RB": rb,
                                "RB確率": f"1/{prob:.1f}" if rb>0 else "-", "判定": status, "_sort": prob
                            })
                except: pass
            progress_bar.progress((i+1)/len(uploaded_files))
            time.sleep(1)

        if all_results:
            st.success("解析完了！")
            df = pd.DataFrame(all_results).sort_values("_sort").drop(columns=["_sort"])
            def hl(row): return ['background-color: #ffcccc; color: red']*len(row) if "🔥" in row["判定"] else ['']*len(row)
            st.dataframe(df.style.apply(hl, axis=1), use_container_width=True)

# ==========================================
# タブ2: ホール記録 (スプレッドシートへ保存)
# ==========================================
with tab2:
    st.write("#### 📝 実戦データの記録")
    with st.form("record_form"):
        col1, col2 = st.columns(2)
        with col1:
            date_val = st.date_input("日付", date.today())
            hall_name = st.text_input("ホール名", placeholder="例：〇〇店")
            machine_no = st.text_input("台番号", placeholder="例：123番台")
        with col2:
            model_name = st.selectbox("機種", list(MODELS_DB.keys()) + ["その他"])
            setting_guess = st.selectbox("設定推測", ["不明", "低設定(1-3)", "中間(4)", "高設定(5-6)", "設定6確定"])
            
        st.write("---")
        col3, col4 = st.columns(2)
        with col3:
            invest = st.number_input("投資 (枚)", min_value=0, step=50)
        with col4:
            collect = st.number_input("回収 (枚)", min_value=0, step=50)
            
        memo = st.text_area("メモ (特定日の傾向など)")
        
        # 保存ボタン
        submitted = st.form_submit_button("スプレッドシートに保存")
        
        if submitted:
            profit = collect - invest
            # データ作成
            new_row = [
                str(date_val), hall_name, machine_no, model_name, 
                setting_guess, invest, collect, profit, memo, 
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ]
            
            try:
                # 1行目が空ならヘッダーを追加
                if not sheet.get_all_values():
                    sheet.append_row(["日付", "ホール名", "台番", "機種", "設定推測", "投資", "回収", "差枚", "メモ", "登録日時"])
                
                # データを追加
                sheet.append_row(new_row)
                st.success(f"保存しました！ 差枚: {profit:+d}枚")
            except Exception as e:
                st.error(f"保存失敗: {e}")

# ==========================================
# タブ3: データ履歴 & 分析
# ==========================================
with tab3:
    st.write("#### 📊 過去のデータ")
    if st.button("データを更新"):
        st.rerun()
        
    try:
        data = sheet.get_all_records()
        if data:
            df_hist = pd.DataFrame(data)
            
            # 簡単な指標
            total_profit = df_hist["差枚"].sum() if "差枚" in df_hist.columns else 0
            win_rate = (df_hist["差枚"] > 0).mean() * 100 if "差枚" in df_hist.columns else 0
            
            kpi1, kpi2, kpi3 = st.columns(3)
            kpi1.metric("通算収支", f"{total_profit:+d} 枚")
            kpi2.metric("勝率", f"{win_rate:.1f} %")
            kpi3.metric("記録数", f"{len(df_hist)} 件")
            
            # データの表示
            st.dataframe(df_hist, use_container_width=True)
        else:
            st.info("まだデータがありません。「ホール記録」タブから入力してください。")
            
    except Exception as e:
        st.warning("データを読み込めませんでした（まだデータがないか、エラーです）")

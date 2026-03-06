import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import io
import requests
import xml.etree.ElementTree as ET

# --- 전역 폰트 설정 ---
TITLE_FONT_SIZE = "15px"
CONTENT_FONT_SIZE = "12px"

# --- 1. 초기 DB 설정 (표준품명 및 사용자 관리용) ---
def init_db():
    conn = sqlite3.connect("customs_master.db")
    c = conn.cursor()
    # 관세율/통계부호는 API로 대체하므로, 이지스 고유 데이터인 '표준품명' 테이블 위주로 유지
    c.execute("CREATE TABLE IF NOT EXISTS hs_master (hs_code TEXT, name_kr TEXT, name_en TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS standard_names (hs_code TEXT, base_name TEXT, std_name_kr TEXT, std_name_en TEXT)")
    conn.commit()
    conn.close()

    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    admin_id = "aegis01210"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    conn_auth.commit()
    conn_auth.close()

init_db()

# Gemini API 설정
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 세션 관리 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    st.title("🔐 AEGIS 서비스 로그인")
    l_id = st.text_input("아이디")
    l_pw = st.text_input("비밀번호", type="password")
    if st.button("로그인"):
        conn = sqlite3.connect("users.db")
        res = conn.execute("SELECT is_approved, is_admin FROM users WHERE id=? AND pw=?", 
                           (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
        conn.close()
        if res and res[0] == 1:
            st.session_state.logged_in = True
            st.session_state.user_id = l_id
            st.session_state.is_admin = bool(res[1])
            st.rerun()
        else: st.error("정보 불일치 또는 승인 대기")
    st.stop()

# --- 3. 메인 레이아웃 ---
st.sidebar.write(f"✅ {st.session_state.user_id} 접속 중")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관진행정보", "🧮 세액계산기"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 (Gemini AI) ---
with tabs[0]:
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("품명/물품정보 입력", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"], key="hs_i")
    if st.button("HS분석 실행", use_container_width=True):
        with st.spinner("AI 분석 중..."):
            try:
                prompt = f"당신은 전문 관세사입니다. 품명 '{u_input}'을 분석하여 HS코드 10자리를 추천하세요."
                content = [prompt]
                if u_img: content.append(Image.open(u_img))
                res = model.generate_content(content)
                st.markdown("### 📋 분석 리포트")
                st.write(res.text)
            except Exception as e: st.error(f"오류: {e}")

# --- [Tab 2] HS정보 (실시간 품목별 관세율 API) ---
with tabs[1]:
    st.markdown(f"""
        <style>
            .custom-header {{ font-size: {TITLE_FONT_SIZE} !important; font-weight: bold; color: #1E3A8A; border-left: 4px solid #1E3A8A; padding-left: 8px; margin-bottom: 10px; }}
            div[data-testid="stMetricValue"] {{ font-size: 20px !important; }}
        </style>
    """, unsafe_allow_html=True)
    
    # 개별 인증키 호출 (RATE_API_KEY)
    RATE_KEY = st.secrets.get("RATE_API_KEY", "").strip()
    target_hs = st.text_input("HS코드 10자리 입력", placeholder="예: 8517130000", key="hs_rate_input")

    if st.button("실시간 관세율 조회", use_container_width=True):
        if not target_hs: st.warning("코드를 입력하세요.")
        else:
            with st.spinner("유니패스 관세율 서버 연결 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/itemRateQry/retrieveItemRate"
                params = {"crkyCn": RATE_KEY, "hsCd": target_hs.strip()}
                try:
                    res = requests.get(url, params=params, timeout=15)
                    root = ET.fromstring(res.content)
                    items = root.findall(".//itemRateQryVo")
                    if items:
                        st.markdown(f"<div class='custom-header'>💰 HS {target_hs} 실시간 세율 정보</div>", unsafe_allow_html=True)
                        data = []
                        for i in items:
                            data.append({"구분": i.findtext("tarfClsfCd"), "세율명칭": i.findtext("tarfNm"), "세율": f"{i.findtext('itrt')}%"})
                        
                        df = pd.DataFrame(data)
                        c1, c2 = st.columns(2)
                        with c1: 
                            val_a = df[df['구분']=='A']['세율'].values
                            st.metric("기본세율 (A)", val_a[0] if len(val_a)>0 else "-")
                        with c2:
                            val_c = df[df['구분']=='C']['세율'].values
                            st.metric("WTO세율 (C)", val_c[0] if len(val_c)>0 else "-")
                        st.dataframe(df, hide_index=True, use_container_width=True)
                    else: st.warning("데이터가 없습니다.")
                except Exception as e: st.error(f"API 오류: {e}")

# --- [Tab 3] 통계부호 (실시간 공통코드 API) ---
with tabs[2]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📊 실시간 통계부호 검색</div>", unsafe_allow_html=True)
    
    # 개별 인증키 호출 (STAT_API_KEY)
    STAT_KEY = st.secrets.get("STAT_API_KEY", "").strip()
    
    clft_map = {"관세감면": "001", "내국세면세": "002", "보세구역": "003", "세관부호": "004"} # 예시 분류코드
    col1, col2 = st.columns([1, 2])
    with col1: sel_clft = st.selectbox("분류 선택", list(clft_map.keys()))
    with col2: kw = st.text_input("검색어 입력", placeholder="예: 인천, 감면")

    if st.button("부호 검색", use_container_width=True):
        with st.spinner("유니패스 코드 서버 조회 중..."):
            url = "https://unipass.customs.go.kr:38010/ext/rest/cmmnCdQry/retrieveCmmnCd"
            params = {"crkyCn": STAT_KEY, "clftCd": clft_map[sel_clft]}
            try:
                res = requests.get(url, params=params, timeout=15)
                root = ET.fromstring(res.content)
                codes = root.findall(".//cmmnCdQryVo")
                if codes:
                    res_list = []
                    for c in codes:
                        name, code_val = c.findtext("cdNm"), c.findtext("cd")
                        if not kw or (kw in name or kw in code_val):
                            res_list.append({"코드": code_val, "명칭": name, "비고": c.findtext("cdDesc")})
                    st.dataframe(pd.DataFrame(res_list), hide_index=True, use_container_width=True)
                else: st.warning("결과 없음")
            except Exception as e: st.error(f"API 오류: {e}")

# --- [Tab 4] 화물통관진행정보 (기존 개별 키 방식) ---
with tabs[3]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold;'>📦 화물 실시간 추적</div>", unsafe_allow_html=True)
    
    # 개별 인증키 호출 (CARGO_API_KEY)
    CARGO_KEY = st.secrets.get("CARGO_API_KEY", "").strip()
    
    c1, c2 = st.columns([1, 2])
    with c1: yy = st.selectbox("년도", [2026, 2025, 2024])
    with c2: bl = st.text_input("B/L 번호")
    
    if st.button("추적 실행", use_container_width=True):
        url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
        params = {"crkyCn": CARGO_KEY, "blYy": str(yy), "hblNo": bl.strip().upper()}
        try:
            res = requests.get(url, params=params, timeout=15)
            root = ET.fromstring(res.content)
            info = root.find(".//cargCsclPrgsInfoQryVo")
            if info is not None:
                st.success(f"현재상태: {info.findtext('prgsStts')}")
                st.write(f"품명: {info.findtext('prnm')}")
            else: st.warning("정보를 찾을 수 없습니다.")
        except Exception as e: st.error(f"API 오류: {e}")

# --- 하단 푸터 ---
st.divider()
st.write("📞 010-8859-0403 (이지스 관세사무소)")
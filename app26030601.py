import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import requests
import xml.etree.ElementTree as ET
import urllib3

# SSL 경고 메시지 무시 설정 (API 연결 안정성 확보)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- 전역 설정 ---
TITLE_FONT_SIZE = "15px"
CONTENT_FONT_SIZE = "12px"
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/xml"
}

# --- 1. 초기 DB 설정 ---
def init_db():
    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, name, is_approved, is_admin) VALUES (?, ?, ?, 1, 1)", 
                      ("aegis01210", admin_pw, "관리자"))
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
        res = conn.execute("SELECT is_approved, is_admin, name FROM users WHERE id=? AND pw=?", 
                           (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
        conn.close()
        if res and res[0] == 1:
            st.session_state.logged_in = True
            st.session_state.user_id = l_id
            st.session_state.user_name = res[2]
            st.session_state.is_admin = bool(res[1])
            st.rerun()
        else: st.error("승인 대기 또는 정보 불일치")
    st.stop()

# --- 3. 메인 화면 ---
st.sidebar.write(f"✅ {st.session_state.user_name} 접속 중")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관진행정보", "🧮 세액계산기"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 (로직 고정) ---
with tabs[0]:
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("품명/물품정보 입력", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"], key="hs_i")
    if st.button("HS분석 실행", use_container_width=True):
        with st.spinner("AI 분석 중..."):
            try:
                prompt = f"당신은 전문 관세사입니다. 물품 '{u_input}'을 분석하여 HS코드 10자리를 추천하고 리포트를 작성하세요."
                res = model.generate_content([prompt, Image.open(u_img)] if u_img else prompt)
                st.markdown("### 📋 분석 리포트")
                st.write(res.text)
            except Exception as e: st.error(f"오류: {e}")

# --- [Tab 2] HS정보 (API018 가이드 정밀 반영) ---
with tabs[1]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📘 실시간 HS부호 정보 (Uni-Pass)</div>", unsafe_allow_html=True)
    RATE_KEY = st.secrets.get("RATE_API_KEY", "").strip()
    target_hs = st.text_input("HS코드 입력 (최소 2자리~10자리)", placeholder="예: 030244", key="hs_rate_api")
    if st.button("실시간 HS 정보 조회", use_container_width=True):
        if target_hs:
            with st.spinner("가이드 경로로 데이터 호출 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/hsSgnQry/searchHsSgn"
                params = {"crkyCn": RATE_KEY, "hsSgn": target_hs.strip(), "koenTp": "1"}
                try:
                    res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15, verify=False)
                    root = ET.fromstring(res.content)
                    if root.find(".//korePrnm") is not None:
                        st.info(f"✅ 품명: {root.findtext('.//korePrnm')}")
                        st.write(f"영문품명: {root.findtext('.//englPrnm')}")
                        st.success(f"적용세율: {root.findtext('.//txrt') or '정보없음'}")
                    else: st.warning("정보를 찾을 수 없습니다. 인증키의 'API018' 승인 여부를 확인하세요.")
                except Exception as e: st.error(f"연결 오류: {e}")

# --- [Tab 3] 통계부호 (API019 가이드 정밀 반영) ---
with tabs[2]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📊 실시간 통계부호 검색 (Uni-Pass)</div>", unsafe_allow_html=True)
    STAT_KEY = st.secrets.get("STAT_API_KEY", "").strip()
    clft_dict = {"관세감면/분납": "A01", "내국세율": "A04", "용도부호": "A05", "보세구역": "A08"}
    col1, col2 = st.columns([1, 2])
    with col1: sel_clft = st.selectbox("분류 선택", list(clft_dict.keys()))
    with col2: kw = st.text_input("한글내역 키워드", placeholder="예: 정밀전자")
    if st.button("부호 실시간 검색", use_container_width=True):
        url = "https://unipass.customs.go.kr:38010/ext/rest/statsSgnQry/retrieveStatsSgnBrkd"
        params = {"crkyCn": STAT_KEY, "statsSgnclftCd": clft_dict[sel_clft]}
        try:
            res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15, verify=False)
            root = ET.fromstring(res.content)
            codes = root.findall(".//statsSgnQryVo")
            if codes:
                res_list = []
                for c in codes:
                    name = c.findtext("koreBrkd")
                    if not kw or kw in name:
                        res_list.append({"통계부호": c.findtext("statsSgn"), "한글내역": name, "내국세율": c.findtext("itxRt")})
                st.dataframe(pd.DataFrame(res_list), hide_index=True, use_container_width=True)
            else: st.warning("결과가 없습니다. 인증키의 'API019' 승인 여부를 확인하세요.")
        except Exception as e: st.error(f"연결 오류: {e}")

# --- [Tab 4] 화물통관진행정보 (고정 로직 및 보안 강화) ---
with tabs[3]:
    st.subheader("📦 실시간 화물통관 진행정보 조회")
    CR_API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
    c1, c2 = st.columns([1, 3])
    with c1: carg_year = st.selectbox("년도", [2026, 2025, 2024], index=0)
    with c2: bl_no = st.text_input("B/L 번호", key="bl_v3_fixed")
    if st.button("실시간 조회", use_container_width=True) and bl_no:
        url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
        params = {"crkyCn": CR_API_KEY, "blYy": str(carg_year), "hblNo": bl_no.strip().upper()}
        try:
            res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=20, verify=False)
            root = ET.fromstring(res.content)
            info = root.find(".//cargCsclPrgsInfoQryVo")
            if info is not None:
                st.success(f"✅ 상태: {info.findtext('prgsStts')}")
                st.write(f"품명: {info.findtext('prnm')} | 중량: {info.findtext('ttwg')}")
            else: st.warning("조회 결과 없음")
        except Exception as e: st.error(f"API 오류: {e}")

# --- 하단 푸터 (고정) ---
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")
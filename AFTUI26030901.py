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

# --- [AFTUI26030901] 전역 디자인 설정 (엘박스 스타일) ---
st.set_page_config(page_title="AEGIS - 전문 관세 행정 데이터 포털", layout="wide")

TITLE_FONT_SIZE = "16px"
CONTENT_FONT_SIZE = "13px"

st.markdown(f"""
    <style>
        /* 폰트 및 배경 시스템 */
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
        * {{ font-family: 'Pretendard', sans-serif; }}
        .stApp {{ background-color: #FFFFFF; }}

        /* 엘박스 스타일 내비게이션 (Tabs) */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 24px;
            background-color: #FFFFFF;
            padding: 0px 20px;
            border-bottom: 1px solid #E2E8F0;
        }}
        .stTabs [data-baseweb="tab"] {{
            height: 50px;
            background-color: transparent;
            border: none;
            color: #64748B;
            font-size: 15px;
            font-weight: 500;
        }}
        .stTabs [aria-selected="true"] {{
            color: #1E3A8A !important;
            border-bottom: 2px solid #1E3A8A !important;
        }}

        /* 전문가용 카드 섹션 */
        .stContainer {{
            border: 1px solid #E2E8F0;
            border-radius: 8px;
            padding: 24px;
            margin-bottom: 20px;
            background-color: #FFFFFF;
        }}

        /* 버튼: 엘박스 네이비 */
        .stButton > button {{
            background-color: #1E3A8A;
            color: white;
            border-radius: 6px;
            border: none;
            padding: 12px 24px;
            font-weight: 600;
            transition: all 0.2s;
        }}
        .stButton > button:hover {{
            background-color: #1e40af;
            box-shadow: 0 4px 12px rgba(30, 58, 138, 0.15);
        }}

        /* 데이터 테이블 정제 */
        .center-table {{ width: 100%; text-align: center !important; border-collapse: collapse; }}
        .center-table th {{ background-color: #F8FAFC !important; color: #1E3A8A !important; text-align: center !important; padding: 12px !important; font-size: {CONTENT_FONT_SIZE}; border-bottom: 2px solid #E2E8F0; }}
        .center-table td {{ text-align: center !important; padding: 12px !important; border-bottom: 1px solid #F1F5F9; font-size: {CONTENT_FONT_SIZE}; }}

        /* 섹션 헤더 디자인 */
        .custom-header {{ 
            font-size: {TITLE_FONT_SIZE} !important; 
            font-weight: 700; 
            color: #1E3A8A; 
            margin-bottom: 16px; 
            border-left: 4px solid #1E3A8A; 
            padding-left: 12px; 
        }}
        
        /* 모바일 최적화 여백 */
        @media (max-width: 768px) {{
            .stTabs [data-baseweb="tab-list"] {{ gap: 10px; padding: 0px 5px; }}
            .custom-header {{ font-size: 14px !important; }}
        }}
    </style>
""", unsafe_allow_html=True)

# --- 1. 초기 DB 설정 ---
def init_db():
    conn = sqlite3.connect("customs_master.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS hs_master (hs_code TEXT, name_kr TEXT, name_en TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS standard_names (hs_code TEXT, base_name TEXT, std_name_kr TEXT, std_name_en TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS rates (hs_code TEXT, type TEXT, rate TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS rate_names (code TEXT, h_name TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS req_import (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS req_export (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_gani (gani_hs TEXT, gani_name TEXT, rate TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_reduction (code TEXT, content TEXT, rate TEXT, after_target TEXT, installment_months TEXT, installment_count TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_vat_exemption (name TEXT, type_name TEXT, code TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_internal_tax (item_name TEXT, tax_rate TEXT, type_code TEXT, type_name TEXT, tax_kind_code TEXT, unit TEXT, tax_base_price TEXT, agri_tax_yn TEXT)")
    conn.commit(); conn.close()

    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)")
    admin_id = "aegis01210"; admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    conn_auth.commit(); conn_auth.close()

init_db()

# Gemini API
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 관리 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    st.markdown("<div style='text-align:center; padding-top:100px;'><h1 style='color:#1E3A8A; font-size:48px; font-weight:800; letter-spacing:-1.5px;'>AEGIS</h1><p style='color:#64748B; font-size:18px;'>Customs Data Intelligence</p></div>", unsafe_allow_html=True)
    cl1, cl2, cl3 = st.columns([1, 1.4, 1])
    with cl2:
        with st.container():
            l_id = st.text_input("아이디", placeholder="아이디를 입력하세요")
            l_pw = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
            if st.button("로그인", use_container_width=True):
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

# --- 3. 메인 인터페이스 ---
st.sidebar.markdown(f"### 👤 {st.session_state.user_id}")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관", "🧮 세액계산"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

def display_hsk_details(hsk_code, prob=""):
    code_clean = re.sub(r'[^0-9]', '', str(hsk_code)).zfill(10)
    conn = sqlite3.connect("customs_master.db")
    master = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{code_clean}'", conn)
    conn.close()
    if not master.empty:
        st.success(f"✅ [{code_clean}] {master['name_kr'].values[0]} {f'({prob})' if prob else ''}")

# --- [Tab 1] HS검색 ---
with tabs[0]:
    st.markdown("<div class='custom-header'>HS코드 AI 분석</div>", unsafe_allow_html=True)
    with st.container():
        col_a, col_b = st.columns([2, 1])
        with col_a: u_input = st.text_input("품명/용도/성분/재질 정보 입력", key="hs_q", placeholder="예: 무선 헤드폰, 리튬이온 배터리 등")
        with col_b: u_img = st.file_uploader("제품 사진 업로드", type=["jpg", "png", "jpeg"], key="hs_i")
    
    if st.button("분석 실행", use_container_width=True, type="primary"):
        if u_img or u_input:
            with st.spinner("AI 관세사가 분류 사례를 분석 중입니다..."):
                try:
                    prompt = f"전문 관세사로서 다음 정보를 분석하여 HSK 10자리와 근거를 제시하세요: {u_input}"
                    content = [prompt]
                    if u_img: content.append(Image.open(u_img))
                    res = model.generate_content(content)
                    st.markdown("### 📋 분석 리포트")
                    st.write(res.text)
                    codes = re.findall(r'\d{10}', res.text)
                    if "100%" in res.text and codes: display_hsk_details(codes[0], "100%")
                except Exception as e: st.error(f"오류: {e}")

# --- [Tab 2] HS정보 ---
with tabs[1]:
    st.markdown("<div class='custom-header'>HS 통합 데이터 조회</div>", unsafe_allow_html=True)
    target_hs = st.text_input("HSK 10자리", placeholder="예: 0101211000", key="hs_info_input")
    if st.button("통합 조회 실행", use_container_width=True):
        if target_hs:
            hsk = re.sub(r'[^0-9]', '', target_hs).zfill(10)
            conn = sqlite3.connect("customs_master.db")
            m = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{hsk}'", conn)
            r_query = f"SELECT r.type as '코드', n.h_name as '세율명칭', r.rate as '세율' FROM rates r LEFT JOIN rate_names n ON r.type = n.code WHERE r.hs_code = '{hsk}'"
            r_all = pd.read_sql(r_query, conn)
            conn.close()
            if not m.empty:
                st.info(f"**[{hsk}]** {m['name_kr'].values[0]}")
                st.dataframe(r_all, hide_index=True, use_container_width=True)
            else: st.error("정보 없음")

# --- [Tab 3] 통계부호 ---
with tabs[2]:
    st.markdown("<div class='custom-header'>📊 2026 통계부호 통합 검색</div>", unsafe_allow_html=True)
    stat_tables = {"간이세율(2026)": "stat_gani", "관세감면부호(2026)": "stat_reduction", "내국세면세부호(2026)": "stat_vat_exemption", "내국세율(2026)": "stat_internal_tax"}
    c1, c2 = st.columns([1, 2])
    with c1: sel_name = st.selectbox("항목 선택", ["선택하세요"] + list(stat_tables.keys()), key="stat_sel_v2")
    with c2: search_kw = st.text_input("검색어", placeholder="품명 또는 내용 입력", key="stat_kw_v2")
    
    if st.button("조회 실행", use_container_width=True) and sel_name != "선택하세요":
        conn = sqlite3.connect("customs_master.db"); tbl = stat_tables[sel_name]
        if sel_name == "간이세율(2026)":
            df = pd.read_sql(f"SELECT gani_name as '간이품명', gani_hs as '간이HS부호', rate as '세율' FROM {tbl} WHERE gani_name LIKE '%{search_kw}%'", conn)
            if not df.empty: df['세율'] = df['세율'].astype(str) + "%"
        elif sel_name == "관세감면부호(2026)":
            df = pd.read_sql(f"SELECT content as '조항내용', code as '코드', rate as '감면율', installment_months, installment_count FROM {tbl} WHERE content LIKE '%{search_kw}%'", conn)
            if not df.empty:
                df['감면율'] = df['감면율'].astype(str) + "%"
                df['분납개월'] = df['installment_months'].apply(lambda x: str(x) if str(x) not in ['0', '0.0'] else "")
                df = df.drop(columns=['installment_months', 'installment_count'])
        elif sel_name == "내국세율(2026)":
            df = pd.read_sql(f"SELECT item_name as '신고품명', tax_rate as '내국세율' FROM {tbl} WHERE item_name LIKE '%{search_kw}%'", conn)
            if not df.empty: df['내국세율'] = df['내국세율'].astype(str) + "%"
        else: df = pd.read_sql(f"SELECT * FROM {tbl} WHERE name LIKE '%{search_kw}%'", conn)
        conn.close()
        st.dataframe(df, hide_index=True, use_container_width=True)

# --- [Tab 4] 화물통관 ---
with tabs[3]:
    st.markdown("<div class='custom-header'>📦 실시간 화물통관 정보</div>", unsafe_allow_html=True)
    CR_API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
    col1, col2 = st.columns([1, 3])
    with col1: year = st.selectbox("입항년도", [2026, 2025, 2024], index=0)
    with col2: bl = st.text_input("B/L 번호")
    if st.button("조회", use_container_width=True) and bl:
        st.info("Uni-Pass 서버 연결 중...")

# --- [Tab 5] 세액계산 ---
with tabs[4]:
    st.markdown("<div class='custom-header'>🧮 수입물품 예상 세액계산기</div>", unsafe_allow_html=True)
    if "duty_rate_widget" not in st.session_state: st.session_state["duty_rate_widget"] = 8.0
    
    with st.container():
        c1, c2 = st.columns(2)
        with c1:
            price = st.number_input("물품가격 (외화)", min_value=0.0)
            ex_rate = st.number_input("적용 환율", value=1350.0)
        with c2:
            st.write("품목 선택")
            hs_in = st.text_input("HS Code 입력")
            if st.button("세율 적용"): st.toast("세율이 반영되었습니다.")
        
        applied_duty = st.number_input("관세율 (%)", value=st.session_state["duty_rate_widget"])
        cif = int(price * ex_rate)
        
    if st.button("계산 실행", use_container_width=True, type="primary"):
        duty = int(cif * (applied_duty/100))
        vat = int((cif + duty) * 0.1)
        st.markdown(f"<div style='font-size: 24px; font-weight: bold; color: #B91C1C; text-align: right; background-color: #FEF2F2; padding: 20px; border-radius: 8px; border: 1px solid #FCA5A5;'>💰 예상세액: {duty+vat:,.0f} 원</div>", unsafe_allow_html=True)
        res_df = pd.DataFrame({"세종": ["관세", "부가세"], "세액(원)": [f"{duty:,.0f}", f"{vat:,.0f}"]})
        st.write(res_df.to_html(index=False, classes='center-table'), unsafe_allow_html=True)

# --- [Tab 6] 관리자 ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.markdown("<div class='custom-header'>⚙️ 데이터 관리 센터</div>", unsafe_allow_html=True)
        m_list = ["HS코드(마스터)", "표준품명", "관세율", "관세율구분"]
        stat_list = ["간이세율(2026)", "관세감면부호(2026)", "내국세면세부호(2026)", "내국세율(2026)"]
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            st.subheader("📁 마스터 데이터")
            for m in m_list: st.file_uploader(m, type="csv", key=f"ad_{m}")
        with col_m2:
            st.subheader("📊 통계부호 데이터")
            for s in stat_list: st.file_uploader(s, type="csv", key=f"ad_{s}")

# --- 하단 푸터 (복구 완료) ---
st.divider()
f1, f2, f3, f4 = st.columns([2.5, 1, 1, 1])
with f1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with f2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with f3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with f4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")
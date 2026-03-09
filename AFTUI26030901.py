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

# --- [AFTUI26030901] 전역 스타일 설정 ---
st.set_page_config(page_title="AEGIS - 전문 관세 행정 서비스", layout="wide")

TITLE_FONT_SIZE = "18px"
CONTENT_FONT_SIZE = "14px"

st.markdown(f"""
    <style>
        /* 기본 폰트 및 배경 */
        @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');
        * {{ font-family: 'Pretendard', sans-serif; }}
        .stApp {{ background-color: #F8FAFC; }}

        /* 탭 디자인 커스텀 (엘박스 스타일) */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 20px;
            background-color: #FFFFFF;
            padding: 10px 20px;
            border-radius: 10px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }}
        .stTabs [data-baseweb="tab"] {{
            height: 45px;
            background-color: transparent;
            border: none;
            color: #64748B;
            font-weight: 500;
        }}
        .stTabs [aria-selected="true"] {{
            color: #1E3A8A !important;
            border-bottom: 3px solid #1E3A8A !important;
        }}

        /* 컨테이너 카드 UI */
        div[data-testid="stVerticalBlock"] > div:has(div.stExpander), .stContainer {{
            background-color: white;
            border-radius: 12px;
            padding: 20px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
            margin-bottom: 20px;
        }}
        
        /* 버튼 스타일 최적화 */
        .stButton > button {{
            background-color: #1E3A8A;
            color: white;
            border-radius: 8px;
            border: none;
            padding: 10px 20px;
            font-weight: 600;
            width: 100%;
        }}
        .stButton > button:hover {{
            background-color: #1e40af;
            box-shadow: 0 4px 12px rgba(30, 58, 138, 0.2);
        }}

        /* 중앙 정렬 테이블 CSS */
        .center-table {{ width: 100%; text-align: center !important; border-collapse: collapse; }}
        .center-table th {{ background-color: #F8FAFC !important; color: #1E3A8A !important; text-align: center !important; padding: 12px !important; border-bottom: 2px solid #E2E8F0; }}
        .center-table td {{ text-align: center !important; padding: 10px !important; border-bottom: 1px solid #F1F5F9; font-size: {CONTENT_FONT_SIZE}; }}

        /* 섹션 헤더 */
        .custom-header {{ font-size: {TITLE_FONT_SIZE} !important; font-weight: bold; color: #1E3A8A; margin-bottom: 15px; border-left: 5px solid #1E3A8A; padding-left: 12px; }}
    </style>
""", unsafe_allow_html=True)

# --- 1. 초기 DB 설정 ---
def init_db():
    conn = sqlite3.connect("customs_master.db")
    c = conn.cursor()
    # 기본 마스터 테이블
    c.execute("CREATE TABLE IF NOT EXISTS hs_master (hs_code TEXT, name_kr TEXT, name_en TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS standard_names (hs_code TEXT, base_name TEXT, std_name_kr TEXT, std_name_en TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS rates (hs_code TEXT, type TEXT, rate TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS rate_names (code TEXT, h_name TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS req_import (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS req_export (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    # 탭3 통계부호 테이블
    c.execute("CREATE TABLE IF NOT EXISTS stat_gani (gani_hs TEXT, gani_name TEXT, rate TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_reduction (code TEXT, content TEXT, rate TEXT, after_target TEXT, installment_months TEXT, installment_count TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_vat_exemption (name TEXT, type_name TEXT, code TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS stat_internal_tax (item_name TEXT, tax_rate TEXT, type_code TEXT, type_name TEXT, tax_kind_code TEXT, unit TEXT, tax_base_price TEXT, agri_tax_yn TEXT)")
    conn.commit(); conn.close()

    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)")
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", ("aegis01210", admin_pw))
    conn_auth.commit(); conn_auth.close()

init_db()

# Gemini 설정
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 로직 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    st.markdown("<div style='text-align:center; padding-top: 80px;'><h1 style='color:#1E3A8A; font-size:40px;'>AEGIS</h1><p style='color:#64748B;'>Professional Customs Data Portal</p></div>", unsafe_allow_html=True)
    cl1, cl2, cl3 = st.columns([1, 1.5, 1])
    with cl2:
        with st.form("login_form"):
            l_id = st.text_input("아이디")
            l_pw = st.text_input("비밀번호", type="password")
            if st.form_submit_button("로그인"):
                conn = sqlite3.connect("users.db")
                res = conn.execute("SELECT is_approved, is_admin FROM users WHERE id=? AND pw=?", 
                                   (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
                conn.close()
                if res and res[0] == 1:
                    st.session_state.logged_in = True
                    st.session_state.user_id = l_id
                    st.session_state.is_admin = bool(res[1])
                    st.rerun()
                else: st.error("로그인 정보가 올바르지 않거나 승인 대기 중입니다.")
    st.stop()

# --- 3. 메인 인터페이스 ---
st.sidebar.markdown(f"### 👤 {st.session_state.user_id} 관세사님")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관", "🧮 세액계산"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 ---
with tabs[0]:
    st.markdown("<div class='custom-header'>🔍 AI 기반 품목분류 분석</div>", unsafe_allow_html=True)
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("분석할 품명 또는 물품 정보를 입력하세요", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"])
    
    if st.button("분석 실행", use_container_width=True, type="primary"):
        if u_input or u_img:
            with st.spinner("AI가 사례를 분석하고 있습니다..."):
                try:
                    content = [f"관세사 입장에서 다음 정보를 분석하여 HSK 10자리와 근거를 제시하세요: {u_input}"]
                    if u_img: content.append(Image.open(u_img))
                    res = model.generate_content(content)
                    st.markdown("<div style='background:white; padding:20px; border-radius:10px; border:1px solid #E2E8F0;'>", unsafe_allow_html=True)
                    st.write(res.text)
                    st.markdown("</div>", unsafe_allow_html=True)
                except Exception as e: st.error(f"분석 오류: {e}")

# --- [Tab 2] HS정보 ---
with tabs[1]:
    st.markdown("<div class='custom-header'>📘 HSK 통합 정보 조회</div>", unsafe_allow_html=True)
    target_hs = st.text_input("조회할 HSK 10자리", placeholder="예: 8708290000")
    if st.button("정보 통합 조회", use_container_width=True):
        if target_hs:
            hsk = re.sub(r'[^0-9]', '', target_hs).zfill(10)
            conn = sqlite3.connect("customs_master.db")
            m = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{hsk}'", conn)
            r_all = pd.read_sql(f"SELECT r.type as '코드', n.h_name as '세율명칭', r.rate as '세율' FROM rates r LEFT JOIN rate_names n ON r.type = n.code WHERE r.hs_code = '{hsk}'", conn)
            conn.close()
            if not m.empty:
                st.info(f"**[{hsk}]** {m['name_kr'].values[0]}")
                st.dataframe(r_all, hide_index=True, use_container_width=True)
            else: st.error("데이터가 존재하지 않습니다.")

# --- [Tab 3] 통계부호 ---
with tabs[2]:
    st.markdown("<div class='custom-header'>📊 통계부호 통합 검색</div>", unsafe_allow_html=True)
    stat_tables = {"간이세율(2026)": "stat_gani", "관세감면부호(2026)": "stat_reduction", "내국세면세부호(2026)": "stat_vat_exemption", "내국세율(2026)": "stat_internal_tax"}
    c1, c2 = st.columns([1, 2])
    with c1: sel_name = st.selectbox("분류 선택", ["선택하세요"] + list(stat_tables.keys()))
    with c2: search_kw = st.text_input("검색 키워드")
    
    if st.button("부호 조회", use_container_width=True) and sel_name != "선택하세요":
        conn = sqlite3.connect("customs_master.db"); tbl = stat_tables[sel_name]
        if sel_name == "간이세율(2026)":
            df = pd.read_sql(f"SELECT gani_name as '간이품명', gani_hs as '간이HS부호', rate as '세율' FROM {tbl} WHERE gani_name LIKE '%{search_kw}%'", conn)
            if not df.empty: df['세율'] = df['세율'].astype(str) + "%"
        elif sel_name == "관세감면부호(2026)":
            df = pd.read_sql(f"SELECT content as '관세감면분납조항내용', code as '관세감면분납코드', rate as '관세감면율', after_target as '사후관리대상여부', installment_months, installment_count FROM {tbl} WHERE content LIKE '%{search_kw}%'", conn)
            if not df.empty:
                df['관세감면율'] = df['관세감면율'].astype(str) + "%"
                df['분납개월수'] = df['installment_months'].apply(lambda x: str(x) if str(x) not in ['0', '0.0'] else "")
                df['분납횟수'] = df['installment_count'].apply(lambda x: str(x) if str(x) not in ['0', '0.0'] else "")
                df = df.drop(columns=['installment_months', 'installment_count'])
        elif sel_name == "내국세율(2026)":
            df = pd.read_sql(f"SELECT item_name as '신고품명', tax_rate as '내국세율', type_code as '내국세율구분코드', type_name as '내국세율구분코드명', tax_kind_code as '내국세세종코드', unit as '금액기준중수량단위', tax_base_price as '개소세과세기준가격', agri_tax_yn as '농특세과세여부' FROM {tbl} WHERE item_name LIKE '%{search_kw}%'", conn)
            if not df.empty: df['내국세율'] = df['내국세율'].astype(str) + "%"
        else: df = pd.read_sql(f"SELECT * FROM {tbl} WHERE name LIKE '%{search_kw}%'", conn)
        conn.close()
        st.dataframe(df, hide_index=True, use_container_width=True)

# --- [Tab 4] 화물통관 ---
with tabs[3]:
    st.markdown("<div class='custom-header'>📦 화물통관 진행정보</div>", unsafe_allow_html=True)
    CR_API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
    col1, col2 = st.columns([1, 3])
    with col1: year = st.selectbox("입항년도", [2026, 2025, 2024])
    with col2: bl = st.text_input("B/L 번호")
    if st.button("실시간 조회", use_container_width=True) and bl:
        st.info("관세청 유니패스 서버 연결 중...")

# --- [Tab 5] 세액계산 ---
with tabs[4]:
    st.markdown("<div class='custom-header'>🧮 수입물품 예상 세액계산기</div>", unsafe_allow_html=True)
    if "duty_rate_widget" not in st.session_state: st.session_state["duty_rate_widget"] = 8.0
    
    with st.container():
        c1, c2 = st.columns(2)
        with c1:
            price = st.number_input("물품가격 (외화)", min_value=0.0)
            ex_rate = st.number_input("환율", value=1350.0)
        with c2:
            st.write("품목 적용")
            hs_in = st.text_input("HS Code")
            if st.button("적용"):
                st.session_state["duty_rate_widget"] = 8.0; st.rerun()
        
        applied_duty = st.number_input("관세율 (%)", value=st.session_state["duty_rate_widget"], key="d_widget")
        cif = int(price * ex_rate)
        
    if st.button("계산 실행", use_container_width=True, type="primary"):
        duty = int(cif * (applied_duty/100))
        vat = int((cif + duty) * 0.1)
        st.markdown(f"<div style='font-size: 24px; font-weight: bold; color: #B91C1C; text-align: right; background-color: #FEF2F2; padding: 20px; border-radius: 10px; border: 1px solid #FCA5A5;'>💰 예상세액: {duty+vat:,.0f} 원</div>", unsafe_allow_html=True)
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

# 푸터
st.markdown("---")
f1, f2, f3 = st.columns([2, 1, 1])
with f1: st.write("📞 010-8859-0403 (이지스 관세사무소)")
with f2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with f3: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")
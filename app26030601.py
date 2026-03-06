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

# --- 전역 설정 및 폰트 사양 ---
TITLE_FONT_SIZE = "15px"
CONTENT_FONT_SIZE = "12px"
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/xml"
}

# --- 1. 초기 DB 설정 ---
def init_db():
    # 사용자 관리 DB
    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, name, is_approved, is_admin) VALUES (?, ?, ?, 1, 1)", 
                      ("aegis01210", admin_pw, "관리자"))
    conn_auth.commit()
    conn_auth.close()

    # HS 마스터 DB (Tab 2용 유지)
    conn = sqlite3.connect("customs_master.db")
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS hs_master (hs_code TEXT, name_kr TEXT, name_en TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS standard_names (hs_code TEXT, base_name TEXT, std_name_kr TEXT, std_name_en TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS rates (hs_code TEXT, type TEXT, rate TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS rate_names (code TEXT, h_name TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS req_import (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    c.execute("CREATE TABLE IF NOT EXISTS req_export (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    # (주의) Tab 3 API화로 인해 stat_codes 테이블 생성 로직은 생략/삭제합니다.
    conn.commit()
    conn.close()

init_db()

# Gemini AI 설정
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
        else: st.error("정보 불일치 또는 승인 대기")
    st.stop()

# --- 3. 메인 화면 ---
st.sidebar.write(f"✅ {st.session_state.user_name} 접속 중")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관진행정보", "🧮 세액계산기", "⚙️ 관리자"])

# --- [Tab 1] HS검색 (성공 로직 고정) ---
with tabs[0]:
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("품명/물품정보(용도/기능/성분/재질) 입력", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"], key="hs_i")
    if u_img: st.image(Image.open(u_img), caption="📸 분석 대상 이미지", width=300)
    if st.button("HS분석 실행", use_container_width=True):
        if u_img or u_input:
            with st.spinner("분석 중..."):
                try:
                    prompt = f"""당신은 전문 관세사입니다. 아래 지침에 따라 HS코드를 분류하고 리포트를 작성하세요.
                    1. 품명: (유저입력 '{u_input}' 참고하여 예상 품명 제시)
                    2. 추천결과:
                       - 1순위가 100%인 경우: "1순위 [코드] 100%"만 출력하고 종료.
                       - 미확정인 경우: 상위 3순위까지 추천하되 3순위가 낮으면 2순위까지만.
                       - 형식: "n순위 [코드] [확률]%" """
                    content = [prompt]
                    if u_img: content.append(Image.open(u_img))
                    if u_input: content.append(f"상세 정보: {u_input}")
                    res = model.generate_content(content)
                    st.markdown("### 📋 분석 리포트"); st.write(res.text)
                except Exception as e: st.error(f"오류: {e}")

# --- [Tab 2] HS정보 (기존 DB 방식 유지) ---
with tabs[1]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📘 HS 상세 정보 (이지스 DB)</div>", unsafe_allow_html=True)
    target_hs = st.text_input("HSK 10자리 입력", placeholder="예: 0101211000", key="hs_info_db")
    if st.button("통합 조회", use_container_width=True):
        if target_hs:
            hsk = re.sub(r'[^0-9]', '', target_hs).zfill(10)
            conn = sqlite3.connect("customs_master.db")
            m = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{hsk}'", conn)
            std = pd.read_sql(f"SELECT base_name, std_name_kr, std_name_en FROM standard_names WHERE hs_code = '{hsk}'", conn)
            r_query = f"SELECT r.type as '코드', n.h_name as '세율명칭', r.rate as '세율' FROM rates r LEFT JOIN rate_names n ON r.type = n.code WHERE r.hs_code = '{hsk}'"
            r_all = pd.read_sql(r_query, conn)
            req_i = pd.read_sql(f"SELECT law as '법령', agency as '기관', document as '서류' FROM req_import WHERE hs_code = '{hsk}'", conn)
            conn.close()
            if not m.empty:
                st.info(f"✅ HS {hsk} 조회 결과")
                col_s, col_b = st.columns(2)
                with col_s: st.write("**표준품명**"); st.caption(f"{std['std_name_kr'].values[0]}" if not std.empty else "정보없음")
                with col_b: st.write("**기본품명**"); st.caption(f"{m['name_kr'].values[0]}")
                st.divider()
                st.write("**💰 관세율**"); st.dataframe(r_all, hide_index=True, use_container_width=True)
                st.write("**🛡️ 수입요건**"); st.dataframe(req_i, hide_index=True, use_container_width=True)
            else: st.warning("DB에 정보가 없습니다.")

# --- [Tab 3] 통계부호 (실시간 API 전환 - DB 로직 완전 제거) ---
with tabs[2]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📊 실시간 통계부호 검색 (Uni-Pass API)</div>", unsafe_allow_html=True)
    STAT_KEY = st.secrets.get("STAT_API_KEY", "").strip()
    
    # 가이드북(API019) 기반 통계부호구분코드
    clft_dict = {"관세감면/분납부호": "A01", "내국세율부호": "A04", "용도부호": "A05", "보세구역부호": "A08"}
    col1, col2 = st.columns([1, 2])
    with col1: sel_clft = st.selectbox("분류 선택", list(clft_dict.keys()))
    with col2: kw = st.text_input("검색 키워드(한글내역)", placeholder="예: 정밀전자")
    
    if st.button("부호 실시간 검색", use_container_width=True):
        with st.spinner("관세청 코드 조회 중..."):
            # 가이드북 URL 및 파라미터 적용 (statsSgnclftCd 필수)
            url = "https://unipass.customs.go.kr:38010/ext/rest/statsSgnQry/retrieveStatsSgnBrkd"
            params = {"crkyCn": STAT_KEY, "statsSgnclftCd": clft_dict[sel_clft]}
            try:
                res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
                root = ET.fromstring(res.content)
                codes = root.findall(".//statsSgnQryVo")
                if codes:
                    res_list = []
                    for c in codes:
                        name = c.findtext("koreBrkd")
                        if not kw or kw in name:
                            res_list.append({
                                "통계부호": c.findtext("statsSgn"),
                                "한글내역": name,
                                "내국세율/비고": c.findtext("itxRt")
                            })
                    if res_list:
                        st.dataframe(pd.DataFrame(res_list).style.set_properties(**{'font-size': '12px'}), hide_index=True, use_container_width=True)
                    else: st.warning("검색 결과가 없습니다.")
                else: st.warning("서버 응답 결과가 없습니다. 인증키 승인을 확인하세요.")
            except Exception as e: st.error(f"API 연결 실패: {e}")

# --- [Tab 4] 화물통관진행정보 (성공 로직 고정) ---
with tabs[3]:
    st.subheader("📦 실시간 화물통관 진행정보 조회")
    CR_API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
    if not CR_API_KEY: st.error("API 키 미설정"); st.stop()
    col1, col2, col3 = st.columns([1.5, 3, 1])
    with col1: carg_year = st.selectbox("입항년도", [2026, 2025, 2024, 2023], index=0)
    with col2: bl_no = st.text_input("B/L 번호 입력", placeholder="HBL/MBL 번호", key="bl_final_v3")
    with col3: st.write(""); search_btn = st.button("실시간 조회", use_container_width=True)
    if search_btn and bl_no:
        with st.spinner("조회 중..."):
            url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
            params = {"crkyCn": CR_API_KEY, "blYy": str(carg_year), "hblNo": bl_no.strip().upper()}
            try:
                response = requests.get(url, params=params, timeout=30)
                root = ET.fromstring(response.content)
                info = root.find(".//cargCsclPrgsInfoQryVo")
                if info is not None:
                    status = info.findtext('prgsStts')
                    st.success(f"✅ 상태: {status}")
                    m1, m2, m3 = st.columns(3)
                    m1.metric("진행상태", status)
                    m2.metric("품명", info.findtext("prnm")[:12] if info.findtext("prnm") else "-")
                    m3.metric("중량", f"{info.findtext('ttwg')} {info.findtext('wghtUt')}")
                    st.markdown("---")
                    history = [{"단계": i.findtext("cargTrcnRelaBsopTpcd"), "일시": i.findtext("prcsDttm"), "내용": i.findtext("shedNm") or i.findtext("rlbrCn")} for i in root.findall(".//cargCsclPrgsInfoDtlQryVo")]
                    st.dataframe(pd.DataFrame(history), hide_index=True, use_container_width=True)
            except Exception as e: st.error(f"API 호출 실패: {e}")

# --- [Tab 6] 관리자 (사용자 승인 및 Tab 2용 DB 관리) ---
if st.session_state.is_admin:
    with tabs[5]:
        st.header("⚙️ 관리자 데이터 센터")
        # 사용자 승인 관리
        st.subheader("👤 계정 승인")
        conn_u = sqlite3.connect("users.db")
        users = pd.read_sql("SELECT id, name, is_approved FROM users", conn_u)
        st.dataframe(users, hide_index=True)
        target_id = st.text_input("승인할 ID")
        if st.button("승인 실행"):
            conn_u.execute("UPDATE users SET is_approved=1 WHERE id=?", (target_id,))
            conn_u.commit(); conn_u.close(); st.rerun()
        
        st.divider()
        # Tab 2용 HS DB 업로드 메뉴
        st.subheader("📁 HS 마스터 데이터 관리 (Tab 2용)")
        m_list = ["HS코드(마스터)", "표준품명", "관세율", "세관장확인"]
        for m_name in m_list:
            up = st.file_uploader(f"{m_name} CSV", type="csv", key=f"up_{m_name}")
            if up and st.button(f"{m_name} 반영"):
                df = pd.read_csv(up, encoding='utf-8-sig')
                conn = sqlite3.connect("customs_master.db")
                tbl_map = {"HS코드(마스터)": "hs_master", "표준품명": "standard_names", "관세율": "rates", "세관장확인": "req_import"}
                df.to_sql(tbl_map[m_name], conn, if_exists='replace', index=False)
                conn.close(); st.success(f"{m_name} 완료")

# --- 하단 푸터 (고정) ---
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")
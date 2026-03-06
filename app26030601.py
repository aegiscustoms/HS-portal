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

# --- 전역 설정 ---
TITLE_FONT_SIZE = "15px"
CONTENT_FONT_SIZE = "12px"
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/xml"
}

# --- 1. 초기 DB 설정 (사용자 관리용) ---
def init_db():
    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    # 관리자 계정 생성
    admin_id = "aegis01210"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, name, is_approved, is_admin) VALUES (?, ?, ?, 1, 1)", 
                      (admin_id, admin_pw, "관리자"))
    conn_auth.commit()
    conn_auth.close()

init_db()

# Gemini API 설정
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 및 회원가입 섹션 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    st.title("🔐 AEGIS 서비스 로그인")
    menu = ["로그인", "회원가입"]
    choice = st.radio("메뉴 선택", menu, horizontal=True)

    if choice == "로그인":
        l_id = st.text_input("아이디")
        l_pw = st.text_input("비밀번호", type="password")
        if st.button("로그인"):
            conn = sqlite3.connect("users.db")
            res = conn.execute("SELECT is_approved, is_admin, name FROM users WHERE id=? AND pw=?", 
                               (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
            conn.close()
            if res:
                if res[0] == 1:
                    st.session_state.logged_in = True
                    st.session_state.user_id = l_id
                    st.session_state.user_name = res[2]
                    st.session_state.is_admin = bool(res[1])
                    st.rerun()
                else: st.warning("승인 대기 중인 계정입니다.")
            else: st.error("아이디 또는 비밀번호가 틀렸습니다.")
    
    else:
        new_id = st.text_input("가입할 아이디")
        new_name = st.text_input("성함")
        new_pw = st.text_input("가입할 비밀번호", type="password")
        if st.button("회원가입 신청"):
            if new_id and new_pw:
                try:
                    conn = sqlite3.connect("users.db")
                    conn.execute("INSERT INTO users (id, pw, name, is_approved, is_admin) VALUES (?, ?, ?, 0, 0)",
                                 (new_id, hashlib.sha256(new_pw.encode()).hexdigest(), new_name))
                    conn.commit()
                    conn.close()
                    st.success("가입 신청 완료! 관리자 승인 후 이용 가능합니다.")
                except: st.error("이미 존재하는 아이디입니다.")
    st.stop()

# --- 3. 메인 화면 구성 ---
st.sidebar.write(f"✅ {st.session_state.user_name}님 접속 중")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관진행정보", "🧮 세액계산기"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 (Gemini AI) ---
with tabs[0]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>🔍 AI 품목분류 분석</div>", unsafe_allow_html=True)
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("물품 정보(용도/재질 등) 입력", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 분석", type=["jpg", "png", "jpeg"], key="hs_i")
    if st.button("AI 분석 실행", use_container_width=True):
        with st.spinner("분석 중..."):
            try:
                prompt = f"당신은 전문 관세사입니다. 물품 '{u_input}'을 분석하여 HSK 10자리를 추천하고 분류 근거를 제시하세요."
                content = [prompt]
                if u_img: content.append(Image.open(u_img))
                res = model.generate_content(content)
                st.markdown("### 📋 AI 리포트"); st.write(res.text)
            except Exception as e: st.error(f"오류: {e}")

# --- [Tab 2] HS정보 (실시간 관세율 API) ---
with tabs[1]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📘 실시간 관세율 정보 (Uni-Pass)</div>", unsafe_allow_html=True)
    RATE_KEY = st.secrets.get("RATE_API_KEY", "").strip()
    target_hs = st.text_input("HS코드 10자리 입력", placeholder="예: 8517130000", key="hs_rate_api")
    if st.button("실시간 관세율 조회", use_container_width=True):
        if target_hs:
            with st.spinner("조회 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/itemRateQry/retrieveItemRate"
                params = {"crkyCn": RATE_KEY, "hsCd": target_hs.strip()}
                try:
                    res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
                    root = ET.fromstring(res.content)
                    items = root.findall(".//itemRateQryVo")
                    if items:
                        data = [{"구분": i.findtext("tarfClsfCd"), "세율명칭": i.findtext("tarfNm"), "세율": f"{i.findtext('itrt')}%"} for i in items]
                        st.dataframe(pd.DataFrame(data), hide_index=True, use_container_width=True)
                    else: st.warning("조회된 데이터가 없습니다.")
                except Exception as e: st.error(f"API 연결 오류: {e}")

# --- [Tab 3] 통계부호 (실시간 공통코드 API) ---
with tabs[2]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📊 실시간 통계부호 검색</div>", unsafe_allow_html=True)
    STAT_KEY = st.secrets.get("STAT_API_KEY", "").strip()
    clft_dict = {"관세감면": "001", "내국세면세": "002", "보세구역": "003", "세관부호": "004"}
    col1, col2 = st.columns([1, 2])
    with col1: sel_clft = st.selectbox("부호 분류", list(clft_dict.keys()))
    with col2: kw = st.text_input("검색 키워드", placeholder="예: 인천")
    if st.button("부호 실시간 검색", use_container_width=True):
        url = "https://unipass.customs.go.kr:38010/ext/rest/cmmnCdQry/retrieveCmmnCd"
        params = {"crkyCn": STAT_KEY, "clftCd": clft_dict[sel_clft]}
        try:
            res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
            root = ET.fromstring(res.content)
            codes = root.findall(".//cmmnCdQryVo")
            res_list = [{"코드": c.findtext("cd"), "명칭": c.findtext("cdNm")} for c in codes if not kw or (kw in c.findtext("cdNm") or kw in c.findtext("cd"))]
            st.dataframe(pd.DataFrame(res_list), hide_index=True, use_container_width=True)
        except Exception as e: st.error(f"API 오류: {e}")

# --- [Tab 4] 화물통관진행정보 (고정 로직) ---
with tabs[3]:
    st.subheader("📦 실시간 화물통관 진행정보 조회")
    CR_API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
    if not CR_API_KEY:
        st.error("⚠️ Streamlit Secrets에 'UNIPASS_API_KEY'가 설정되지 않았습니다."); st.stop()
    col1, col2, col3 = st.columns([1.5, 3, 1])
    with col1: carg_year = st.selectbox("입항년도", [2026, 2025, 2024, 2023], index=0)
    with col2: bl_no = st.text_input("B/L 번호 입력", placeholder="HBL 또는 MBL 번호", key="bl_final_v3")
    with col3: st.write(""); search_btn = st.button("실시간 조회", use_container_width=True)
    if search_btn:
        if not bl_no: st.warning("B/L 번호를 입력해 주세요.")
        else:
            with st.spinner("관세청 유니패스에서 데이터를 가져오는 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
                params = {"crkyCn": CR_API_KEY, "blYy": str(carg_year), "hblNo": bl_no.strip().upper()}
                try:
                    response = requests.get(url, params=params, timeout=30)
                    if response.status_code == 200:
                        root = ET.fromstring(response.content)
                        t_cnt = root.findtext(".//tCnt")
                        if t_cnt and int(t_cnt) > 0:
                            info = root.find(".//cargCsclPrgsInfoQryVo")
                            current_status = info.findtext('prgsStts')
                            st.success(f"✅ 화물 확인됨: {current_status}")
                            m1, m2, m3 = st.columns(3)
                            m1.metric("진행상태", current_status)
                            m2.metric("품명", info.findtext("prnm")[:12] if info.findtext("prnm") else "-")
                            m3.metric("중량", f"{info.findtext('ttwg')} {info.findtext('wghtUt')}")
                            st.markdown("---")
                            st.markdown(f"<div class='custom-text'><b>• 선박명:</b> {info.findtext('shipNm')}<br><b>• 입항일:</b> {info.findtext('etprDt')}<br><b>• MBL:</b> {info.findtext('mblNo')}</div>", unsafe_allow_html=True)
                            st.markdown("#### 🕒 처리 단계별 상세 이력")
                            history = [{"처리단계": i.findtext("cargTrcnRelaBsopTpcd"), "처리일시": i.findtext("prcsDttm"), "장소": i.findtext("shedNm") if i.findtext("shedNm") else i.findtext("rlbrCn")} for i in root.findall(".//cargCsclPrgsInfoDtlQryVo")]
                            st.dataframe(pd.DataFrame(history).style.set_properties(**{'font-size': '12px', 'text-align': 'center'}), hide_index=True, use_container_width=True)
                        else: st.warning("정보 없음")
                except Exception as e: st.error(f"연결 실패: {e}")

# --- [Tab 6] 관리자 페이지 (ID/PW 관리 전용) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.header("⚙️ 관리자: 사용자 계정 관리")
        conn = sqlite3.connect("users.db")
        users_df = pd.read_sql("SELECT id, name, is_approved, is_admin FROM users", conn)
        st.subheader("👤 사용자 목록 및 승인")
        for index, row in users_df.iterrows():
            col1, col2, col3 = st.columns([2, 1, 1])
            with col1: st.write(f"**{row['name']}** ({row['id']})")
            with col2:
                status = "승인완료" if row['is_approved'] == 1 else "미승인"
                if st.button(f"{status} 변경", key=f"app_{row['id']}"):
                    new_stat = 0 if row['is_approved'] == 1 else 1
                    conn.execute("UPDATE users SET is_approved=? WHERE id=?", (new_stat, row['id']))
                    conn.commit(); st.rerun()
            with col3:
                if st.button("삭제", key=f"del_{row['id']}"):
                    conn.execute("DELETE FROM users WHERE id=?", (row['id'],))
                    conn.commit(); st.rerun()
        conn.close()

# --- 하단 푸터 (고정) ---

st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")
import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import io

# --- 1. 초기 DB 설정 ---
def init_db():
    # 보안/회원 DB
    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, phone TEXT, 
                biz_name TEXT, biz_no TEXT, tax_email TEXT, 
                is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    # 관리자 계정 생성
    admin_id = "aegis01201"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn_auth.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    conn_auth.commit()
    conn_auth.close()

    # 관세/통계 DB
    conn_data = sqlite3.connect("customs_master.db")
    conn_data.execute("CREATE TABLE IF NOT EXISTS hs_master (hs_code TEXT, name_kr TEXT, name_en TEXT)")
    conn_data.execute("CREATE TABLE IF NOT EXISTS rates (hs_code TEXT, type TEXT, rate TEXT)")
    conn_data.execute("CREATE TABLE IF NOT EXISTS requirements (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    conn_data.execute("CREATE TABLE IF NOT EXISTS exemptions (code TEXT, description TEXT, rate TEXT)")
    conn_data.commit()
    conn_data.close()

init_db()

# Gemini API 설정 (오류 방지를 위해 모델 경로 명시)
genai.configure(api_key=st.secrets.get("GEMINI_KEY", "YOUR_API_KEY"))
model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 및 세션 관리 ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.is_admin = False

if not st.session_state.logged_in:
    choice = st.sidebar.selectbox("메뉴", ["로그인", "회원가입"])
    if choice == "로그인":
        st.title("🔐 AEGIS 서비스 로그인")
        l_id = st.text_input("아이디")
        l_pw = st.text_input("비밀번호", type="password")
        if st.button("로그인"):
            conn = sqlite3.connect("users.db")
            res = conn.execute("SELECT is_approved, is_admin FROM users WHERE id=? AND pw=?", 
                               (l_id, hashlib.sha256(l_pw.encode()).hexdigest())).fetchone()
            conn.close()
            if res:
                if res[0] == 1:
                    st.session_state.logged_in = True
                    st.session_state.user_id = l_id
                    st.session_state.is_admin = bool(res[1])
                    st.rerun()
                else: st.error("관리자 승인 대기 중입니다.")
            else: st.error("정보가 일치하지 않습니다.")
    else:
        st.title("📝 회원가입 신청")
        with st.form("signup"):
            c1, c2 = st.columns(2)
            with c1:
                new_id = st.text_input("아이디")
                new_pw = st.text_input("비밀번호", type="password")
                new_name = st.text_input("이름")
                new_phone = st.text_input("전화번호")
            with c2:
                b_name = st.text_input("상호")
                b_no = st.text_input("사업자번호")
                t_email = st.text_input("계산서 메일")
            if st.form_submit_button("가입 신청"):
                conn = sqlite3.connect("users.db")
                try:
                    conn.execute("INSERT INTO users (id, pw, name, phone, biz_name, biz_no, tax_email) VALUES (?,?,?,?,?,?,?)",
                                 (new_id, hashlib.sha256(new_pw.encode()).hexdigest(), new_name, new_phone, b_name, b_no, t_email))
                    conn.commit()
                    st.success("신청 완료! 관리자 승인 후 연락드리겠습니다.")
                except: st.error("이미 사용 중인 아이디입니다.")
                conn.close()
    st.stop()

# --- 3. 메인 앱 기능 ---
st.sidebar.write(f"✅ 접속중: {st.session_state.user_id}")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

# 탭 구성 (요청하신 순서 반영)
tab_names = ["🔍 HS검색", "📊 통계부호", "🌎 세계 HS/세율", "📜 FTA정보", "📦 화물통관진행정보", "🧮 세액계산기"]
if st.session_state.is_admin: tab_names.append("⚙️ 관리자")
tabs = st.tabs(tab_names)

# 공통 함수: DB 상세 조회
def display_hsk_details(hsk_code):
    code_clean = re.sub(r'[^0-9]', '', str(hsk_code))
    conn = sqlite3.connect("customs_master.db")
    master = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{code_clean}'", conn)
    rates = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{code_clean}'", conn)
    reqs = pd.read_sql(f"SELECT law, agency, document FROM requirements WHERE hs_code = '{code_clean}'", conn)
    conn.close()
    if not master.empty:
        st.success(f"✅ [{code_clean}] {master['name_kr'].values[0]}")
        c1, c2 = st.columns(2)
        with c1: st.write("**적용 세율**"); st.table(rates)
        with c2: st.write("**수입 요건**"); st.table(reqs)
    else: st.warning("DB에 해당 코드의 상세 정보가 없습니다.")

# --- [Tab 1] HS검색 ---
with tabs[0]:
    col1, col2 = st.columns([2, 1])
    with col1: u_input = st.text_input("HSK 10자리 또는 품명 입력", key="main_search")
    with col2: u_img = st.file_uploader("이미지 업로드", type=["jpg", "jpeg", "png"], key="main_img")
    
    if st.button("HS분석 실행"):
        if u_img:
            with st.spinner("AI가 이미지를 분석 중입니다..."):
                try:
                    img_data = Image.open(u_img)
                    prompt = "관세사로서 이 물품의 HSK 10자리를 제안하고 이유를 설명하세요. 마지막에 '추천코드: [숫자10자리]'를 포함하세요."
                    # 오류 방지: PIL 이미지를 직접 전달
                    response = model.generate_content([prompt, img_data])
                    st.write(response.text)
                    found = re.findall(r'\d{10}', response.text)
                    if found: display_hsk_details(found[0])
                except Exception as e: st.error(f"AI 분석 오류: {e}")
        elif u_input:
            if u_input.isdigit() and len(u_input) >= 4:
                display_hsk_details(u_input)
            else:
                conn = sqlite3.connect("customs_master.db")
                res = pd.read_sql(f"SELECT hs_code, name_kr FROM hs_master WHERE name_kr LIKE '%{u_input}%' LIMIT 10", conn)
                conn.close()
                for i, r in res.iterrows():
                    with st.expander(f"[{r['hs_code']}] {r['name_kr']}"): display_hsk_details(r['hs_code'])

# --- [Tab 2] 통계부호 ---
with tabs[1]:
    s_q = st.text_input("", placeholder="검색할 부호 또는 명칭을 입력하세요", key="stat_search")
    if st.button("검색"):
        conn = sqlite3.connect("customs_master.db")
        res = pd.read_sql(f"SELECT * FROM exemptions WHERE code LIKE '%{s_q}%' OR description LIKE '%{s_q}%'", conn)
        conn.close()
        st.table(res)

# --- [Tab 3] 세계 HS/세율 ---
with tabs[2]:
    st.header("🌎 세계 HS/세율 실시간 가이드")
    c_name = st.selectbox("국가 선택", ["미국", "EU", "베트남", "중국", "일본"])
    c_hs = st.text_input("현지 HS코드 입력")
    raw_data = st.text_area("해외 사이트 텍스트 복사/붙여넣기")
    if st.button("해외 세율 정밀 분석 실행"):
        with st.spinner("다국어 세율표 분석 중..."):
            res = model.generate_content(f"당신은 글로벌 관세사입니다. {c_name}의 HS코드 {c_hs}에 대해 다음 텍스트를 분석하여 기본/WTO/FTA세율을 표로 정리해줘: {raw_data}")
            st.markdown(res.text)

# --- [Tab 4 & 5] 자료 수집 중 ---
with tabs[3]: st.info("📜 FTA 정보 RAW 데이터 수집 및 업데이트 중입니다.")
with tabs[4]: st.info("📦 화물통관진행정보 조회 기능을 준비 중입니다.")

# --- [Tab 6] 세액계산기 ---
with tabs[5]:
    st.header("🧮 세액 계산기")
    p_val = st.number_input("물품가격(원화기준)", value=1000000)
    r_val = st.number_input("관세율(%)", value=8.0)
    if st.button("세액 계산"):
        duty = p_val * (r_val/100)
        vat = (p_val + duty) * 0.1
        st.success(f"관세: {int(duty):,}원 | 부가세: {int(vat):,}원 | 합계: {int(duty+vat):,}원")

# --- [Tab 7] 관리자 전용 ---
if st.session_state.is_admin:
    with tabs[6]:
        m = st.radio("관리 메뉴", ["회원 승인", "회원 삭제"], horizontal=True)
        conn = sqlite3.connect("users.db")
        if m == "회원 승인":
            p = pd.read_sql("SELECT id, name, biz_name FROM users WHERE is_approved=0", conn)
            st.table(p)
            tid = st.text_input("승인할 ID")
            if st.button("승인하기"):
                conn.execute("UPDATE users SET is_approved=1 WHERE id=?", (tid,))
                conn.commit(); st.success("완료")
        elif m == "회원 삭제":
            u = pd.read_sql("SELECT id, name FROM users", conn)
            st.table(u)
            did = st.text_input("삭제할 ID")
            if st.button("삭제하기"):
                conn.execute("DELETE FROM users WHERE id=?", (did,))
                conn.commit(); st.warning("삭제됨")
        conn.close()

# --- 4. 하단 연락처 및 상담 채널 (이지스 관세사무소) ---
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1:
    st.markdown("### 📞 전문가 상담: 010-8859-0403")
    st.write("이지스 관세사무소 | 이종혁 관세사 (jhlee@aegiscustoms.com)")
with c2: st.link_button("📧 이메일 상담", "mailto:jhlee@aegiscustoms.com", use_container_width=True)
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/", use_container_width=True)
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn", use_container_width=True)
import streamlit as st
import google.generativeai as genai
from PIL import Image
import pandas as pd
import sqlite3
import hashlib
import re
import io

# --- 1. DB 초기화 및 테이블 구조 설정 ---
def init_db():
    conn = sqlite3.connect("customs_master.db")
    c = conn.cursor()
    # HS코드 마스터
    c.execute("CREATE TABLE IF NOT EXISTS hs_master (hs_code TEXT, name_kr TEXT, name_en TEXT)")
    # 표준품명
    c.execute("CREATE TABLE IF NOT EXISTS standard_names (hs_code TEXT, std_name_kr TEXT, std_name_en TEXT)")
    # 관세율
    c.execute("CREATE TABLE IF NOT EXISTS rates (hs_code TEXT, type TEXT, rate TEXT)")
    # 세관장확인 (수입)
    c.execute("CREATE TABLE IF NOT EXISTS req_import (hs_code TEXT, law TEXT, agency TEXT, document TEXT)")
    # 감면/면세부호
    c.execute("CREATE TABLE IF NOT EXISTS exemptions (code TEXT, name TEXT, rate TEXT)")
    conn.commit()
    conn.close()

    conn_auth = sqlite3.connect("users.db")
    conn_auth.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    # 관리자 계정 ID: aegis01210
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
        else: st.error("정보 불일치 또는 승인 대기 상태입니다.")
    st.stop()

# --- 3. 메인 앱 레이아웃 ---
st.sidebar.write(f"✅ {st.session_state.user_id} 접속 중")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📊 통계부호", "🌎 세계 HS/세율", "📜 FTA정보", "📦 화물통관진행정보", "🧮 세액계산기"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# DB 상세 정보 출력 공통 함수
def display_hsk_details(hsk_code, probability=""):
    code_clean = re.sub(r'[^0-9]', '', str(hsk_code))
    conn = sqlite3.connect("customs_master.db")
    master = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{code_clean}'", conn)
    rates = pd.read_sql(f"SELECT type, rate FROM rates WHERE hs_code = '{code_clean}'", conn)
    reqs = pd.read_sql(f"SELECT law, agency, document FROM req_import WHERE hs_code = '{code_clean}'", conn)
    conn.close()
    
    if not master.empty:
        st.success(f"✅ [{code_clean}] {master['name_kr'].values[0]} {f'({probability})' if probability else ''}")
        c1, c2 = st.columns(2)
        with c1: st.write("**세율 정보**"); st.dataframe(rates, hide_index=True)
        with c2: st.write("**세관장확인**"); st.dataframe(reqs, hide_index=True)

# [Tab 1] HS검색 (미리보기 + 품명 로직 + 확률 병기)
with tabs[0]:
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("품명/물품정보 입력", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 업로드", type=["jpg", "png", "jpeg"], key="hs_i")
    
    if u_img: st.image(Image.open(u_img), caption="📸 분석 대상 이미지", width=300)

    if st.button("HS분석 실행", use_container_width=True):
        if u_img or u_input:
            with st.spinner("분석 중..."):
                try:
                    prompt = f"""당신은 전문 관세사입니다.
                    1. 품명: 유저입력('{u_input}')이 있으면 그대로 사용, 없으면 이미지를 보고 '예상품명' 제시.
                    2. 100% 확정 시: 10자리 HSK 코드 옆에 (100%) 표기.
                    3. 미확정 시: 6단위 기준 상위 3순위까지 확률(%)과 함께 추천.
                    결과 하단에 '추천결과: [코드] [확률]' 형식을 지켜주세요."""
                    
                    content = [prompt]
                    if u_img: content.append(Image.open(u_img))
                    if u_input: content.append(f"입력: {u_input}")
                    
                    res = model.generate_content(content)
                    st.markdown("### 📋 분석 리포트")
                    st.write(res.text)
                    
                    codes = re.findall(r'\d{10}', res.text)
                    if "100%" in res.text and codes:
                        st.divider()
                        display_hsk_details(codes[0], "100%")
                except Exception as e: st.error(f"오류: {e}")


# --- [Tab 2] 통계부호 (정밀 조회 모듈) ---
with tabs[1]:
    target_hs = st.text_input("조회할 HSK 10자리 (숫자만)", key="stat_q", placeholder="예: 0101211000")
    
    if st.button("데이터 통합 조회", use_container_width=True):
        if target_hs:
            # 입력값 숫자만 추출
            hsk = re.sub(r'[^0-9]', '', target_hs)
            
            # DB 연결
            conn = sqlite3.connect("customs_master.db")
            
            # 테이블 존재 여부 확인 및 데이터 쿼리
            try:
                # 1. 품명 정보 (hs_master)
                m = pd.read_sql(f"SELECT * FROM hs_master WHERE hs_code = '{hsk}'", conn)
                # 2. 표준 품명 (standard_names)
                std = pd.read_sql(f"SELECT * FROM standard_names WHERE hs_code = '{hsk}'", conn)
                # 3. 관세율 (rates)
                r = pd.read_sql(f"SELECT * FROM rates WHERE hs_code = '{hsk}'", conn)
                # 4. 세관장확인 (req_import)
                req = pd.read_sql(f"SELECT * FROM req_import WHERE hs_code = '{hsk}'", conn)
                
                if not m.empty:
                    st.subheader(f"📋 HS {hsk} 데이터 상세 리포트")
                    
                    c1, c2 = st.columns(2)
                    with c1:
                        st.info("**기본/영문 품명**")
                        st.write(f"국문: {m['name_kr'].values[0]}")
                        st.write(f"영문: {m['name_en'].values[0]}")
                    with c2:
                        st.info("**표준 품명**")
                        if not std.empty:
                            st.write(f"국문: {std['std_name_kr'].values[0]}")
                            st.write(f"영문: {std['std_name_en'].values[0]}")
                        else:
                            st.write("등록된 표준품명 없음")

                    st.divider()
                    st.markdown("### 💰 관세율 정보")
                    if not r.empty:
                        ra = r[r['type'] == 'A']
                        rc = r[r['type'] == 'C']
                        rf = r[r['type'].str.startswith('F', na=False)]
                        re_etc = r[~r['type'].isin(['A', 'C']) & ~r['type'].str.startswith('F', na=False)]
                        
                        m1, m2 = st.columns(2)
                        m1.metric("기본세율(A)", f"{ra['rate'].values[0]}%" if not ra.empty else "-")
                        m2.metric("WTO세율(C)", f"{rc['rate'].values[0]}%" if not rc.empty else "-")
                        
                        st.write("**협정세율(F)**")
                        st.dataframe(rf, hide_index=True, use_container_width=True)
                        st.write("**기타세율**")
                        st.dataframe(re_etc, hide_index=True, use_container_width=True)
                    else:
                        st.warning("등록된 세율 데이터가 없습니다.")

                    st.divider()
                    st.markdown("### 🛡️ 세관장확인 (수입)")
                    if not req.empty:
                        st.table(req)
                    else:
                        st.success("세관장확인 대상 품목이 아닙니다.")
                else:
                    st.error("해당 HS코드의 마스터 정보가 DB에 존재하지 않습니다. [관리자] 탭에서 'HS코드(마스터)' 파일을 먼저 업로드해 주세요.")
            
            except Exception as e:
                st.error(f"조회 중 오류 발생: {e}. [관리자] 탭에서 모든 CSV 파일을 다시 업로드해 주세요.")
            
            finally:
                conn.close()

# --- [Tab 7] 관리자 (CSV 업로드 및 DB 통합 매핑) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.header("⚙️ 데이터베이스 통합 관리 (aegis01210)")
        st.markdown("""
        관세청에서 내려받은 **CSV 파일**을 선택하고 해당 종류를 지정하여 업로드하세요. 
        업로드 시 기존 데이터는 최신 파일로 교체(Replace)됩니다.
        """)
        
        # 업로드 모드 선택
        mode = st.selectbox("업로드할 파일 종류 선택", [
            "HS코드(마스터)", 
            "표준품명", 
            "관세율", 
            "세관장확인(수입)",
            "내국세율",
            "관세감면/내국세면세부호"
        ])
        
        up_file = st.file_uploader(f"[{mode}] CSV 파일 선택", type="csv", key="admin_uploader")
        
        if up_file and st.button(f"{mode} DB 반영 실행", use_container_width=True):
            try:
                # 한글 깨짐 방지를 위한 인코딩 설정 (utf-8-sig)
                df = pd.read_csv(up_file, encoding='utf-8-sig')
                conn = sqlite3.connect("customs_master.db")
                
                if mode == "HS코드(마스터)":
                    # [HS코드(2026).csv] 기준 매핑
                    # 컬럼: HS부호, 한글품목명, 영문품목명
                    df_map = df[['HS부호', '한글품목명', '영문품목명']].copy()
                    df_map.columns = ['hs_code', 'name_kr', 'name_en']
                    table_name = 'hs_master'
                    
                elif mode == "표준품명":
                    # [표준품명(2026).csv] 기준 매핑
                    # 컬럼: HS부호, 표준품명_한글, 표준품명_영문
                    df_map = df[['HS부호', '표준품명_한글', '표준품명_영문']].copy()
                    df_map.columns = ['hs_code', 'std_name_kr', 'std_name_en']
                    table_name = 'standard_names'
                    
                elif mode == "관세율":
                    # [관세율(2026).csv] 기준 매핑
                    # 컬럼: 품목번호, 관세율구분, 관세율
                    df_map = df[['품목번호', '관세율구분', '관세율']].copy()
                    df_map.columns = ['hs_code', 'type', 'rate']
                    table_name = 'rates'
                    
                elif mode == "세관장확인(수입)":
                    # [세관장확인대상 품목(2026)_수입.csv] 기준 매핑
                    # 컬럼: HS부호, 신고인확인법령코드명, 요건승인기관코드명, 요건확인서류명
                    df_map = df[['HS부호', '신고인확인법령코드명', '요건승인기관코드명', '요건확인서류명']].copy()
                    df_map.columns = ['hs_code', 'law', 'agency', 'document']
                    table_name = 'req_import'

                elif mode == "내국세율":
                    # [내국세율(2026).csv] 기준 매핑
                    # 컬럼: 내국세율구분코드명, 신고품명, 내국세율
                    # HS코드가 없는 데이터이므로 별도 테이블로 관리하거나 참고용
                    df_map = df[['내국세율구분코드명', '신고품명', '내국세율']].copy()
                    df_map.columns = ['tax_type', 'item_name', 'tax_rate']
                    table_name = 'internal_tax_rates'

                elif mode == "관세감면/내국세면세부호":
                    # [관세감면부호(2026).csv] 또는 [내국세면세부호(2026).csv] 기준
                    # 첫 두 컬럼을 코드와 명칭으로 자동 인식
                    df_map = df.iloc[:, [0, 1]].copy()
                    df_map.columns = ['code', 'name']
                    table_name = 'exemptions'

                # HS코드 숫자 클렌징 (공백, 하이픈 제거)
                if 'hs_code' in df_map.columns:
                    df_map['hs_code'] = df_map['hs_code'].astype(str).str.replace(r'[^0-9]', '', regex=True)
                
                # DB 저장
                df_map.to_sql(table_name, conn, if_exists='replace', index=False)
                conn.close()
                
                st.balloons()
                st.success(f"✅ {mode} 데이터가 성공적으로 DB에 반영되었습니다.")
                st.info(f"조회 테이블명: {table_name} | 행 개수: {len(df_map):,}개")

            except Exception as e:
                st.error(f"❌ 데이터 반영 중 오류가 발생했습니다: {e}")
                st.warning("CSV 파일의 헤더(첫 줄) 명칭이 시스템 요구사항과 일치하는지 확인해주세요.")

# 하단 상담 채널
st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")
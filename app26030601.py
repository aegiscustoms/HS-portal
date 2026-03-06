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

# 관세청 서버 보안 우회를 위한 표준 브라우저 헤더
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Accept": "application/xml"
}

# --- 1. 초기 DB 설정 (이지스 고유 데이터 및 로그인용) ---
def init_db():
    conn = sqlite3.connect("users.db")
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY, pw TEXT, name TEXT, is_approved INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0)""")
    admin_id = "aegis01210"
    admin_pw = hashlib.sha256("dlwltm2025@".encode()).hexdigest()
    conn.execute("INSERT OR IGNORE INTO users (id, pw, is_approved, is_admin) VALUES (?, ?, 1, 1)", (admin_id, admin_pw))
    conn.commit()
    conn.close()

    # 이지스 내부용 마스터 DB (표준품명 등)
    conn_m = sqlite3.connect("customs_master.db")
    c_m = conn_m.cursor()
    c_m.execute("CREATE TABLE IF NOT EXISTS standard_names (hs_code TEXT, base_name TEXT, std_name_kr TEXT, std_name_en TEXT)")
    conn_m.commit()
    conn_m.close()

init_db()

# Gemini AI 설정
api_key = st.secrets.get("GEMINI_KEY")
if api_key:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-2.0-flash')

# --- 2. 로그인 및 세션 관리 ---
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

# --- 3. 메인 탭 구성 ---
st.sidebar.write(f"✅ {st.session_state.user_id} 접속 중")
if st.sidebar.button("로그아웃"):
    st.session_state.logged_in = False
    st.rerun()

tabs = st.tabs(["🔍 HS검색", "📘 HS정보", "📊 통계부호", "📦 화물통관진행정보", "🧮 세액계산기"] + (["⚙️ 관리자"] if st.session_state.is_admin else []))

# --- [Tab 1] HS검색 (Gemini AI) ---
with tabs[0]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>🔍 AI 품목분류 분석</div>", unsafe_allow_html=True)
    col_a, col_b = st.columns([2, 1])
    with col_a: u_input = st.text_input("물품 정보 입력 (용도/재질 등)", key="hs_q")
    with col_b: u_img = st.file_uploader("이미지 분석", type=["jpg", "png", "jpeg"], key="hs_i")
    if st.button("AI 분석 실행", use_container_width=True):
        with st.spinner("전문가 시스템 분석 중..."):
            try:
                prompt = f"당신은 전문 관세사입니다. 물품 '{u_input}'을 분석하여 HSK 10자리를 추천하고 분류 근거(해설서 요약)를 제시하세요."
                content = [prompt]
                if u_img: content.append(Image.open(u_img))
                res = model.generate_content(content)
                st.markdown("### 📋 AI 추천 리포트")
                st.write(res.text)
            except Exception as e: st.error(f"분석 오류: {e}")

# --- [Tab 2] HS정보 (관세청 실시간 관세율 API) ---
with tabs[1]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📘 품목별 실시간 관세율 조회 (Uni-Pass)</div>", unsafe_allow_html=True)
    RATE_KEY = st.secrets.get("RATE_API_KEY", "").strip()
    target_hs = st.text_input("조회할 HS코드 10자리", placeholder="예: 8517130000", key="hs_rate_api")

    if st.button("실시간 관세율 조회", use_container_width=True):
        if not target_hs: st.warning("코드를 입력하세요.")
        else:
            with st.spinner("관세청 서버와 실시간 통신 중..."):
                url = "https://unipass.customs.go.kr:38010/ext/rest/itemRateQry/retrieveItemRate"
                params = {"crkyCn": RATE_KEY, "hsCd": target_hs.strip()}
                try:
                    res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
                    if res.text:
                        root = ET.fromstring(res.content)
                        items = root.findall(".//itemRateQryVo")
                        if items:
                            st.markdown(f"**HS {target_hs} 검색 결과**")
                            rate_data = []
                            for i in items:
                                rate_data.append({
                                    "코드": i.findtext("tarfClsfCd"),
                                    "세율명칭": i.findtext("tarfNm"),
                                    "세율(%)": f"{i.findtext('itrt')}%",
                                    "적용일자": i.findtext("aplyStrtDt")
                                })
                            df = pd.DataFrame(rate_data)
                            st.dataframe(df.style.set_properties(**{'font-size': CONTENT_FONT_SIZE, 'text-align': 'center'}), hide_index=True, use_container_width=True)
                        else: st.warning("조회된 데이터가 없습니다.")
                    else: st.error("관세청 서버 응답이 없습니다.")
                except Exception as e: st.error(f"API 호출 실패: {e}")

# --- [Tab 3] 통계부호 (관세청 실시간 공통코드 API) ---
with tabs[2]:
    st.markdown(f"<div style='font-size: {TITLE_FONT_SIZE}; font-weight: bold; color: #1E3A8A;'>📊 실시간 통계부호/공통코드 검색</div>", unsafe_allow_html=True)
    STAT_KEY = st.secrets.get("STAT_API_KEY", "").strip()
    
    clft_dict = {"관세감면분납코드": "001", "내국세면세부호": "002", "보세구역": "003", "세관부호": "004"}
    col1, col2 = st.columns([1, 2])
    with col1: sel_clft = st.selectbox("분류 카테고리", list(clft_dict.keys()))
    with col2: kw = st.text_input("부호 또는 명칭 키워드", placeholder="예: 인천, 농업")

    if st.button("부호 실시간 조회", use_container_width=True):
        with st.spinner("코드 마스터 데이터 불러오는 중..."):
            url = "https://unipass.customs.go.kr:38010/ext/rest/cmmnCdQry/retrieveCmmnCd"
            params = {"crkyCn": STAT_KEY, "clftCd": clft_dict[sel_clft]}
            try:
                res = requests.get(url, params=params, headers=HTTP_HEADERS, timeout=15)
                if res.text:
                    root = ET.fromstring(res.content)
                    codes = root.findall(".//cmmnCdQryVo")
                    if codes:
                        res_list = []
                        for c in codes:
                            c_name, c_id = c.findtext("cdNm"), c.findtext("cd")
                            if not kw or (kw in c_name or kw in c_id):
                                res_list.append({"부호": c_id, "명칭": c_name, "설명": c.findtext("cdDesc")})
                        st.dataframe(pd.DataFrame(res_list).style.set_properties(**{'font-size': CONTENT_FONT_SIZE}), hide_index=True, use_container_width=True)
                    else: st.warning("데이터가 존재하지 않습니다.")
                else: st.error("응답 데이터가 없습니다.")
            except Exception as e: st.error(f"API 호출 실패: {e}")

# --- [Tab 4] 화물통관진행정보 (실제 XML 결과 기반 최종 보정) ---
with tabs[3]:
    st.subheader("📦 실시간 화물통관 진행정보 조회")
    
    CR_API_KEY = st.secrets.get("UNIPASS_API_KEY", "").strip()
    
    if not CR_API_KEY:
        st.error("⚠️ Streamlit Secrets에 'UNIPASS_API_KEY'가 설정되지 않았습니다.")
        st.stop()

    col1, col2, col3 = st.columns([1.5, 3, 1])
    with col1:
        carg_year = st.selectbox("입항년도", [2026, 2025, 2024, 2023], index=0)
    with col2:
        bl_no = st.text_input("B/L 번호 입력", placeholder="HBL 또는 MBL 번호", key="bl_final_v3")
    with col3:
        st.write("") 
        search_btn = st.button("실시간 조회", use_container_width=True)

    if search_btn:
        if not bl_no:
            st.warning("B/L 번호를 입력해 주세요.")
        else:
            with st.spinner("관세청 유니패스에서 데이터를 가져오는 중..."):
                # 실제 테스트 성공하신 URL 적용
                url = "https://unipass.customs.go.kr:38010/ext/rest/cargCsclPrgsInfoQry/retrieveCargCsclPrgsInfo"
                
                params = {
                    "crkyCn": CR_API_KEY,
                    "blYy": str(carg_year),
                    "hblNo": bl_no.strip().upper()
                }
                
                try:
                    # 타임아웃을 30초로 넉넉히 설정
                    response = requests.get(url, params=params, timeout=30)
                    
                    if response.status_code == 200:
                        root = ET.fromstring(response.content)
                        
                        # tCnt: 결과 건수 확인
                        t_cnt = root.findtext(".//tCnt")
                        
                        if t_cnt and int(t_cnt) > 0:
                            # 1. 일반 정보 (cargCsclPrgsInfoQryVo)
                            info = root.find(".//cargCsclPrgsInfoQryVo")
                            
                            # 실제 XML 태그인 prgsStts(반출완료 등)와 csclPrgsStts(수입신고수리 등) 활용
                            current_status = info.findtext('prgsStts') # 현재 진행 상태
                            st.success(f"✅ 화물 확인됨: {current_status}")
                            
                            m1, m2, m3 = st.columns(3)
                            m1.metric("진행상태", current_status)
                            m2.metric("품명", info.findtext("prnm")[:12] if info.findtext("prnm") else "-")
                            m3.metric("중량", f"{info.findtext('ttwg')} {info.findtext('wghtUt')}")

                            # 상세 요약 (12px)
                            st.markdown("---")
                            st.markdown(f"""
                            <div class='custom-text'>
                            <b>• 선박/항공기명:</b> {info.findtext('shipNm')}<br>
                            <b>• 입항일자:</b> {info.findtext('etprDt')}<br>
                            <b>• 현재위치:</b> {info.findtext('shcoFlco')}<br>
                            <b>• MBL 번호:</b> {info.findtext('mblNo')}
                            </div>
                            """, unsafe_allow_html=True)

                            # 2. 상세 이력 (cargCsclPrgsInfoDtlQryVo)
                            st.markdown("#### 🕒 처리 단계별 상세 이력")
                            history = []
                            for item in root.findall(".//cargCsclPrgsInfoDtlQryVo"):
                                history.append({
                                    "처리단계": item.findtext("cargTrcnRelaBsopTpcd"),
                                    "처리일시": item.findtext("prcsDttm"),
                                    "장치장/내용": item.findtext("shedNm") if item.findtext("shedNm") else item.findtext("rlbrCn"),
                                    "포장개수": f"{item.findtext('pckGcnt')} {item.findtext('pckUt')}"
                                })
                            
                            df_hist = pd.DataFrame(history)
                            st.dataframe(
                                df_hist.style.set_properties(**{'text-align': 'center', 'font-size': '12px'}),
                                hide_index=True, use_container_width=True
                            )
                        else:
                            st.warning("조회된 정보가 없습니다. 번호나 연도를 확인하세요.")
                    else:
                        st.error(f"❌ 접속 오류 (Status: {response.status_code})")
                except Exception as e:
                    st.error(f"⚠️ 연결 실패: {str(e)}")
                    st.info("사내 네트워크 차단이 의심됩니다. 모바일 핫스팟으로 연결 후 다시 시도해 보세요.")

# --- [Tab 6] 관리자 (이지스 고유 데이터 관리) ---
if st.session_state.is_admin:
    with tabs[-1]:
        st.header("⚙️ 관리자 설정 센터")
        st.subheader("📁 내부 마스터 데이터 관리")
        up_std = st.file_uploader("표준품명 마스터 업로드 (CSV)", type="csv")
        if up_std and st.button("데이터베이스 동기화"):
            df = pd.read_csv(up_std, encoding='utf-8-sig')
            conn = sqlite3.connect("customs_master.db")
            df.to_sql('standard_names', conn, if_exists='replace', index=False)
            conn.close(); st.success("동기화 성공")

# --- 하단 푸터 (기존 내용 유지) ---

st.divider()
c1, c2, c3, c4 = st.columns([2,1,1,1])
with c1: st.write("**📞 010-8859-0403 (이지스 관세사무소)**")
with c2: st.link_button("📧 이메일", "mailto:jhlee@aegiscustoms.com")
with c3: st.link_button("🌐 홈페이지", "https://aegiscustoms.com/")
with c4: st.link_button("💬 카카오톡", "https://pf.kakao.com/_nxexbTn")
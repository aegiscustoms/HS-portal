import streamlit as st
import google.generativeai as genai
from PIL import Image

# 1. 제미나이 API 설정
# GitHub 배포 시에는 st.secrets 방식을 사용하고, 로컬 테스트 시에는 직접 키를 입력하세요.
try:
    GOOGLE_API_KEY = st.secrets["GEMINI_KEY"]
except:
    GOOGLE_API_KEY = "여기에_직접_발급받은_API키를_입력하세요"

genai.configure(api_key=GOOGLE_API_KEY)

# 속도가 빠르고 효율적인 gemini-1.5-flash 모델 사용
model = genai.GenerativeModel('gemini-1.5-flash')

# 웹페이지 설정 (모바일 최적화)
st.set_page_config(page_title="HS포털 AI 통합 검색", layout="centered")

st.title("🔍 HS포털 AI 통합 검색")
st.info("품목 정보를 입력하거나 사진을 업로드하여 HS코드를 빠르게 조회하세요.")

# --- 입력 섹션 ---
search_query = st.text_area(
    "물품 정보를 입력하세요:", 
    placeholder="품명 / 용도 / 기능 / 성분 / 재질 등을 입력하세요.",
    height=150
)

uploaded_file = st.file_uploader("이미지를 업로드하거나 촬영하세요 (선택사항)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.image(image, caption='분석할 이미지', use_container_width=True)

# --- 실행 버튼 ---
if st.button("HS코드 분석 시작"):
    if not search_query and uploaded_file is None:
        st.warning("검색할 텍스트를 입력하거나 이미지를 업로드해 주세요.")
    else:
        # 답변이 출력될 빈 공간을 먼저 만듭니다.
        result_container = st.empty()
        
        with st.spinner('AI가 HS코드를 추론 중입니다...'):
            try:
                # 2. 분석 프롬프트 (분류 근거 제외, 핵심 정보만 요청)
                prompt = """
                당신은 전문 관세사입니다. 제공된 정보를 바탕으로 다음 형식에 맞춰 아주 간결하게 답변하세요.
                분류 근거는 생략하고 결과만 제시합니다.

                1) 예상 품명
                2) 예상 추천 6단위 HS코드 (최대 3개)와 각 코드의 확률(%)
                   (100% 확실한 경우 1개만 제시)
                
                한국어로 답변해 주세요.
                """
                
                content_list = [prompt]
                if search_query:
                    content_list.append(f"\n[입력 정보]: {search_query}")
                if uploaded_file is not None:
                    content_list.append(image)
                
                # 3. 스트리밍 방식으로 응답 생성 (속도 향상 및 타임아웃 방지)
                response = model.generate_content(content_list, stream=True)
                
                st.subheader("✅ AI 분석 결과")
                # 실시간으로 텍스트를 화면에 뿌려줍니다.
                st.write_stream(response)
                
            except Exception as e:
                if "503" in str(e) or "overloaded" in str(e).lower():
                    st.error("현재 AI 서버에 요청이 많습니다. 잠시 후 다시 시도해 주세요.")
                elif "429" in str(e):
                    st.error("무료 버전 사용량이 초과되었습니다. 잠시 후 다시 시도해 주세요.")
                else:
                    st.error(f"오류가 발생했습니다: {e}")

st.divider()
st.caption("© 2026 HS포털 - AI 추천 결과는 참고용으로만 활용하세요.")
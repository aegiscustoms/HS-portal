import streamlit as st
import google.generativeai as genai
from PIL import Image

# 1. 제미나이 API 설정 (발급받은 키를 여기에 입력하거나 Secrets를 사용하세요)
# 배포 시에는 st.secrets["GEMINI_KEY"] 방식을 권장합니다.
GOOGLE_API_KEY = "여기에_API_키를_넣으세요" 
genai.configure(api_key=GOOGLE_API_KEY)

# 무료 티어에서 안정적인 gemini-1.5-flash 모델을 권장합니다.
model = genai.GenerativeModel('gemini-1.5-flash')

# 웹페이지 설정 (모바일 최적화 레이아웃)
st.set_page_config(page_title="HS포털 AI 통합 검색", layout="centered")

st.title("🔍 HS포털 AI 통합 검색")
st.info("이미지 업로드와 텍스트 입력을 자유롭게 조합하여 HS코드를 조회하세요.")

# --- 입력 섹션 ---
# 2. 텍스트 검색창 (질문자님 요청 반영: 품명/용도/기능/성분/재질)
search_query = st.text_area(
    "물품 정보를 입력하세요:", 
    placeholder="품명 / 용도 / 기능 / 성분 / 재질 등을 상세히 적을수록 정확도가 높아집니다.",
    help="예: 스마트워치 / 운동량 기록용 / 심박수 측정 / 실리콘 및 금속 / 손목시계형 기기"
)

# 3. 이미지 업로드 섹션
uploaded_file = st.file_uploader("이미지를 업로드하거나 촬영하세요 (선택사항)", type=["jpg", "jpeg", "png"])

# 업로드된 이미지가 있다면 화면에 미리보기 출력
if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.image(image, caption='분석할 이미지', use_container_width=True)

# --- 실행 버튼 ---
if st.button("HS코드 분석 시작"):
    # 이미지와 텍스트가 둘 다 없는 경우 체크
    if not search_query and uploaded_file is None:
        st.warning("검색할 텍스트를 입력하거나 이미지를 업로드해 주세요.")
    else:
        with st.spinner('제미나이가 데이터를 분석 중입니다...'):
            try:
                # 4. 분석 로직 구성
                # 공통 프롬프트 설정
                base_prompt = """
                당신은 전문 관세사입니다. 제공된 정보를 바탕으로 다음 형식에 맞춰 답변하세요:
                1) 예상 품명
                2) 예상 추천 6단위 HS코드 (최대 3개)와 각 코드의 적중 확률(%)
                   (100% 확실한 경우 1개만 제시)
                3) 분류 근거 (관세율표 해석 통칙 및 품목분류 원칙 언급)
                
                결과는 한국어로 친절하게 설명해 주세요.
                """
                
                # 상황별 전송 데이터 결정
                content_list = [base_prompt]
                
                if search_query:
                    content_list.append(f"\n[사용자 입력 정보]\n{search_query}")
                
                if uploaded_file is not None:
                    # 이미지가 있으면 리스트에 추가
                    content_list.append(image)
                
                # 제미나이에게 통합 데이터 전송 및 응답 생성
                response = model.generate_content(content_list)
                
                # 결과 출력
                st.success("분석이 완료되었습니다!")
                st.subheader("✅ AI 분석 결과")
                st.markdown(response.text)
                
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")

st.divider()
st.caption("© 2026 HS포털 - AI 추천 결과는 법적 효력이 없으므로 참고용으로만 활용하세요.")
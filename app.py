import streamlit as st
import google.generativeai as genai
from PIL import Image

# 1. API 설정
try:
    # Streamlit Cloud 배포 시 설정한 Secrets 사용
    GOOGLE_API_KEY = st.secrets["GEMINI_KEY"]
except:
    # 로컬 테스트용 (본인의 API 키 입력)
    GOOGLE_API_KEY = "여기에_발급받은_API키를_입력하세요"

genai.configure(api_key=GOOGLE_API_KEY)

# 최신 2.0 모델 또는 안정적인 1.5 모델 사용 (404 에러 방지)
model = genai.GenerativeModel('gemini-2.0-flash')

# 웹페이지 설정
st.set_page_config(page_title="HS포털 AI 통합 검색", layout="centered")

# 헤더 부분
st.title("🔍 HS포털 AI 통합 검색")
st.markdown(f"""
    **전문 관세사가 설계한 AI 품목분류 서비스** 이미지 촬영이나 상세 정보 입력만으로 예상 HS코드를 즉시 확인하세요.
""")

# --- 입력 섹션 ---
st.divider()

search_query = st.text_area(
    "물품 상세 정보 입력:", 
    placeholder="품명 / 용도 / 기능 / 성분 / 재질 등을 상세히 입력할수록 정확도가 높아집니다.",
    height=120
)

uploaded_file = st.file_uploader("이미지 업로드 (선택사항)", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.image(image, caption='분석 대기 이미지', use_container_width=True)

# --- 분석 실행 ---
if st.button("AI HS코드 분석 시작", use_container_width=True):
    if not search_query and uploaded_file is None:
        st.warning("분석할 텍스트 정보를 입력하거나 이미지를 업로드해 주세요.")
    else:
        with st.spinner('제미나이 AI가 데이터를 분석 중입니다...'):
            try:
                # 프롬프트 설정 (분류 근거 제외, 핵심 위주 답변)
                prompt = """
                당신은 전문 관세사입니다. 제공된 이미지와 정보를 바탕으로 다음 형식에 맞춰 간결하게 답변하세요.
                내용이 길어지지 않도록 분류 근거는 생략하고 결과만 핵심적으로 전달합니다.

                1) 예상 품명: (물품의 성격에 맞는 정확한 명칭)
                2) 추천 HS코드: 6단위 코드 (최대 3개) 및 적중 확률(%) 표기
                3) 참고 사항: (수입요건 유무 등 간단한 주의사항 한 줄)
                
                한국어로 답변하세요.
                """
                
                # 입력 데이터 조합
                content_list = [prompt]
                if search_query:
                    content_list.append(f"\n[입력된 물품 상세 정보]\n{search_query}")
                if uploaded_file is not None:
                    content_list.append(image)
                
                # 결과 출력 섹션
                st.success("분석 완료!")
                st.subheader("✅ AI 분석 결과")
                
                # 스트리밍 응답 처리 (오류 수정 핵심 구간)
                response = model.generate_content(content_list, stream=True)
                
                placeholder = st.empty()  # 텍스트가 실시간으로 써질 빈 공간
                full_response = ""

                for chunk in response:
                    # chunk 내의 실제 텍스트 부분만 추출
                    if chunk.text:
                        full_response += chunk.text
                        # 실시간 타이핑 효과
                        placeholder.markdown(full_response + " ▌")
                
                # 최종 텍스트 출력 (커서 제거)
                placeholder.markdown(full_response)
                
            except Exception as e:
                if "503" in str(e) or "overloaded" in str(e).lower():
                    st.error("현재 서버 혼잡으로 응답이 지연되고 있습니다. 잠시 후 다시 시도해 주세요.")
                elif "404" in str(e):
                    st.error("모델을 찾을 수 없습니다. 모델명을 'gemini-1.5-flash' 또는 'gemini-2.0-flash'로 변경해 보세요.")
                else:
                    st.error(f"오류가 발생했습니다: {e}")

# --- 하단 안내 ---
st.divider()
st.caption("본 결과는 AI의 추론 기반이며, 실제 통관 시 법적 증빙 자료로 사용할 수 없습니다.")
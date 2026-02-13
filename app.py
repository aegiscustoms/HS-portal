import streamlit as st
import google.generativeai as genai
from PIL import Image

# 1. 제미나이 API 설정 (발급받은 키를 따옴표 안에 넣으세요)
GOOGLE_API_KEY = "여기에_발급받은_API키를_넣으세요"
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')

# 모바일 최적화 레이아웃 설정
st.set_page_config(page_title="HS포털 AI 스캐너", layout="centered")

st.title("🔍 HS포털 AI 스캐너")
st.info("이미지를 업로드하면 AI가 HS코드를 추천합니다.")

# 2. 이미지 업로드 섹션
uploaded_file = st.file_uploader("제품 사진을 업로드하거나 촬영하세요", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    # 이미지 표시
    image = Image.open(uploaded_file)
    st.image(image, caption='분석할 이미지', use_container_width=True)
    
    # 분석 버튼
    if st.button("HS코드 분석 시작"):
        with st.spinner('제미나이가 분석 중...'):
            try:
                # 3. 제미나이 프롬프트 (요청 내용 반영)
                prompt = """
                이 이미지 속 물품을 분석해서 다음 형식으로 출력해줘:
                1) 예상 품명
                2) 예상 추천 6단위 HS코드 3개와 각 코드의 확률
                   (만약 특정 코드가 100% 확실하다면 1개만 제시)
                결과는 한국어로 작성해줘.
                """
                
                response = model.generate_content([prompt, image])
                
                st.subheader("✅ AI 분석 결과")
                st.write(response.text)
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")

st.divider()
st.caption("© 2026 HS포털 - 테스트 버전")
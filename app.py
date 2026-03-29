import streamlit as st
import os
from main import build_blog_db, generate_blog_post, get_naver_blog_urls_by_id
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(page_title="Raton AI 블로그 작가", layout="wide")

# 앱 시작 시 기존 DB 자동 로드
if 'db' not in st.session_state:
    with st.spinner("기존 학습 데이터를 불러오는 중..."):
        db = build_blog_db(None) # URL 없이 호출하면 로드만 수행
        if db:
            st.session_state.db = db
            st.toast("✅ 기존 학습 데이터를 성공적으로 불러왔습니다!")
        else:
            st.info("💡 아직 학습된 데이터가 없습니다. 왼쪽에서 블로그를 학습시켜 주세요.")

st.title("✍️ Raton AI 블로그 작가 (MVP)")
st.subheader("나의 네이버 블로그를 학습하여 맞춤형 포스팅을 생성합니다.")

# 사이드바: 설정 및 학습
with st.sidebar:
    st.header("1. 말투 학습 및 업데이트")
    
    # DB 상태 표시
    if 'db' in st.session_state:
        st.success("✅ 페르소나 로드 완료")
    else:
        st.warning("⚠️ 페르소나 미학습 상태")

    naver_id = st.text_input("네이버 블로그 아이디", value="gobc20000", placeholder="예: gobc20000")
    
    # 수집 범위 설정 추가
    page_count = st.slider("수집할 페이지 수 (페이지당 약 30개)", min_value=1, max_value=20, value=3)
    
    if st.button("내 글 목록 가져오기"):
        if naver_id:
            with st.spinner(f"'{naver_id}'님의 글 주소를 {page_count}페이지까지 찾는 중..."):
                urls = get_naver_blog_urls_by_id(naver_id, page_count=page_count)
                if urls:
                    st.session_state.urls = urls
                    st.success(f"글 {len(urls)}개를 찾았습니다!")
                else:
                    st.error("글을 찾지 못했습니다.")
        else:
            st.warning("아이디를 입력해 주세요.")

    if 'urls' in st.session_state:
        st.write(f"확인된 주소: {len(st.session_state.urls)}개")
        if st.button("새로운 글 추가 학습 (DB 업데이트)"):
            with st.spinner("새로운 본문을 분석하여 추가 학습 중..."):
                # 새로운 글만 골라서 추가함
                db = build_blog_db(st.session_state.urls)
                if db:
                    st.session_state.db = db
                    st.success("업데이트가 완료되었습니다!")

# 메인 화면: 주제 입력 및 결과
st.header("2. 새 블로그 글 작성하기")
topic = st.text_input("새로운 포스팅 주제", placeholder="예: 2024년 하반기 수도권 청약 단지 분석")
extra_info = st.text_area("참고할 자료 (뉴스 기사, PDF 텍스트 등)", 
                          placeholder="작성에 참고할 상세 정보를 넣어주세요. AI가 이 내용을 바탕으로 글을 씁니다.", 
                          height=200)

if st.button("블로그 포스트 생성하기"):
    if 'db' not in st.session_state:
        st.error("먼저 왼쪽에서 '내 말투 학습하기' 단계를 완료해 주세요.")
    elif not topic:
        st.warning("주제를 입력해 주세요.")
    else:
        with st.spinner("라톤님의 페르소나를 불러오는 중..."):
            result = generate_blog_post(st.session_state.db, topic, extra_info)
            st.divider()
            st.markdown("### 📝 생성된 블로그 포스트")
            st.write(result)
            st.download_button("텍스트 파일로 다운로드", result, file_name=f"{topic}.txt")

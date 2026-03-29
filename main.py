# -*- coding: utf-8 -*-
import os
import requests
import feedparser
import json
import re
from bs4 import BeautifulSoup
from dotenv import load_dotenv

try:
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:
    from langchain.text_splitter import RecursiveCharacterTextSplitter

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_google_genai import ChatGoogleGenerativeAI

try:
    from langchain_core.prompts import PromptTemplate
    from langchain_core.documents import Document
except ImportError:
    from langchain.prompts import PromptTemplate
    from langchain.schema import Document

# 1. Environment Settings
load_dotenv()

# 2. Naver Blog Content Extractor
def get_naver_blog_content(url):
    try:
        # RSS용 파라미터(?fromRss=true...)가 붙어있을 경우 제거하여 깨끗한 주소로 만듭니다.
        clean_url = url.split('?')[0]
        
        if "blog.naver.com" in clean_url and "PostView" not in clean_url:
            path_parts = clean_url.replace("https://blog.naver.com/", "").split("/")
            if len(path_parts) >= 2:
                user_id = path_parts[0]
                log_no = path_parts[1]
                url = f"https://blog.naver.com/PostView.naver?blogId={user_id}&logNo={log_no}"
        else:
            url = clean_url

        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36"}
        response = requests.get(url, headers=headers)
        # 인코딩 설정 (네이버 블로그는 utf-8)
        response.encoding = 'utf-8'
        soup = BeautifulSoup(response.text, "html.parser")

        # 네이버 블로그 본문 태그들 (여러 후보군을 모두 탐색)
        content = soup.find("div", class_="se-main-container")
        if not content:
            content = soup.find("div", id="postViewArea")
        if not content:
            content = soup.find("div", class_="se-viewer")
        
        if content:
            # 텍스트 추출 시 불필요한 공백 제거
            text = content.get_text(separator="\n", strip=True)
            if len(text) < 50: # 내용이 너무 적으면 실패로 간주
                return "Content too short."
            return text
        else:
            return "Content not found."
    except Exception as e:
        return f"Error: {e}"

# 3. Naver Blog URL Collector (Enhanced - Regex Version)
def get_naver_blog_urls_by_id(blog_id, page_count=3):
    """
    네이버 블로그 아이디로 글 URL 목록을 가져옵니다. (정규식 기반으로 JSON 오류 방지)
    """
    all_urls = []
    blog_id = blog_id.strip()
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
        "Referer": f"https://blog.naver.com/PostList.naver?blogId={blog_id}",
        "Accept": "*/*"
    }
    
    print(f"[{blog_id}] 수집 시작 (정규식 모드, 목표: {page_count}페이지)...")
    
    for page in range(1, page_count + 1):
        list_url = f"https://blog.naver.com/PostTitleListAsync.naver?blogId={blog_id}&viewdate=&currentPage={page}&categoryNo=&parentCategoryNo=&countPerPage=30"
        
        try:
            response = requests.get(list_url, headers=headers)
            if response.status_code != 200:
                print(f"오류: 응답 코드 {response.status_code}")
                break
                
            text = response.text
            
            # JSON 파싱 대신 "logNo":"12345678" 패턴을 직접 찾습니다.
            log_nos = re.findall(r'"logNo"\s*:\s*"(\d+)"', text)
            
            if log_nos:
                for log_no in log_nos:
                    all_urls.append(f"https://blog.naver.com/{blog_id}/{log_no}")
                print(f"{page}페이지 수집 완료: {len(log_nos)}개 추출됨")
            else:
                # 더 이상 데이터가 없는지 확인 (검색 결과 없음 등)
                if '"postList":[]' in text.replace(" ", ""):
                    print(f"{page}페이지: 더 이상 게시글이 없습니다.")
                    break
                else:
                    print(f"{page}페이지: logNo를 찾지 못했습니다.")
                
            time.sleep(0.5) 
        except Exception as e:
            print(f"{page}페이지 예외 발생: {e}")
            break
            
    unique_urls = []
    for url in all_urls:
        if url not in unique_urls:
            unique_urls.append(url)
            
    print(f"최종 수집 완료: 총 {len(unique_urls)}개의 URL 확보")
    return unique_urls

import time

# 4. Vector DB Build
def build_blog_db_from_urls(urls=None, persist_directory="./chroma_db"):
    """
    urls가 주어지면 새로운 글만 추가하고, 
    urls가 없거나 빈 리스트면 기존 DB만 불러옵니다.
    """
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
    vectorstore = None
    existing_urls = set()
    
    # 1. 기존 DB 로드 시도
    if os.path.exists(persist_directory):
        print(f"기존 학습 데이터({persist_directory})를 불러오는 중입니다...")
        try:
            vectorstore = Chroma(
                persist_directory=persist_directory, 
                embedding_function=embeddings
            )
            # 기존 저장된 문서들의 URL(source) 목록 가져오기
            data = vectorstore.get()
            if data and 'metadatas' in data:
                existing_urls = {m.get('source') for m in data['metadatas'] if m.get('source')}
            print(f"이미 학습된 글: {len(existing_urls)}개")
        except Exception as e:
            print(f"기존 DB 로드 중 오류: {e}")

    # 2. 추가할 글이 없는 경우 (초기 로딩용)
    if not urls:
        return vectorstore

    # 3. 새로운 URL만 필터링
    new_urls = [url for url in urls if url not in existing_urls]
    
    if not new_urls:
        print("모든 글이 이미 학습되어 있습니다. 추가할 내용이 없습니다.")
        return vectorstore

    print(f"새로운 글 {len(new_urls)}개를 추가로 학습합니다.")
    
    documents = []
    for url in new_urls:
        print(f"[{url}] 본문 수집 중...")
        text = get_naver_blog_content(url)
        if "Error" not in text and "Content not found" not in text and "too short" not in text:
            documents.append(Document(page_content=text, metadata={"source": url}))
    
    if not documents:
        print("추가로 학습할 유효한 내용이 없습니다.")
        return vectorstore

    # 4. 텍스트 분할 및 추가 (배치 처리)
    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
    splits = text_splitter.split_documents(documents)
    
    batch_size = 1
    total_batches = len(splits)
    
    for i in range(0, total_batches, batch_size):
        batch = splits[i:i + batch_size]
        print(f"[{i+1}/{total_batches}] 새 데이터 학습 중...")
        
        for attempt in range(3):
            try:
                if vectorstore is None:
                    vectorstore = Chroma.from_documents(
                        documents=batch, 
                        embedding=embeddings, 
                        persist_directory=persist_directory
                    )
                else:
                    vectorstore.add_documents(batch)
                
                time.sleep(5) # API 할당량 보호
                break 
            except Exception as e:
                if "429" in str(e):
                    wait_time = (attempt + 1) * 20
                    print(f"할당량 초과! {wait_time}초 대기...")
                    time.sleep(wait_time)
                else:
                    print(f"오류 발생: {e}")
                    time.sleep(5)
                    break
                
    return vectorstore

# 5. Generate Blog Post
def generate_blog_post(vectorstore, new_topic, reference_material=""):
    # 참조 문서 조각을 7개로 늘려 더 많은 문체를 학습하게 함
    retriever = vectorstore.as_retriever(search_kwargs={"k": 7})
    retrieved_docs = retriever.invoke(new_topic)
    
    # 중복 제거 및 문체 추출
    unique_contents = list(dict.fromkeys([doc.page_content for doc in retrieved_docs]))
    style_reference = "\n\n---\n\n".join(unique_contents)

    prompt_template = """
    당신은 아래 [STYLE REFERENCE]에 제공된 실제 블로그 포스팅의 말투와 형식을 완벽하게 흉내 내는 전문 블로거입니다.
    사용자가 제공한 [TOPIC]과 [REFERENCE INFO]를 바탕으로 새로운 블로그 글을 작성하세요.

    [작성 규칙]
    1. 반드시 [STYLE REFERENCE]에서 관찰되는 문체(어투, 인사말, 맺음말, 감탄사 등)를 그대로 사용하세요.
    2. [STYLE REFERENCE]에서 자주 사용하는 기호(예: ✅, -, 1., 2.)와 소제목 형식을 그대로 유지하세요.
    3. 인위적인 'AI 말투'가 아닌, 실제 사람이 쓴 것 같은 친근하고 전문적인 느낌을 살리세요.
    4. 제공된 [REFERENCE INFO]의 정보를 정확하게 반영하여 실질적인 도움을 주는 글을 작성하세요.

    [STYLE REFERENCE]
    {style_reference}

    [TOPIC]
    {new_topic}

    [REFERENCE INFO]
    {reference_material}

    위 스타일을 바탕으로 완벽한 블로그 포스트를 작성해 주세요. 한국어로 작성하세요.
    """
    
    prompt = PromptTemplate(
        input_variables=["style_reference", "new_topic", "reference_material"],
        template=prompt_template
    )
    
    # 온도를 약간 높여서 문체 복제력을 향상시킵니다 (0.7 -> 0.8)
    llm = ChatGoogleGenerativeAI(model="models/gemini-flash-latest", temperature=0.8)
    chain = prompt | llm
    
    print("사용자님의 문체를 분석하여 글을 작성 중입니다...")
    response = chain.invoke({
        "style_reference": style_reference,
        "new_topic": new_topic,
        "reference_material": reference_material
    })
    
    # 결과가 리스트 형식일 경우 문자열로 합쳐줍니다.
    result_text = response.content
    if isinstance(result_text, list):
        parts = []
        for part in result_text:
            if isinstance(part, dict) and 'text' in part:
                parts.append(part['text'])
            else:
                parts.append(str(part))
        result_text = "".join(parts)
        
    return result_text

# 6. Legacy support (UI용)
def build_blog_db(urls, persist_directory="./chroma_db"):
    return build_blog_db_from_urls(urls, persist_directory)

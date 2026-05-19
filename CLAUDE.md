# CLAUDE.md — Raton AI Codebase Guide

## Project Overview

This repository contains two independent Streamlit web applications that use Google Gemini AI for Korean real-estate and blogging workflows. Both apps are targeted at a Korean-speaking user ("라톤") and all user-facing text is in Korean.

---

## Repository Structure

```
gemini-test/
├── app.py                  # App 1: Naver Blog AI Writer (main app)
├── main.py                 # Core logic for App 1 (crawling, RAG, generation)
├── debug_test.py           # Debug script for testing Naver blog crawl
├── requirements.txt        # Dependencies for App 1
├── run_blog.bat            # Windows launcher for App 1
├── .env                    # API keys (GEMINI_API_KEY)
├── chroma_db/              # Persisted ChromaDB vector store (auto-created)
├── fonts/
│   ├── NanumGothic.ttf
│   └── NanumGothicBold.ttf # Korean fonts used by APPLY image generation
├── APPLY/
│   ├── app.py              # App 2: Real-estate subscription (분양) analysis
│   ├── requirements.txt    # Dependencies for App 2 (separate)
│   └── prompt.txt          # Gemini extraction prompt for PDF parsing
├── README.md
└── README.txt              # Setup instructions for new machines
```

---

## App 1: Naver Blog AI Writer (`app.py` + `main.py`)

### Purpose
Learns a user's Naver blog writing style via RAG (ChromaDB + Gemini Embeddings), then generates new blog posts that mimic that style given a topic and optional reference material.

### Architecture
```
Naver Blog URLs → HTML scrape (main.py) → ChromaDB vector store
                                              ↓
Topic + reference material → Retriever (k=7) → Gemini Flash → Generated post
```

### Key functions in `main.py`

| Function | Description |
|---|---|
| `get_naver_blog_content(url)` | Scrapes blog post body via BeautifulSoup; handles `blog.naver.com` URL formats |
| `get_naver_blog_urls_by_id(blog_id, page_count)` | Fetches post URLs from Naver's `PostTitleListAsync.naver` API using regex to extract `logNo` values |
| `build_blog_db_from_urls(urls, persist_directory)` | Incremental upsert into ChromaDB: loads existing DB, skips already-indexed URLs, embeds new posts in batches of 1 with 5-second delays to respect Gemini quota |
| `generate_blog_post(vectorstore, new_topic, reference_material)` | RAG pipeline: retrieves 7 style-reference chunks → fills PromptTemplate → calls Gemini Flash at temperature 0.8 |
| `build_blog_db(urls, persist_directory)` | Alias for `build_blog_db_from_urls`; used by Streamlit UI |

### Streamlit UI (`app.py`)
- On startup, auto-loads existing `chroma_db/` if present
- Sidebar: enter Naver blog ID, choose page count (1–20), fetch URLs, then run incremental training
- Main area: enter topic + reference text, generate post, download as `.txt`

### Running App 1
```bash
pip install -r requirements.txt
streamlit run app.py
# or on Windows: double-click run_blog.bat
```

---

## App 2: Real-estate Subscription Analyzer (`APPLY/app.py`)

### Purpose
Parses Korean real-estate subscription announcement PDFs (분양 공고문) using Gemini AI, then generates a set of styled info-card images and a formatted blog summary text for easy copy-paste into Naver/Tistory blogs.

### Architecture
```
PDF upload → pdfplumber (text + table extraction) → Gemini (APPLY/prompt.txt) → JSON data
→ validate_input_data() → create_styled_image() × N → PIL images
→ get_blog_summary_text() → Markdown blog text
```

### Key functions in `APPLY/app.py`

| Function | Description |
|---|---|
| `extract_option_pages(pdf_file, start_page, end_page)` | Extracts a page range from PDF using pypdf; returns bytes |
| `draw_text_with_wrap(draw, text, position, font, max_width, ...)` | PIL text renderer with manual word-wrap for Korean text |
| `parse_price(ratio_str, total_price)` | Parses price ratios (`"10%"`, `"1,000만원"`, `"0.1"`) into integer 만원 values |
| `validate_input_data(json_str, cofix)` | Strips markdown fences, parses JSON, normalises units (원→만원), injects live COFIX rate |
| `create_styled_image(data, title, target_type, all_data, extra_info)` | Main image factory: dispatches on `title` to render different table layouts (payment plan, price table, schedule, etc.) using Pillow |
| `get_blog_summary_text(data, target_type, total_intr)` | Produces formatted Korean blog text with all key figures (prices, schedule, interest) |

### JSON schema (output of Gemini extraction)
See `APPLY/prompt.txt` for the full extraction rules. The validated data dict has these top-level keys:
`주요내용`, `청약일정`, `공급규모`, `세대수`, `분양가`, `납부일정`, `is_same`, `옵션_일정`, `발코니_일정`, `발코니_확장비`, `대출정보`, `is_metropolitan`, `가점제_비율`, `에어컨_비용`, `중문_비용`

### Running App 2
```bash
cd APPLY
pip install -r requirements.txt
# Copy fonts/ from project root to APPLY/ if running standalone
streamlit run app.py
```
The app is normally run from the project root with the fonts path resolved relatively.

---

## Environment & Configuration

### `.env` (root)
```
GEMINI_API_KEY=<your_key>
```
App 1 loads this via `python-dotenv`. App 2 also accepts the key via a sidebar text input at runtime.

### Models used
| App | Model | Usage |
|---|---|---|
| App 1 | `models/gemini-embedding-001` | Document embeddings (LangChain) |
| App 1 | `models/gemini-flash-latest` | Blog post generation |
| App 2 | `gemini-3-flash-preview` | PDF data extraction |

### Fonts
`fonts/NanumGothic.ttf` and `fonts/NanumGothicBold.ttf` are required for image generation in App 2. `create_styled_image` falls back to `/usr/share/fonts/truetype/nanum/` on Linux if not found locally.

### ChromaDB persistence
`chroma_db/` is created in the working directory when the first blog is indexed. It uses the HNSW index. Commit or back up this directory to preserve training data across machines.

---

## Development Conventions

### Python style
- UTF-8 encoding declared at the top of each file (`# -*- coding: utf-8 -*-`)
- Korean comments throughout; variable names are a mix of English and Korean
- No type annotations; no unit tests

### Error handling
- Network calls (Naver scraping, Gemini API) catch broad `Exception` and log via `print` or `st.error`
- Rate-limit handling: 429 responses trigger exponential back-off (20s, 40s, 60s) in `build_blog_db_from_urls`
- Batch size for ChromaDB ingestion is 1 document at a time with a 5-second sleep to stay within Gemini free-tier quota

### Import compatibility shim
`main.py` uses try/except import blocks for `langchain` vs `langchain_core` to support both older and newer LangChain versions:
```python
try:
    from langchain_core.prompts import PromptTemplate
except ImportError:
    from langchain.prompts import PromptTemplate
```

### Price/unit conventions (App 2)
- All monetary values are stored internally in **만원** (10,000 KRW) as integers
- `parse_price` converts any string representation to this unit
- Display strings multiply by 10,000 for 원 display: `f"{int(p*10000):,}"`
- The `validate_input_data` function auto-corrects values > 1,000,000 that were accidentally stored in 원 instead of 만원

---

## Known Issues / Gotchas

1. **API key hardcoded in `APPLY/app.py` line 417**: The Gemini key is set as the default value of a `st.text_input`. This leaks the key in source. Replace with `os.getenv("GEMINI_API_KEY", "")` when refactoring.

2. **`time` import order in `main.py`**: `time` is imported inside the file body (line 123) after first use at line 110 inside `get_naver_blog_urls_by_id`. This causes a `NameError` if that function is called before the module-level import is reached. Move `import time` to the top of the file.

3. **`APPLY/app.py` assumes `gemini-3-flash-preview`**: This is an experimental preview model name. If it is unavailable, replace with `gemini-1.5-flash` or `gemini-2.0-flash`.

4. **`chroma_db/` is committed**: The binary ChromaDB files are checked in. Add `chroma_db/` to `.gitignore` for clean version control; distribute DB separately.

5. **`__pycache__.7z`**: A compressed archive of `__pycache__` is committed. It serves no runtime purpose and should not be re-committed.

---

## Common Tasks

### Add a new image card type to App 2
1. Add a new `elif title == "새 카드명":` block inside `create_styled_image` in `APPLY/app.py`
2. Set `row_count` and draw the table using `draw.rectangle` + `draw.text`
3. Set `table_bottom_y` to `y_start + (row_count * ROW_H)`
4. Add the card to the `imgs` dict inside the `"🔄 이미지 새로고침"` button handler

### Update the PDF extraction prompt
Edit `APPLY/prompt.txt`. The prompt is read at runtime on every "AI 분석 시작" button press, so no code change is needed.

### Add a new Naver blog to training data
Use the sidebar in App 1: enter the blog ID, fetch URLs, click "새로운 글 추가 학습". The function skips already-indexed URLs automatically.

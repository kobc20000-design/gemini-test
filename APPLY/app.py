import streamlit as st
import os
import json
import re
import pdfplumber
import textwrap
import math
import io
import zipfile
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import google.generativeai as genai
from dotenv import load_dotenv
from pypdf import PdfReader, PdfWriter
import base64

# 1. 페이지 설정 및 세션 상태 초기화
st.set_page_config(page_title="라톤의 재테크 마라톤 - 분양 분석", layout="wide")

if "extracted_data" not in st.session_state:
    st.session_state.extracted_data = None
if "generated_images" not in st.session_state:
    st.session_state.generated_images = {}
if "blog_summary" not in st.session_state:
    st.session_state.blog_summary = ""
if "option_pdf" not in st.session_state:
    st.session_state.option_pdf = None

# PDF 옵션 페이지 추출 함수 (범위 기반)
def extract_option_pages(pdf_file, start_page, end_page):
    reader = PdfReader(pdf_file)
    writer = PdfWriter()
    total_pages = len(reader.pages)
    
    # 페이지 인덱스 보정 (1-based to 0-based) 및 범위 제한
    start_idx = max(0, start_page - 1)
    end_idx = min(total_pages, end_page)
    
    found_pages = []
    for i in range(start_idx, end_idx):
        writer.add_page(reader.pages[i])
        found_pages.append(i + 1)
            
    if found_pages:
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue(), found_pages
    return None, []

# 2. 유틸리티 및 이미지 생성 엔진

def draw_text_with_wrap(draw, text, position, font, max_width, fill="black", anchor="mm", align="center"):
    x, y = position
    wrap_w = 50 if max_width > 500 else 15
    lines = []
    for part in str(text).split('\n'):
        lines.extend(textwrap.wrap(part, width=wrap_w))
    line_height = font.getbbox("가")[3] + 10
    total_height = len(lines) * line_height
    current_y = y - (total_height / 2) + (line_height / 2)
    for line in lines:
        draw.text((int(x), int(current_y)), line, fill=fill, anchor=anchor, font=font, align=align)
        current_y += line_height

def parse_price(ratio_str, total_price):
    ratio_str = str(ratio_str).strip()
    if ratio_str.replace('.', '', 1).isdigit():
        try:
            val = float(ratio_str)
            if val < 1: return int(total_price * val)
            return int(total_price * val / 100)
        except: return 0
    if "만원" in ratio_str and "%" not in ratio_str: 
        num = re.sub(r'[^0-9]', '', ratio_str)
        return int(num) if num else 0
    if "%" in ratio_str:
        parts = ratio_str.split('%')
        ratio = float(re.sub(r'[^0-9.]', '', parts[0])) / 100
        minus = int(re.sub(r'[^0-9]', '', parts[1])) if len(parts) > 1 and '-' in parts[1] else 0
        return int(total_price * ratio) - minus
    return 0

def validate_input_data(json_str, cofix):
    try:
        clean_json = re.sub(r'```json|```', '', json_str).strip()
        data = json.loads(clean_json)
        # 만원 단위 보정 로직
        for key in ["분양가", "발코니_확장비"]:
            if key in data and isinstance(data[key], dict):
                for t, v in data[key].items():
                    num_str = re.sub(r'[^0-9]', '', str(v))
                    if num_str and int(num_str) > 1000000: data[key][t] = int(num_str) // 10000
        for key in ["에어컨_비용", "중문_비용"]:
            if key in data:
                num_str = re.sub(r'[^0-9]', '', str(data[key]))
                if num_str and int(num_str) > 1000000: data[key] = int(num_str) // 10000
        if '대출정보' in data: data['대출정보']['cofix'] = cofix
        return data
    except Exception as e:
        st.error(f"⚠️ 데이터 형식 에러: {e}")
        return None

def create_styled_image(data, title, target_type, all_data, extra_info=None):
    if data is None: return None
    
    scale = 3.0 if title == "분양가 납부 계획" else 1.0
    ROW_H, width, y_start = int(150 * scale), int(1000 * scale), int(100 * scale)
    header_color, label_bg, border_color = (19, 41, 75), (235, 237, 240), (0, 0, 0)

    try:
        font_path, font_reg_path = "fonts/NanumGothicBold.ttf", "fonts/NanumGothic.ttf"
        if not os.path.exists(font_path):
            font_path = "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"
            font_reg_path = "/usr/share/fonts/truetype/nanum/NanumGothic.ttf"
        font_header = ImageFont.truetype(font_path, int(52 * scale))
        font_item = ImageFont.truetype(font_path, int(34 * scale))
        font_value = ImageFont.truetype(font_reg_path, int(34 * scale))
    except:
        font_header = font_item = font_value = ImageFont.load_default()

    is_metro = all_data.get("is_metropolitan", False)

    # 행 개수 결정
    if title == "분양가 납부 계획":
        col_w = [int(x * scale) for x in [360, 380, 400, 310, 380, 380]]
        width = sum(col_w) + 20
        row_count = len(data) + 2
    elif title == "일반분양 가점제 및 추첨제 세대수": 
        row_count = len(all_data.get('세대수', [])) + (2 if is_metro else 1)
    elif title == "중도금대출 이자": 
        row_count = (len([d for d in all_data.get('납부일정', []) if "중도금" in d.get('항목', '')]) + 2)
    elif title == "타입별 세대수": 
        row_count = len(data if isinstance(data, list) else []) + 1
    elif title in ["분양가", "발코니 확장비"]: 
        row_count = (len(data.keys()) + 1) // 2
    elif title == "공급규모":
        row_count = 3
    elif title == "주요내용":
        row_count = 3
    elif title == "청약일정":
        row_count = 3
    elif isinstance(data, list):
        row_count = len(data)
    else: 
        row_count = 3

    image = Image.new("RGB", (width, y_start + (row_count * ROW_H) + 20), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([10, 10, width-10, int(100 * scale)], fill=header_color)
    draw.text((int(width/2), int(55 * scale)), title, fill="white", anchor="mm", font=font_header)
    table_bottom_y = y_start

    # --- 테이블 그리기 로직 상세 구현 ---
    
    if title == "분양가 납부 계획":
        col_headers = ["", "분양가", "발코니확장비", "옵션", "총합", "일자"]; curr_x = 10
        for i, h in enumerate(col_headers):
            draw.rectangle([curr_x, y_start, curr_x + col_w[i], y_start + ROW_H], fill="white")
            draw.text((int(curr_x + col_w[i]/2), int(y_start + ROW_H/2)), h, fill="black", anchor="mm", font=font_item)
            curr_x += col_w[i]
        s_total = all_data['분양가'].get(target_type, 0); b_total = all_data.get('발코니_확장비', {}).get(target_type, 0)
        o_total = all_data.get("에어컨_비용", 0) + all_data.get("중문_비용", 0)
        is_same = all_data.get("is_same", False); opt_src = all_data.get("옵션_일정", [])
        bal_src = opt_src if is_same else all_data.get("발코니_일정", [])
        o_mid = [i for i in opt_src if "중도금" in i['항목']]; o_con = [i for i in opt_src if "계약" in i['항목']]; o_rem = [i for i in opt_src if "잔금" in i['항목']]
        b_mid = [i for i in bal_src if "중도금" in i['항목']]; b_con = [i for i in bal_src if "계약" in i['항목']]; b_rem = [i for i in bal_src if "잔금" in i['항목']]
        c_i, m_i, r_i, g_total = 0, 0, 0, 0
        for idx, step in enumerate(data):
            curr_y = y_start + ((idx + 1) * ROW_H); fill = label_bg if idx % 2 != 0 else "white"
            s_v = parse_price(step.get("비율", 0), s_total); b_v = 0; o_v = 0
            if "계약" in step['항목']:
                if c_i < len(o_con): o_v = parse_price(o_con[c_i]['비율'], o_total)
                if c_i < len(b_con): b_v = parse_price(b_con[c_i]['비율'], b_total)
                c_i += 1
            elif "중도금" in step['항목']:
                if m_i < len(o_mid): o_v = parse_price(o_mid[m_i]['비율'], o_total)
                if m_i < len(b_mid): b_v = parse_price(b_mid[m_i]['비율'], b_total)
                m_i += 1
            elif "잔금" in step['항목']:
                if r_i < len(o_rem): o_v = parse_price(o_rem[r_i]['비율'], o_total)
                if r_i < len(b_rem): b_v = parse_price(b_rem[r_i]['비율'], b_total)
                r_i += 1
            r_sum = s_v + b_v + o_v; g_total += r_sum
            vals = [step['항목'], f"{s_v*10000:,}", f"{b_v*10000:,}" if b_v>0 else "-", f"{o_v*10000:,}" if o_v>0 else "-", f"{r_sum*10000:,}", step['날짜']]; curr_x = 10
            for ci, val in enumerate(vals):
                draw.rectangle([curr_x, curr_y, curr_x + col_w[ci], curr_y + ROW_H], fill=fill)
                draw.text((int(curr_x + (col_w[ci]-20 if 1<=ci<=4 else col_w[ci]/2)), int(curr_y+ROW_H/2)), str(val), fill="black", anchor="rm" if 1<=ci<=4 else "mm", font=font_value); curr_x += col_w[ci]
        f_sum = (g_total * 10000) + (extra_info if extra_info else 0)
        curr_y += ROW_H; draw.rectangle([10, curr_y, width-col_w[-1]-10, curr_y + ROW_H], fill="white")
        draw.text((int(40 * scale), int(curr_y + ROW_H/2)), "최종 분양가(분양가 + 발코니 + 옵션" + (" + 중도금이자)" if extra_info else ")"), fill="black", anchor="lm", font=font_item)
        draw.text((int(width-30), int(curr_y + ROW_H/2)), f"{int(f_sum):,}", fill="red", anchor="rm", font=font_item)
        table_bottom_y = curr_y + ROW_H

    elif title == "일반분양 가점제 및 추첨제 세대수":
        if is_metro:
            col_w, colors = [130, 160, 160, 170, 170, 190], [(255, 255, 255), (255, 230, 215), (211, 211, 211), (220, 245, 220)]
            for i, txt in enumerate(["타입", "일반공급", "가점제"]):
                draw.rectangle([10+sum(col_w[:i]), y_start, 10+sum(col_w[:i+1]), y_start+(ROW_H*2)], fill=colors[i]); draw.text((int(10+sum(col_w[:i])+col_w[i]/2), int(y_start+ROW_H)), txt, fill="black", anchor="mm", font=font_item)
            draw.rectangle([10+sum(col_w[:3]), y_start, 990, y_start+ROW_H], fill=colors[3]); draw.text((int(10+sum(col_w[:3])+sum(col_w[3:6])/2), int(y_start+ROW_H/2)), "추첨제", fill="black", anchor="mm", font=font_item)
            curr_x, sub_h = 10+sum(col_w[:3]), ["총 세대수", "무주택자", "1주택자\n&\n무주택자"]
            for i, txt in enumerate(sub_h):
                draw.rectangle([curr_x, y_start+ROW_H, curr_x+col_w[i+3], y_start+(ROW_H*2)], fill="white"); draw_text_with_wrap(draw, txt, (curr_x+col_w[i+3]/2, y_start+ROW_H+ROW_H/2), font_value, col_w[i+3]); curr_x += col_w[i+3]
            for r_idx, s in enumerate(all_data.get('세대수', [])):
                try:
                    size_num = int(re.search(r'\d+', s['타입']).group()); cat = "60이하" if size_num <= 60 else ("85이하" if size_num <= 85 else "85초과"); ratio = all_data.get("가점제_비율", {}).get(cat, 40)/100
                    curr_y, gen = y_start+(ROW_H*2)+(r_idx*ROW_H), int(s.get('일반공급', 0)); p, d = math.ceil(gen*ratio), gen-math.ceil(gen*ratio); h, o = math.ceil(d*0.75), d-math.ceil(d*0.75)
                    vals = [s['타입'], f"{gen}세대", f"{p}세대", f"{d}세대", f"{h}세대", f"{o}세대"]; curr_x = 10
                    for c_idx, val in enumerate(vals):
                        draw.rectangle([curr_x, curr_y, curr_x+col_w[c_idx], curr_y+ROW_H], fill=label_bg if r_idx%2!=0 else "white"); draw.text((int(curr_x+(col_w[c_idx]-20 if c_idx>0 else col_w[c_idx]/2)), int(curr_y+ROW_H/2)), str(val), fill="black", anchor="rm" if c_idx>0 else "mm", font=font_value); curr_x += col_w[c_idx]
                except: pass
            table_bottom_y = y_start + (len(all_data.get('세대수', [])) + 2) * ROW_H
        else:
            col_w, headers = [240, 250, 250, 250], ["타입", "일반공급", "가점제", "추첨제"]
            for i, h in enumerate(headers):
                draw.rectangle([10+sum(col_w[:i]), y_start, 10+sum(col_w[:i+1]), y_start+ROW_H], fill="white"); draw.text((int(10+sum(col_w[:i])+col_w[i]/2), int(y_start+ROW_H/2)), h, fill="black", anchor="mm", font=font_item)
            for r_idx, s in enumerate(all_data.get('세대수', [])):
                try:
                    size_num = int(re.search(r'\d+', s['타입']).group()); cat = "60이하" if size_num <= 60 else ("85이하" if size_num <= 85 else "85초과"); ratio = all_data.get("가점제_비율", {}).get(cat, 40)/100
                    curr_y, gen = y_start+ROW_H+(r_idx*ROW_H), int(s.get('일반공급', 0)); p = math.ceil(gen*ratio); vals = [s['타입'], f"{gen}세대", f"{p}세대", f"{gen-p}세대"]; curr_x = 10
                    for c_idx, val in enumerate(vals):
                        draw.rectangle([curr_x, curr_y, curr_x+col_w[c_idx], curr_y+ROW_H], fill=label_bg if r_idx%2!=0 else "white"); draw.text((int(curr_x+(col_w[c_idx]-20 if c_idx>0 else col_w[c_idx]/2)), int(curr_y+ROW_H/2)), str(val), fill="black", anchor="rm" if c_idx>0 else "mm", font=font_value); curr_x += col_w[c_idx]
                except: pass
            table_bottom_y = y_start + (len(all_data.get('세대수', [])) + 1) * ROW_H

    elif title == "타입별 세대수":
        headers, col_w = ["타입", "특별공급", "일반공급", "세대수"], [160, 273, 273, 274]
        rows = [headers] + data
        for r_idx, row in enumerate(rows):
            curr_y, curr_x = y_start+(r_idx*ROW_H), 10; fill = label_bg if r_idx > 0 and r_idx % 2 == 0 else "white"
            for c_idx, h in enumerate(headers):
                val = str(row.get(h, '-')) if r_idx > 0 else row[c_idx]
                if r_idx > 0 and c_idx > 0 and val != '-':
                    num_str = re.sub(r'[^0-9]', '', str(val)); val = f"{int(num_str):,}세대" if num_str else val
                draw.rectangle([curr_x, curr_y, curr_x + col_w[c_idx], curr_y + ROW_H], fill=fill); draw.text((int(curr_x + (col_w[c_idx] - 20 if r_idx > 0 and c_idx > 0 else col_w[c_idx]/2)), int(curr_y+ROW_H/2)), val, fill="black", anchor="rm" if r_idx > 0 and c_idx > 0 else "mm", font=font_item if r_idx==0 or c_idx==0 else font_value); curr_x += col_w[c_idx]
        table_bottom_y = y_start + (len(rows) * ROW_H)

    elif title == "중도금대출 이자":
        col_headers, col_w, total_interest_calc = ["", "대출 여부", "대출 원금", "대출이자"], [240, 200, 280, 260], 0
        total_p = all_data['분양가'].get(target_type, 0); mid_items = [d for d in all_data.get('납부일정', []) if "중도금" in d.get('항목', '')]
        move_in = datetime.strptime(re.sub(r'[^0-9]', '', all_data.get("공급규모", {}).get("입주시기", "202703"))[:6] + "01", "%Y%m%d"); l_info = all_data.get("대출정보", {})
        for i, h in enumerate(col_headers):
            draw.rectangle([10+sum(col_w[:i]), y_start, 10+sum(col_w[:i+1]), y_start+ROW_H], fill="white"); draw.text((int(10+sum(col_w[:i])+col_w[i]/2), int(y_start+ROW_H/2)), h, fill="black", anchor="mm", font=font_item)
        for r_idx, item in enumerate(mid_items):
            curr_y = y_start+ROW_H+(r_idx*ROW_H); is_l = item.get("대출여부", "O") == "O"; p = parse_price(item.get("비율", "10%"), total_p); intr = 0
            if is_l and item.get('날짜') and re.search(r'\d', str(item['날짜'])):
                try: d_str = re.sub(r'[^0-9]', '', str(item['날짜']))[:8]; days = (move_in - datetime.strptime(d_str, "%Y%m%d")).days; intr = p * ((l_info.get('cofix', 3.4)+l_info.get('가산금리', 1.5))/100) * (days/365)
                except: intr = 0
            total_interest_calc += intr; vals = [item.get('항목', '-'), item.get("대출여부", "O"), f"{int(p*10000):,}", f"{int(intr*10000):,}"]; curr_x = 10
            for c_idx, v in enumerate(vals):
                draw.rectangle([curr_x, curr_y, curr_x+col_w[c_idx], curr_y+ROW_H], fill=label_bg if (r_idx+1)%2!=0 else "white"); draw.text((int(curr_x+(col_w[c_idx]-40 if c_idx>=2 else col_w[c_idx]/2)), int(curr_y+ROW_H/2)), str(v), fill="black", anchor="rm" if c_idx>=2 else "mm", font=font_value); curr_x += col_w[c_idx]
        curr_y += ROW_H; draw.rectangle([10, curr_y, 730, curr_y+ROW_H], fill=label_bg); draw.text((370, int(curr_y+ROW_H/2)), "이자 합계", fill="black", anchor="mm", font=font_item)
        draw.rectangle([730, curr_y, 990, curr_y+ROW_H], fill=label_bg); draw.text((950, int(curr_y+ROW_H/2)), f"{int(total_interest_calc*10000):,}", fill="red", anchor="rm", font=font_item); table_bottom_y = curr_y + ROW_H

    elif title in ["분양가", "발코니 확장비"]:
        keys, col_w = list(data.keys()), [180, 310, 180, 310]
        for r_idx in range((len(keys)+1)//2):
            curr_y, curr_x = y_start + (r_idx*ROW_H), 10
            for pair in range(2):
                idx = r_idx*2 + pair
                if idx < len(keys):
                    k = keys[idx]; price_val = int(data[k]); v = "무상" if price_val == 0 else f"{price_val:,}만원"
                    draw.rectangle([curr_x, curr_y, curr_x+col_w[pair*2], curr_y+ROW_H], fill=label_bg); draw.text((int(curr_x+col_w[pair*2]/2), int(curr_y+ROW_H/2)), k, fill="black", anchor="mm", font=font_item); curr_x += col_w[pair*2]
                    draw.rectangle([curr_x, curr_y, curr_x+col_w[pair*2+1], curr_y+ROW_H], fill="white"); draw.text((int(curr_x+col_w[pair*2+1]-40), int(curr_y+ROW_H/2)), v, fill="black", anchor="rm", font=font_value); curr_x += col_w[pair*2+1]
        table_bottom_y = y_start + ((len(keys)+1)//2) * ROW_H

    elif "납부일정" in title or (isinstance(data, list) and "일정" in title):
        col_w, items = [240, 370, 370], data
        for r_idx, item in enumerate(items):
            curr_y, curr_x = y_start + (r_idx * ROW_H), 10; fill = label_bg if r_idx % 2 != 0 else "white"
            row_vals = [str(item.get('항목', '-')), str(item.get('비율', '-')), str(item.get('날짜', '-'))]
            for c_idx, text in enumerate(row_vals):
                draw.rectangle([curr_x, curr_y, curr_x + col_w[c_idx], curr_y + ROW_H], fill=fill); draw.text((int(curr_x + col_w[c_idx]/2), int(curr_y + ROW_H/2)), str(text), fill="black", anchor="mm", font=font_value); curr_x += col_w[c_idx]
        table_bottom_y = y_start + (len(data) * ROW_H)

    else:
        # 주요내용, 공급규모, 청약일정 (격자 그리드)
        if title == "공급규모": 
            items, col_w = [("주택위치", data.get('주택위치', '-')), ("공급규모", data.get('공급규모', '-')), ("입주시기", data.get('입주시기', '-'))], [250, 730]
        elif title == "주요내용": 
            items, col_w = [("택지 유형", data.get('택지유형', 'X'), "전매 제한", data.get('전매제한', 'X')), ("규제 지역", data.get('규제지역', 'X'), "거주 의무", data.get('거주의무', 'X')), ("분양가상한", data.get('분양가상한', 'X'), "재당첨제한", data.get('재당첨제한', 'X'))], [180, 310, 180, 310]
        else: # 청약일정
            items, col_w = [("모집공고", data.get('모집공고', '-'), "특별공급", data.get('특별공급', '-')), ("1순위", data.get('1순위', '-'), "2순위", data.get('2순위', '-')), ("당첨발표", data.get('당첨발표', '-'), "계약일자", data.get('계약일자', '-').replace("~", "\n~ "))], [180, 310, 180, 310]
        
        for r_idx, row in enumerate(items):
            curr_y, curr_x = y_start + (r_idx * ROW_H), 10
            for c_idx, text in enumerate(row):
                draw.rectangle([curr_x, curr_y, curr_x + col_w[c_idx], curr_y + ROW_H], fill=label_bg if c_idx % 2 == 0 else "white")
                draw_text_with_wrap(draw, text, (curr_x + col_w[c_idx]/2, curr_y + ROW_H/2), font_item if c_idx%2==0 else font_value, col_w[c_idx])
                curr_x += col_w[c_idx]
        table_bottom_y = y_start + (len(items) * ROW_H)

    draw.rectangle([10, 10, width-10, table_bottom_y], outline=border_color, width=4)
    return image

# 3. 블로그 요약 생성 함수
def get_blog_summary_text(data, target_type, total_intr):
    s_p, b_p, o_p = data['분양가'].get(target_type, 0), data.get('발코니_확장비', {}).get(target_type, 0), data.get('에어컨_비용', 0) + data.get('중문_비용', 0)
    f_sum = (s_p + b_p + o_p) * 10000 + total_intr; pay_plan = data.get('납부일정', [])
    bal_plan = data.get('발코니_일정', []) if data.get('발코니_일정') else [{'비율': '0%', '날짜': '-'}]
    opt_plan = data.get('옵션_일정', []) if data.get('옵션_일정') else [{'비율': '0%', '날짜': '-'}]
    if data.get('is_same'): bal_plan = opt_plan = data.get('옵션_일정', [])
    
    # 규제 정보 줄바꿈 정리
    reg_text = f"""[주요 규제 및 내용]
✅ 택지유형 : {data['주요내용'].get('택지유형', '-')}
✅ 전매제한 : {data['주요내용'].get('전매제한', '-')}
✅ 규제지역 : {data['주요내용'].get('규제지역', '-')}
✅ 거주의무 : {data['주요내용'].get('거주의무', '-')}
✅ 분양가상한 : {data['주요내용'].get('분양가상한', '-')}
✅ 재당첨제한 : {data['주요내용'].get('재당첨제한', '-')}"""

    summary = f"""{reg_text}

[청약일정]
✅ 모집공고 : {data['청약일정'].get('모집공고', '-')}
✅ 특별공급 : {data['청약일정'].get('특별공급', '-')}
✅ 일반공급 : {data['청약일정'].get('1순위', '-')} (1순위), {data['청약일정'].get('2순위', '-')} (2순위)
✅ 당첨발표 : {data['청약일정'].get('당첨발표', '-')}
✅ 계약일자 : {data['청약일정'].get('계약일자', '-')}

✔️ 가점제 비율
"""
    # 존재하는 평형대 카테고리 파악 및 비율 문구 생성
    size_cats = set()
    for s in data.get('세대수', []):
        try:
            size_match = re.search(r'\d+', str(s['타입']))
            if size_match:
                size = int(size_match.group())
                cat = "60이하" if size <= 60 else ("85이하" if size <= 85 else "85초과")
                size_cats.add(cat)
        except: continue
    
    ratios = data.get("가점제_비율", {"60이하": 40, "85이하": 40, "85초과": 0})
    if "60이하" in size_cats:
        summary += f"✅ 전용면적 60㎡ 이하 : {ratios.get('60이하', 40)}%\n"
    if "85이하" in size_cats:
        summary += f"✅ 전용면적 60㎡ 초과 85㎡ 이하 : {ratios.get('85이하', 40)}%\n"
    if "85초과" in size_cats:
        summary += f"✅ 전용면적 85㎡ 초과 : {ratios.get('85초과', 0)}%\n"

    summary += "\n✔️추첨제 물량\n"
    for s in data.get('세대수', []):
        try:
            size_match = re.search(r'\d+', str(s['타입']))
            if size_match:
                size = int(size_match.group())
                cat = "60이하" if size <= 60 else ("85이하" if size <= 85 else "85초과")
                ratio = data.get("가점제_비율", {}).get(cat, 40)/100
                gen = int(s.get('일반공급', 0))
                lottery = gen - math.ceil(gen * ratio)
                summary += f"✅ 전용면적 {s['타입']} : {lottery} 세대\n"
        except: continue
    
    summary += "\n[분양가]\n"
    for t, p in data.get('분양가', {}).items():
        summary += f"✅ 전용면적 {t}㎡ : {int(p):,}만원\n"

    summary += f"""
[분양가 납부 계획 ({target_type}타입 기준)]
✨ 계약금
✅ 1차 계약({pay_plan[0]['날짜'] if len(pay_plan)>0 else '-'}) : {pay_plan[0]['비율'] if len(pay_plan)>0 else '0%'}
✅ 2차 계약(30일 이내) : {pay_plan[1]['비율'] if len(pay_plan)>1 else '0%'}

✨ 중도금
✅ 시행사에서 집단대출 알선 ({data['대출정보'].get('이자 방식', '-')})
✅ 최대 {data['대출정보'].get('대출 비율', 60)}%까지 가능

✨ 잔금
✅ 잔금일({data['공급규모'].get('입주시기', '-')} 예정) : 잔금 + 중도금이자

[옵션 및 발코니 납부 계획]
"""
    if data.get('옵션_일정'):
        summary += "\n✨계약금\n"
        for item in [i for i in data['옵션_일정'] if "계약" in i['항목']]:
            summary += f"✅계약일({item.get('날짜', '-')}) : {item.get('비율', '-')}\n"
        
        summary += "\n✨잔금\n"
        for item in [i for i in data['옵션_일정'] if "잔금" in i['항목']]:
            summary += f"✅잔금일({item.get('날짜', '-')}) : {item.get('비율', '-')}\n"

    # 구체적인 납부 금액 섹션
    s_p_val = parse_price(pay_plan[0]['비율'] if len(pay_plan)>0 else '0', s_p)
    b_p_val = parse_price(bal_plan[0]['비율'] if len(bal_plan)>0 else '0', b_p)
    o_p_val = parse_price(opt_plan[0]['비율'] if len(opt_plan)>0 else '0', o_p)
    
    first_pay = int(s_p_val + b_p_val + o_p_val)
    second_pay = int(parse_price(pay_plan[1]['비율'] if len(pay_plan)>1 else '0', s_p))
    
    # 잔금 계산 (분양가 잔금 + 발코니 잔금 + 옵션 잔금 + 중도금 이자)
    try:
        last_pay_ratio = 100 - sum([float(re.sub(r'[^0-9.]', '', str(item['비율']))) for item in pay_plan if "잔금" not in item['항목']])
    except:
        last_pay_ratio = 10.0
    total_last_pay = int(s_p * (last_pay_ratio/100) + b_p * 0.9 + o_p * 0.9 + (total_intr/10000))

    summary += f"""
[구체적인 납부 금액 ({target_type}타입, 옵션/발코니 포함)]
✨계약금
✅1차 계약({pay_plan[0]['날짜'] if len(pay_plan)>0 else '-'}) : {first_pay:,}만원(분양가, 옵션, 발코니확장비 계약금)
✅2차 계약({pay_plan[1]['날짜'] if len(pay_plan)>1 else '0%'}) : {second_pay:,}만원(분양가 계약금)

✨중도금
✅중도금대출 최대 {data['대출정보'].get('대출 비율', 60)}%까지 가능 
✅중도금대출 {data['대출정보'].get('이자 방식', '-')}

✨잔금
✅잔금일({data['공급규모'].get('입주시기', '-')} 예정) : {total_last_pay:,}만원(분양가, 발코니, 옵션, 중도금이자)

따라서 옵션, 발코니확장비, 중도금이자를 포함한 최종 분양가는 {int(f_sum//100000000)}억 {int((f_sum%100000000)//10000):,}만원입니다."""
    return summary.strip()

# 4. 메인 실행 로직 (Streamlit)
with st.sidebar:
    st.title("⚙️ 설정")
    gemini_key = st.text_input("Gemini API Key", value="AIzaSyDE8HYP7CKk0o9e-NI5KOJ8YQQWRLtaVKU", type="password").strip()
    pdf_file = st.file_uploader("분양 공고 PDF 업로드", type="pdf")
    target_type = st.text_input("대상 타입", value="84A")
    cofix = st.number_input("현재 COFIX 금리 (%)", value=2.84, step=0.01)
    
    # 출력 설정 체크박스를 위로 이동
    use_base64 = st.checkbox("Base64 이미지 모드 (티스토리 전용)", value=False, help="체크하면 드래그 복사가 가능하지만 페이지가 무거워집니다.")
    
    if pdf_file:
        st.write("---")
        st.subheader("📄 PDF 페이지 추출")
        col1, col2 = st.columns(2)
        with col1:
            start_p = st.number_input("시작 페이지", min_value=1, value=1, step=1)
        with col2:
            end_p = st.number_input("종료 페이지", min_value=1, value=1, step=1)

        if st.button("📄 설정 범위 추출 (PDF 생성)"):
            with st.spinner("페이지를 추출하는 중..."):
                pdf_bytes, pages = extract_option_pages(pdf_file, start_p, end_p)
                if pdf_bytes:
                    st.session_state.option_pdf = pdf_bytes
                    st.success(f"✅ {len(pages)}개의 페이지가 준비되었습니다! ({pages[0]}p ~ {pages[-1]}p)")
                else:
                    st.warning("⚠️ 페이지를 추출하지 못했습니다.")
        
        if st.session_state.option_pdf:
            st.download_button(
                label="📥 옵션정리.pdf 다운로드",
                data=st.session_state.option_pdf,
                file_name="옵션정리.pdf",
                mime="application/pdf"
            )
        
        # 개별 이미지 다운로드 기능 추가
        if st.session_state.generated_images:
            st.write("---")
            st.subheader("🖼️ 개별 이미지 다운로드")
            img_list = [n for n, i in st.session_state.generated_images.items() if i is not None]
            if img_list:
                selected_img_name = st.selectbox("이미지 선택", img_list)
                img_obj = st.session_state.generated_images[selected_img_name]
                
                # JPG 변환 및 준비
                buf = io.BytesIO()
                # RGBA일 경우 RGB로 변환하여 JPG 저장 가능하게 함
                rgb_img = img_obj.convert("RGB") if img_obj.mode == "RGBA" else img_obj
                rgb_img.save(buf, format="JPEG", quality=95)
                
                st.download_button(
                    label=f"📥 {selected_img_name} 다운로드 (JPG)",
                    data=buf.getvalue(),
                    file_name=f"{selected_img_name}.jpg",
                    mime="image/jpeg"
                )
        st.write("---")

    if st.button("🚀 AI 분석 시작"):
        if not gemini_key or not pdf_file: st.error("키와 파일을 확인하세요.")
        else:
            with st.spinner("표 추출 방식으로 PDF 전체 분석 중..."):
                try:
                    md_content = ""
                    with pdfplumber.open(pdf_file) as pdf:
                        for i, page in enumerate(pdf.pages):
                            md_content += f"\n### PAGE {i+1} ###\n"
                            tables = page.extract_tables()
                            if tables:
                                for table in tables:
                                    for row in table: md_content += " | ".join([str(cell).replace('\n', ' ') if cell else "" for cell in row]) + "\n"
                            md_content += page.extract_text() + "\n"
                    genai.configure(api_key=gemini_key); model = genai.GenerativeModel('gemini-3-flash-preview')
                    
                    # prompt.txt 파일에서 프롬프트 읽기
                    try:
                        with open("APPLY/prompt.txt", "r", encoding="utf-8") as f:
                            USER_PROMPT = f.read()
                    except Exception as e:
                        st.error(f"prompt.txt 파일을 읽을 수 없습니다: {e}")
                        USER_PROMPT = ""
                    
                    res = model.generate_content([md_content, USER_PROMPT]); st.session_state.extracted_data = validate_input_data(res.text, cofix)
                    if st.session_state.extracted_data: st.success("분석 완료!")
                except Exception as e: st.error(f"실패: {e}")

    # 수동 JSON 입력 기능 추가
    st.write("---")
    st.subheader("⌨️ 수동 JSON 입력")
    manual_json = st.text_area("JSON 붙여넣기", height=150, help="API 사용량을 다 썼을 때 유용합니다.")
    if st.button("💾 수동 데이터 적용"):
        try:
            st.session_state.extracted_data = json.loads(manual_json)
            st.success("✅ 수동 데이터가 적용되었습니다! 옆에서 '이미지 및 텍스트 새로고침'을 눌러주세요.")
        except Exception as e:
            st.error(f"⚠️ JSON 형식이 올바르지 않습니다: {e}")

if st.session_state.extracted_data:
    l_col, r_col = st.columns([1, 1])
    with r_col:
        st.subheader("📝 데이터 편집"); edited = st.text_area("JSON", value=json.dumps(st.session_state.extracted_data, indent=2, ensure_ascii=False), height=500)
        try: st.session_state.extracted_data = json.loads(edited)
        except: pass
    with l_col:
        if st.button("🔄 이미지 새로고침"):
            data = st.session_state.extracted_data; t_p = data['분양가'].get(target_type, 0); move_in_str = re.sub(r'[^0-9]', '', data.get("공급규모", {}).get("입주시기", "202712"))
            move_in = datetime.strptime(move_in_str[:6] + "01", "%Y%m%d"); t_intr = 0
            for m in [d for d in data.get('납부일정', []) if "중도금" in d['항목']]:
                if m.get("대출여부") == "O" and m.get("날짜") and re.search(r'\d', str(m['날짜'])):
                    try: t_intr += parse_price(m['비율'], t_p) * ((data['대출정보']['cofix']+data.get('대출정보',{}).get('가산금리',1.5))/100) * ((move_in - datetime.strptime(re.sub(r'[^0-9]', '', str(m['날짜']))[:8], "%Y%m%d")).days/365)
                    except: pass
            t_intr = int(t_intr * 10000); 
            st.session_state.total_interest_val = t_intr # 이자 값 저장

            # 이미지 생성 리스트 (2번 코드 실행부 로직 100% 반영)
            imgs = {
                "1_주요내용": create_styled_image(data['주요내용'], "주요내용", target_type, data),
                "2_청약일정": create_styled_image(data['청약일정'], "청약일정", target_type, data),
                "3_공급규모": create_styled_image(data['공급규모'], "공급규모", target_type, data),
                "4_세대수": create_styled_image(data['세대수'], "타입별 세대수", target_type, data),
                "5_가점추첨": create_styled_image(data, "일반분양 가점제 및 추첨제 세대수", target_type, data),
                "6_분양가": create_styled_image(data['분양가'], "분양가", target_type, data),
                "7_납부일정": create_styled_image(data['납부일정'], "납부일정", target_type, data)
            }

            # 발코니 및 옵션 일정 비교 로직 추가 (내용이 같으면 합침)
            opt_sch = data.get("옵션_일정", [])
            bal_sch = data.get("발코니_일정", [])
            
            # 실제 데이터가 완벽히 일치하는지 비교
            actual_is_same = (json.dumps(opt_sch, sort_keys=True) == json.dumps(bal_sch, sort_keys=True))
            is_same_val = data.get("is_same", True) or actual_is_same
            
            if is_same_val:
                imgs["8_옵션 및 발코니확장비 납부일정"] = create_styled_image(opt_sch if opt_sch else bal_sch, "옵션 및 발코니확장비 납부일정", target_type, data)
                imgs["9_발코니 확장비"] = create_styled_image(data.get("발코니_확장비"), "발코니 확장비", target_type, data)
            else:
                imgs["8_옵션 납부일정"] = create_styled_image(opt_sch, "옵션 납부일정", target_type, data)
                imgs["9_발코니 확장비 납부일정"] = create_styled_image(bal_sch, "발코니 확장비 납부일정", target_type, data)
                imgs["10_발코니 확장비"] = create_styled_image(data.get("발코니_확장비"), "발코니 확장비", target_type, data)

            # 이자 및 최종 계획
            imgs["11_이자"] = create_styled_image(data, "중도금대출 이자", target_type, data)
            imgs["12_최종계획"] = create_styled_image(data['납부일정'], "분양가 납부 계획", target_type, data, extra_info=t_intr)

            st.session_state.generated_images = imgs
            st.session_state.blog_summary = get_blog_summary_text(data, target_type, t_intr)

        # 블로그 요약 및 이미지 표시
        if st.session_state.blog_summary:
            st.subheader("📋 블로그 복사용 텍스트")
            st.text_area("드래그해서 복사하세요", value=st.session_state.blog_summary, height=400)

        # 이미지-텍스트 매칭용 함수 (키워드 검색 방식)
        def get_snippet(img_name, summary):
            if not summary: return ""
            sections = summary.split("\n\n")
            
            if "1_주요내용" in img_name:
                for s in sections:
                    if "[주요 규제" in s: return s
            if "2_청약일정" in img_name:
                for s in sections:
                    if "[청약일정]" in s: return s
            if "5_가점추첨" in img_name:
                # 가점제 비율과 추첨제 물량을 모두 포함하여 반환
                parts = []
                for s in sections:
                    if "✔️ 가점제 비율" in s or "✔️추첨제 물량" in s:
                        parts.append(s)
                return "\n\n".join(parts)
            if "6_분양가" in img_name:
                for s in sections:
                    if "[분양가]" in s and "납부 계획" not in s: return s
            if "7_납부일정" in img_name:
                parts = []
                collect = False
                for s in sections:
                    if "[분양가 납부 계획" in s:
                        collect = True
                    if collect:
                        if "[옵션 및 발코니" in s or "[구체적인" in s:
                            break
                        parts.append(s)
                return "\n\n".join(parts)
            if "8_" in img_name: # 옵션/발코니 일정
                for s in sections:
                    if "[옵션 및 발코니 납부 계획]" in s: return s
            if "12_최종계획" in img_name:
                parts = []
                collect = False
                for s in sections:
                    if "[구체적인 납부 금액" in s:
                        collect = True
                    if collect:
                        parts.append(s)
                return "\n\n".join(parts)
            
            # 매칭되는 키워드가 없을 때만 이자 정보 등 특수 케이스 처리
            if "11_이자" in img_name:
                data = st.session_state.extracted_data
                spread = data.get('대출정보', {}).get('가산금리', 1.5)
                intr_manwon = st.session_state.get('total_interest_val', 0) // 10000
                return f"""먼저 중도금 이자입니다.

이자는 신규COFIX금리인 {cofix}%에 가산금리 {spread}%를 더해서 계산해봤는데요.

약 {intr_manwon:,}만원 수준입니다.

해당 이자는 추후 금리 변동이나 중도상환 시 변경될 수 있으므로 참고만 부탁드립니다."""
            
            if "9_" in img_name:
                return f"""👉 {target_type}타입 최고층
👉 발코니 확장
👉 현관 중문 옵션
👉 시스템에어컨 전실
👉 중도금이자 후불제"""
                
            return ""

        for n, img in st.session_state.generated_images.items():
            if img:
                # 1. 이미지 출력
                if use_base64 and (not locals().get('target_img_name') or n == target_img_name):
                    # Base64 모드 (선택된 것만 혹은 루프 구조에 따라)
                    MAX_WIDTH = 1000
                    img_to_show = img.resize((MAX_WIDTH, int(img.height * (MAX_WIDTH / img.width))), Image.Resampling.LANCZOS) if img.width > MAX_WIDTH else img
                    buffered = io.BytesIO()
                    rgb_img = img_to_show.convert("RGB") if img_to_show.mode == "RGBA" else img_to_show
                    rgb_img.save(buffered, format="JPEG", quality=80)
                    img_base64 = base64.b64encode(buffered.getvalue()).decode()
                    st.markdown(f'<img src="data:image/jpeg;base64,{img_base64}" width="100%" style="border: 2px solid #ff4b4b; margin-bottom: 5px;">', unsafe_allow_html=True)
                else:
                    st.image(img)
                
                # 2. 관련 텍스트 출력 (이미지 바로 아래 - 캡션 스타일 및 줄바꿈 유지)
                snippet = get_snippet(n, st.session_state.blog_summary)
                if snippet:
                    # 마크다운 줄바꿈 규칙(공백 2개 + \n)을 적용하여 복사 시 줄바꿈 유지
                    st.caption(snippet.replace("\n", "  \n"))
                else:
                    st.caption(n)
                st.write("---")

    if st.session_state.blog_summary:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for n, i in st.session_state.generated_images.items():
                if i: 
                    b = io.BytesIO()
                    i.save(b, format="PNG")
                    zf.writestr(f"{n}.png", b.getvalue())
            zf.writestr("summary.txt", st.session_state.blog_summary)
        st.download_button("🎁 전체 결과 다운로드 (이미지+텍스트)", buf.getvalue(), "result.zip", "application/zip")
else: 
    st.info("사이드바에서 PDF를 업로드하고 'AI 분석 시작'을 눌러주세요.")

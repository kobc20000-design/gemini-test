import requests
import json
import time

def debug_naver_crawl(blog_id):
    blog_id = blog_id.strip()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
        "Referer": f"https://blog.naver.com/PostList.naver?blogId={blog_id}",
        "Accept": "application/json, text/javascript, */*; q=0.01"
    }
    
    list_url = f"https://blog.naver.com/PostTitleListAsync.naver?blogId={blog_id}&viewdate=&currentPage=1&categoryNo=&parentCategoryNo=&countPerPage=30"
    
    print(f"Testing URL: {list_url}")
    try:
        response = requests.get(list_url, headers=headers)
        print(f"Status Code: {response.status_code}")
        print(f"Raw Response (first 100 chars): {response.text[:100]}")
        
        data = response.json()
        if 'postList' in data:
            print(f"Success! Found {len(data['postList'])} posts.")
        else:
            print("Failed: 'postList' key not found in JSON.")
            print(f"Keys in JSON: {list(data.keys())}")
            
    except Exception as e:
        print(f"Error occurred: {e}")

if __name__ == "__main__":
    debug_naver_crawl("gobc20000")

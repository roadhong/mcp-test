from fastmcp import FastMCP
import os
import requests
from rapidfuzz import fuzz
import re
from hangul_romanize.core import Transliter
from hangul_romanize.rule import academic
import gspread
from google.oauth2.service_account import Credentials
from typing import Optional, List, Dict, Any

mcp = FastMCP(on_duplicate_tools="error")
base_url = os.getenv("CONFLUENCE_URL")
user = os.getenv("CONFLUENCE_USER")
token = os.getenv("CONFLUENCE_TOKEN")
sheet_account = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
sheet_url = os.getenv("GOOGLE_SHEET_URL")
worksheet_name = os.getenv("GOOGLE_SHEET_NAME")
parent_ids_env = os.getenv("PAGES_IDS")
if parent_ids_env:
    parent_ids: List[str] = parent_ids_env.split(",")
else:
    parent_ids = []

def is_korean(text: Optional[str]) -> bool:
    if not text:
        return False
    return bool(re.search(r'[\uac00-\ud7a3]', text))

def translate_to_english(text: str) -> str:
    return Transliter(academic).translit(text)

def find_page_detail_by_query(parent_ids: List[str], query: Optional[str]) -> Optional[Dict[str, Any]]:
    def get_scores(q, t):
        scores = [
            fuzz.ratio(q, t),
            fuzz.partial_ratio(q, t),
            fuzz.token_sort_ratio(q, t),
            fuzz.token_set_ratio(q, t)
        ]
        return sum(scores) / len(scores)

    if not base_url or not user or not token:
        return {"error": "Confluence 환경변수가 올바르게 설정되지 않았습니다."}
    if not parent_ids:
        return {"error": "PAGES_IDS 환경변수가 비어 있습니다."}
    if not query:
        return {"error": "검색어(query)가 필요합니다."}

    candidates = []
    for parent_id in parent_ids:
        child_url = f"{base_url}/api/v2/pages/{parent_id}/direct-children?limit=250"
        try:
            resp = requests.get(child_url, auth=(user, token), headers={"Accept": "application/json"}, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            return {"error": f"Failed to fetch children: {str(e)}"}
        child_data = resp.json()
        for p in child_data.get("results", []):
            title = p["title"]
            if str(query).isdigit():
                match = re.match(r'^(\d+)', title)
                if match and match.group(1) == str(query):
                    candidates.append({
                        "id": p["id"],
                        "title": title,
                        "score": 100
                    })
            else:
                score = get_scores(query, title.lower())
                if score >= 30:
                    candidates.append({
                        "id": p["id"],
                        "title": title,
                        "score": score
                    })
    if not candidates:
        return None
    best = max(candidates, key=lambda x: x["score"])
    page_id = best["id"]
    detail_url = f"{base_url}/api/v2/pages/{page_id}?body-format=export_view"
    try:
        detail_resp = requests.get(detail_url, auth=(user, token), headers={"Accept": "application/json"}, timeout=10)
        detail_resp.raise_for_status()
        detail_data = detail_resp.json()
    except requests.HTTPError as e:
        if hasattr(e, 'response') and getattr(e, 'response', None) is not None and e.response.status_code == 404:
            return None
        else:
            return {"error": f"HTTP error: {str(e)}"}
    except Exception as e:
        return {"error": f"Failed to fetch detail: {str(e)}"}
    return {
        "title": best["title"],
        "body_content": detail_data.get("body", {}).get("export_view", {}).get("value"),
    }

def get_worksheet_by_url_and_name(sheet_url: str, worksheet_name: str):
    """
    구글 스프레드시트 URL과 워크시트 이름을 받아 해당 워크시트 객체를 반환한다.
    """
    if not sheet_account:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON 환경변수가 필요합니다.")
    if not sheet_url or not worksheet_name:
        raise ValueError("GOOGLE_SHEET_URL, GOOGLE_SHEET_NAME 환경변수가 필요합니다.")
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive',
    ]
    try:
        creds = Credentials.from_service_account_file(sheet_account, scopes=scope)
        client = gspread.authorize(creds)
        sheet = client.open_by_url(sheet_url)
        worksheet = sheet.worksheet(worksheet_name)
        return worksheet
    except Exception as e:
        raise RuntimeError(f"구글 시트 접근 실패: {str(e)}")

@mcp.tool
def get_page_info(query: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    페이지를 검색한다.
    Parameters:
        query (str): 페이지 이름 또는 페이지 번호.
                     Example: "Piggy Bam Ahoy", "Bingo", "123"
    Returns:
        dict: title and Detailed information of matching documents
    """
    if query and is_korean(query):
        query = translate_to_english(query).lower()
    return find_page_detail_by_query(parent_ids, query)

@mcp.tool
def get_spreadsheet_data(row, column, count = 10) -> Dict[str, Any]:
    """
    구글 스프레드시트에서 데이터를 가져온다.
    
    Returns:
        dict: data
    """
    if not sheet_url or not worksheet_name:
        return {"error": "GOOGLE_SHEET_URL, GOOGLE_SHEET_NAME 환경변수가 필요합니다."}
    try:
        worksheet = get_worksheet_by_url_and_name(sheet_url, worksheet_name)
        header_row = worksheet.row_values(row)[column:]
        data = worksheet.get_all_records(expected_headers=header_row, head=3, default_blank='')
        result = {
            "header": header_row,
            "data": data[:count],
            "totalCount": len(data),
        }
        return result
    except Exception as e:
        return {"error": f"스프레드시트 접근 실패: {str(e)}"}

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)



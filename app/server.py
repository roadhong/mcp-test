from fastmcp import FastMCP
import os
import requests
from rapidfuzz import fuzz
import re
from hangul_romanize.core import Transliter
from hangul_romanize.rule import academic
import gspread
from oauth2client.service_account import ServiceAccountCredentials

mcp = FastMCP(on_duplicate_tools="error")
base_url = os.getenv("CONFLUENCE_URL")
user = os.getenv("CONFLUENCE_USER")
token = os.getenv("CONFLUENCE_TOKEN")
sheet_account = os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON')
sheet_url = os.getenv("GOOGLE_SHEET_URL")
worksheet_name = os.getenv("GOOGLE_SHEET_NAME")
parent_ids = os.getenv("PAGES_IDS").split(",")

def is_korean(text):
    if not text:
        return False
    return bool(re.search(r'[\uac00-\ud7a3]', text))

def translate_to_english(text):
    return Transliter(academic).translit(text)

def find_page_detail_by_query(parent_ids, query):
    def get_scores(q, t):
        scores = [
            fuzz.ratio(q, t),
            fuzz.partial_ratio(q, t),
            fuzz.token_sort_ratio(q, t),
            fuzz.token_set_ratio(q, t)
        ]
        return sum(scores) / len(scores)

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
    except requests.HTTPError as e:
        if hasattr(detail_resp, 'status_code') and detail_resp.status_code == 404:
            return None
        else:
            return {"error": f"HTTP error: {str(e)}"}
    except Exception as e:
        return {"error": f"Failed to fetch detail: {str(e)}"}
    detail_data = detail_resp.json()
    return {
        "title": best["title"],
        "body_content": detail_data.get("body", {}).get("export_view", {}).get("value"),
    }

def get_worksheet_by_url_and_name(sheet_url: str, worksheet_name: str):
    """
    구글 스프레드시트 URL과 워크시트 이름을 받아 해당 워크시트 객체를 반환한다.
    """
    scope = [
        'https://spreadsheets.google.com/feeds',
        'https://www.googleapis.com/auth/drive',
    ]
    creds = ServiceAccountCredentials.from_json_keyfile_name(sheet_account, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(sheet_url)
    worksheet = sheet.worksheet(worksheet_name)
    return worksheet

@mcp.tool
def get_page_info(query: str = None) -> dict:
    """
    페이지를 검색한다.
    Parameters:
        query (str): 페이지 이름 또는 페이지 번호.
                     Example: "Piggy Bam Ahoy", "Bingo", "123"
    Returns:
        dict: title and Detailed information of matching documents
    """
    if is_korean(query):
        query = translate_to_english(query).lower()
    return find_page_detail_by_query(parent_ids, query)

@mcp.tool
def get_spreadsheet_data() -> dict:
    """
    구글 스프레드시트에서 데이터를 가져온다.
    
    Returns:
        dict: data
    """
    worksheet = get_worksheet_by_url_and_name(sheet_url, worksheet_name)
    header_row = worksheet.row_values(3)[1:]
    data = worksheet.get_all_records(expected_headers=header_row, head=3, default_blank='')
    result = {
        "header": header_row,
        "data": data,
    }
    return result

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=8000)



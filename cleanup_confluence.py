"""부모 페이지(MCP - AI Simulation, 121896967)의 모든 자식 페이지 삭제.

일회성 정리 스크립트. 테스트 실행으로 누적된 Reflection / Profile / TEST_* 페이지 일괄 삭제.
"""
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

from confluence_mcp_server.confluence_client import get_child_pages

PARENT_PAGE_ID = "121896967"
_AUTH = (os.environ["CONFLUENCE_USERNAME"], os.environ["CONFLUENCE_API_TOKEN"])
_REST_ROOT = f"{os.environ['CONFLUENCE_URL']}/rest/api"


def _delete_page(page_id: str) -> None:
    """DELETE는 204 No Content — json() 대신 status_code만 확인."""
    url = f"{_REST_ROOT}/content/{page_id}"
    response = httpx.delete(url, auth=_AUTH, timeout=30.0)
    response.raise_for_status()


def main():
    children = get_child_pages(parent_id=PARENT_PAGE_ID, limit=50, expand_body=False)
    print(f"[*] 자식 페이지 {len(children)}개 발견")

    deleted = 0
    failed = 0
    for c in children:
        pid = c["id"]
        title = c["title"]
        try:
            _delete_page(pid)
            print(f"  [x] 삭제: {title}")
            deleted += 1
        except Exception as e:
            print(f"  [!] 실패 ({title}): {type(e).__name__}: {str(e)[:80]}")
            failed += 1

    print(f"\n[+] 삭제 완료: {deleted}건, 실패: {failed}건")


if __name__ == "__main__":
    main()

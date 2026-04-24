"""Atlassian REST API client — 서버 내부에서만 사용.

도메인 도구(server.py)가 호출하는 얇은 HTTP 래퍼.
인증·URL 조립·에러 처리만 담당하고, 도메인 로직은 일절 없다.
"""
import os
from typing import Any

import httpx


CONFLUENCE_BASE_URL = os.environ["CONFLUENCE_URL"]   # 예: https://atdev-ai.atlassian.net/wiki
USERNAME = os.environ["CONFLUENCE_USERNAME"]
API_TOKEN = os.environ["CONFLUENCE_API_TOKEN"]

_AUTH = (USERNAME, API_TOKEN)
_REST_ROOT = f"{CONFLUENCE_BASE_URL}/rest/api"


def _request(method: str, path: str,
             json_body: dict | None = None,
             params: dict | None = None) -> dict[str, Any]:
    """Atlassian REST API 단일 호출. 인증·timeout·에러 raise 표준화.
    204 No Content(주로 DELETE)일 경우 빈 dict 반환."""
    url = f"{_REST_ROOT}/{path.lstrip('/')}"
    response = httpx.request(
        method, url,
        auth=_AUTH,
        json=json_body,
        params=params,
        timeout=30.0,
    )
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()


def create_page(space_key: str, title: str, html_body: str,
                parent_id: str | None = None) -> dict:
    """페이지 생성 — Confluence storage(XHTML) 본문을 받음.
    응답에서 id·title만 골라 반환 (호출 측이 풀 응답을 알 필요 없음)."""
    body: dict = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {"storage": {"value": html_body, "representation": "storage"}},
    }
    if parent_id:
        body["ancestors"] = [{"id": parent_id}]
    raw = _request("POST", "content", json_body=body)
    return {"id": raw["id"], "title": raw["title"]}


def get_child_pages(parent_id: str, limit: int = 50, expand_body: bool = True) -> list[dict]:
    """부모 페이지의 자식 페이지 목록. body.storage 포함 가능.
    반환: [{id, title, body_html}, ...] (서버가 우리 도메인 모양으로 추림)."""
    params = {"limit": limit}
    if expand_body:
        params["expand"] = "body.storage"
    raw = _request("GET", f"content/{parent_id}/child/page", params=params)

    out = []
    for child in raw.get("results", []):
        body_html = ""
        if expand_body:
            body_html = child.get("body", {}).get("storage", {}).get("value", "")
        out.append({
            "id": child.get("id", ""),
            "title": child.get("title", ""),
            "body_html": body_html,
        })
    return out


def find_page_by_title(space_key: str, title: str) -> dict | None:
    """제목 완전 일치로 페이지 1건 조회. 없으면 None.
    overwrite 모드에서 "이미 같은 이름 페이지가 있나"를 판단할 때 쓴다."""
    raw = _request("GET", "content", params={
        "spaceKey": space_key,
        "title": title,
        "expand": "version",
    })
    results = raw.get("results", [])
    if not results:
        return None
    hit = results[0]
    return {
        "id": hit.get("id", ""),
        "title": hit.get("title", ""),
        "version": hit.get("version", {}).get("number", 1),
    }


def update_page(page_id: str, title: str, html_body: str, current_version: int) -> dict:
    """기존 페이지를 새 본문으로 덮어쓴다. Confluence는 version을 +1 해서 보내야 함.
    응답에서 id·title만 골라 반환."""
    body = {
        "type": "page",
        "title": title,
        "version": {"number": current_version + 1},
        "body": {"storage": {"value": html_body, "representation": "storage"}},
    }
    raw = _request("PUT", f"content/{page_id}", json_body=body)
    return {"id": raw["id"], "title": raw["title"]}

"""직접 만든 MCP 서버 — 회사원 시뮬레이션 도메인에 특화된 2개 도구만 노출.

[설계 의도]
- 외부 mcp-atlassian(24개 일반 CRUD)과의 비교 지점은 "도메인을 서버가 알고 있는가".
- 이 서버는 'reflection 저장/조회'라는 도메인 동사를 그대로 노출 →
  클라이언트는 페이지 제목 규약, body HTML 형식, 응답 파싱을 알 필요 없음.

[노출 도구 2개]
- save_reflection: agent_name + day + text + (옵션) quota/run_id → 페이지 ID 반환
- fetch_past_reflections: agent_name + limit → [{day, text, quota}] 리스트 반환

[고정값] 본 프로젝트 한정 — 부모 페이지/스페이스는 서버 상수로 박제 (호출 측 부담 없음)
"""
import json
import re
from html import escape, unescape

from fastmcp import FastMCP

from confluence_mcp_server.confluence_client import (
    create_page, get_child_pages, find_page_by_title, update_page,
)


# 본 프로젝트 특화 상수 — 다른 프로젝트면 바꿀 곳
PARENT_PAGE_ID = "121896967"   # mcptest 스페이스의 'MCP - AI Simulation' 페이지
SPACE_KEY = "mcptest"
TITLE_PREFIX_TMPL = "Reflection_{agent_name}_Day{day:04d}"

mcp = FastMCP("Confluence-Custom-MCP")


def _build_reflection_title(agent_name: str, day: int, run_id: str | None, mode: str) -> str:
    """Reflection 페이지 제목 생성.
    - append 모드: run_id suffix 붙여 실행별로 별도 페이지 누적
    - overwrite 모드: run_id 제외 → 같은 (agent, day) 조합은 항상 같은 제목 → upsert 가능"""
    base = TITLE_PREFIX_TMPL.format(agent_name=agent_name, day=day)
    if mode == "append" and run_id:
        return f"{base}_{run_id}"
    return base


def _build_profile_title(agent_name: str, run_id: str | None, mode: str) -> str:
    base = f"Profile_{agent_name}"
    if mode == "append" and run_id:
        return f"{base}_{run_id}"
    return base


def _upsert(space_key: str, title: str, html_body: str, parent_id: str, mode: str) -> dict:
    """mode에 따라 create 또는 find→update 분기.
    - append: 무조건 create_page (Confluence가 같은 제목 중복 시 409 에러 내줌 → run_id suffix로 방지해야 함)
    - overwrite: find_page_by_title로 같은 제목 있는지 확인 → 있으면 update, 없으면 create"""
    if mode == "overwrite":
        existing = find_page_by_title(space_key, title)
        if existing:
            return update_page(
                page_id=existing["id"],
                title=title,
                html_body=html_body,
                current_version=existing["version"],
            )
    return create_page(
        space_key=space_key, title=title,
        html_body=html_body, parent_id=parent_id,
    )


def _build_html_body(agent_name: str, day: int, text: str, quota: dict | None) -> str:
    """Reflection 본문을 Confluence storage(XHTML) 형식으로 조립."""
    quota_str = json.dumps(quota, ensure_ascii=False) if quota else "(N/A)"
    return (
        f"<h2>Agent: {escape(agent_name)}</h2>"
        f"<p><strong>Day:</strong> {day}</p>"
        f"<p><strong>Quota:</strong> <code>{escape(quota_str)}</code></p>"
        f"<hr/>"
        f"<pre>{escape(text)}</pre>"
    )


def _extract_quota_from_html(body_html: str) -> dict | None:
    """저장 시 본문에 박아둔 Quota JSON을 다시 꺼낸다.
    저장 단계에서 escape()로 HTML 엔티티화됐으므로 추출 후 unescape 필수."""
    m = re.search(r"<code>(.*?)</code>", body_html, re.DOTALL)
    if not m:
        return None
    raw = unescape(m.group(1)).strip()
    if not raw.startswith("{"):
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None


def _extract_text_from_html(body_html: str) -> str:
    """저장 시 <pre>로 감싼 reflection 본문을 다시 꺼낸다 (HTML 엔티티 복원 포함)."""
    m = re.search(r"<pre>(.*?)</pre>", body_html, re.DOTALL)
    return unescape(m.group(1)) if m else ""


# ── 노출 도구 ────────────────────────────────────────

@mcp.tool()
def save_reflection(
    agent_name: str,
    day: int,
    text: str,
    quota: dict | None = None,
    run_id: str | None = None,
    mode: str = "append",
) -> dict:
    """Reflection 결과를 Confluence 페이지로 저장.

    Args:
        agent_name: 에이전트 식별자 (예: 'DeepAgent_정치형')
        day: 시뮬레이션 일차
        text: Reflection 본문 텍스트 (LLM이 생성한 처방·평가 등)
        quota: 행동 배분 dict (선택). 본문에 함께 기록되어 추후 조회 가능
        run_id: 실행 식별자 (append 모드에서만 유효, 제목 충돌 방지용)
        mode: "append"(기본, 실행별로 새 페이지 누적) 또는 "overwrite"(같은 agent·day는 덮어씀)

    Returns:
        {"id": 페이지 ID, "title": 최종 페이지 제목}
    """
    title = _build_reflection_title(agent_name, day, run_id, mode)
    html = _build_html_body(agent_name, day, text, quota)
    return _upsert(SPACE_KEY, title, html, PARENT_PAGE_ID, mode)


@mcp.tool()
def save_personality_profile(personality_name: str, agent_name: str,
                             content: str, run_id: str | None = None,
                             mode: str = "append") -> dict:
    """성향별 프로필 페이지를 Confluence에 저장 (LLM이 자율적으로 호출하는 도메인 도구).

    공식 브랜치는 LLM에게 일반 create_page를 노출하므로 LLM이 space_key/parent_id/
    title prefix 같은 부수 인자를 직접 채워야 한다. 이 도메인 도구는 그 책임을 서버가
    가져가고, LLM은 도메인 인자(성향·에이전트·본문)만 채우면 되도록 단순화.

    Args:
        personality_name: 성향 이름 (예: '정치형')
        agent_name: 에이전트 식별자 (예: 'DeepAgent_정치형')
        content: 마크다운/HTML 본문 (LLM이 자유 작성)
        run_id: 실행 식별자 (append 모드에서만 유효, 제목 충돌 방지용)
        mode: "append"(기본) 또는 "overwrite"(같은 agent는 덮어씀)

    Returns:
        {"id": 페이지 ID, "title": 최종 페이지 제목}
    """
    title = _build_profile_title(agent_name, run_id, mode)
    html = (
        f"<h2>성향: {escape(personality_name)}</h2>"
        f"<p><strong>Agent:</strong> {escape(agent_name)}</p>"
        f"<hr/>"
        f"<pre>{escape(content)}</pre>"
    )
    return _upsert(SPACE_KEY, title, html, PARENT_PAGE_ID, mode)


@mcp.tool()
def fetch_past_reflections(agent_name: str, limit: int = 3) -> list[dict]:
    """이 에이전트의 최근 Reflection을 day 내림차순으로 반환.

    Args:
        agent_name: 조회 대상 에이전트
        limit: 최대 반환 개수 (기본 3)

    Returns:
        [{"day": int, "text": str, "quota": dict | None, "title": str}, ...]
        — 클라이언트는 그대로 사용 (HTML/JSON 파싱 불필요)
    """
    children = get_child_pages(parent_id=PARENT_PAGE_ID, limit=50, expand_body=True)
    title_prefix = TITLE_PREFIX_TMPL.format(agent_name=agent_name, day=0)[:-4]
    # 위 줄: "Reflection_{agent_name}_Day" prefix만 추출 (day 자리는 잘라냄)

    matched = []
    for c in children:
        title = c["title"]
        if not title.startswith(title_prefix):
            continue
        try:
            day_num = int(title[len(title_prefix):len(title_prefix) + 4])
        except ValueError:
            continue
        matched.append({
            "day": day_num,
            "title": title,
            "text": _extract_text_from_html(c["body_html"]),
            "quota": _extract_quota_from_html(c["body_html"]),
        })

    matched.sort(key=lambda x: -x["day"])
    return matched[:limit]


if __name__ == "__main__":
    mcp.run()  # stdio transport (default)

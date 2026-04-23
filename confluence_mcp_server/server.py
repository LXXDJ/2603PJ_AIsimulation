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

from confluence_mcp_server.confluence_client import create_page, get_child_pages


# 본 프로젝트 특화 상수 — 다른 프로젝트면 바꿀 곳
PARENT_PAGE_ID = "121896967"   # mcptest 스페이스의 'MCP - AI Simulation' 페이지
SPACE_KEY = "mcptest"
TITLE_PREFIX_TMPL = "Reflection_{agent_name}_Day{day:04d}"

mcp = FastMCP("Confluence-Custom-MCP")


def _build_title(agent_name: str, day: int, run_id: str | None) -> str:
    title = TITLE_PREFIX_TMPL.format(agent_name=agent_name, day=day)
    return f"{title}_{run_id}" if run_id else title


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
) -> dict:
    """Reflection 결과를 Confluence 페이지로 저장.

    Args:
        agent_name: 에이전트 식별자 (예: 'DeepAgent_정치형')
        day: 시뮬레이션 일차
        text: Reflection 본문 텍스트 (LLM이 생성한 처방·평가 등)
        quota: 행동 배분 dict (선택). 본문에 함께 기록되어 추후 조회 가능
        run_id: 실행 식별자 (선택). 같은 agent로 여러 번 돌릴 때 제목 충돌 방지

    Returns:
        {"id": 페이지 ID, "title": 최종 페이지 제목}
    """
    title = _build_title(agent_name, day, run_id)
    html = _build_html_body(agent_name, day, text, quota)
    return create_page(
        space_key=SPACE_KEY,
        title=title,
        html_body=html,
        parent_id=PARENT_PAGE_ID,
    )


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

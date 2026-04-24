"""Confluence 연동 — Reflection 저장/조회 (공식/커뮤니티 mcp-atlassian 사용).

설계 메모 (옵션 B / code-driven):
- LLM이 도구를 선택하지 않고, 코드가 직접 Reflection 저장/조회 시점을 정한다.
- 시뮬레이션은 ThreadPoolExecutor로 병렬 실행되므로 워커 스레드마다 별도의
  mcp-atlassian subprocess + asyncio loop를 둔다 (threading.local 캐시).
- 첫 호출에서 init(약 2~3초). 이후 호출은 동일 subprocess 재사용 → 반복 호출 비용 최소화.

도구 선택:
- 저장: confluence_create_page (parent_id로 트리 묶기)
- 덮어쓰기 (overwrite mode): confluence_get_page(title+space_key) → 있으면 confluence_update_page
- 조회: confluence_get_page_children (search는 인덱싱 지연/CQL 토큰화로 신뢰성 떨어짐.
  부모 페이지의 자식 리스트는 즉시 일관성 보장)

직접 만든 MCP 서버 버전과의 비교 포인트 (코드리뷰 시):
- 일반 CRUD를 도메인(reflection 저장)에 끼워 맞춤 — 클라이언트가 prefix 필터링/정렬 책임짐
- 응답이 [{'type': 'text', 'text': '...'}] 형태로 와서 파싱 한 단계 더 필요
- 인증/스키마 모두 외부 패키지에 의존 (장점: 설치만 하면 됨, 단점: 도메인 모름)
- mode 정책 변경 시 클라이언트가 도구 2개를 조합 호출 (커스텀 서버는 도메인 도구 1번이면 끝)
"""
import asyncio
import json
import os
import threading

from langchain_mcp_adapters.client import MultiServerMCPClient


# 모든 Reflection 페이지의 부모 — mcptest 스페이스의 README.md 페이지
PARENT_PAGE_ID = "120520708"
SPACE_KEY = "mcptest"

_local = threading.local()


def _build_subprocess_env() -> dict:
    """mcp-atlassian subprocess가 필요로 하는 최소 환경변수를 추려서 전달한다.
    Atlassian 인증 정보 + Windows에서 실행 파일을 찾기 위한 시스템 환경변수만 포함."""
    base = {
        k: v for k, v in os.environ.items()
        if k.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}
    }
    base.update({
        "CONFLUENCE_URL": os.environ["CONFLUENCE_URL"],
        "CONFLUENCE_USERNAME": os.environ["CONFLUENCE_USERNAME"],
        "CONFLUENCE_API_TOKEN": os.environ["CONFLUENCE_API_TOKEN"],
    })
    return base


def _ensure_init() -> dict[str, object]:
    """현재 스레드의 MCP 클라이언트가 준비되어 있는지 확인하고 도구 dict를 반환."""
    if hasattr(_local, "tools"):
        return _local.tools

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = MultiServerMCPClient({
        "atlassian": {
            "command": "mcp-atlassian",
            "args": [],
            "transport": "stdio",
            "env": _build_subprocess_env(),
        }
    })
    tool_list = loop.run_until_complete(client.get_tools())

    _local.loop = loop
    _local.client = client
    _local.tools = {t.name: t for t in tool_list}
    return _local.tools


def _build_reflection_title(agent_name: str, day: int, run_id: str | None, mode: str) -> str:
    """제목 결정.
    - append + run_id → 매 실행마다 새 페이지 (suffix로 충돌 회피)
    - overwrite, 또는 run_id 없음 → 같은 (agent, day) 조합은 같은 제목 (upsert 가능)"""
    base = f"Reflection_{agent_name}_Day{day:04d}"
    if mode == "append" and run_id:
        return f"{base}_{run_id}"
    return base


def find_page_id_by_title(title: str, tools: dict | None = None) -> str | None:
    """제목+space로 페이지 1건 조회. 없거나 예외면 None.
    overwrite 모드와 LLM-driven Profile 양쪽에서 공용."""
    if tools is None:
        try:
            tools = _ensure_init()
        except Exception:
            return None
    get_page = tools.get("confluence_get_page")
    if not get_page:
        return None
    try:
        raw = _local.loop.run_until_complete(get_page.ainvoke({
            "title": title,
            "space_key": SPACE_KEY,
            "include_metadata": False,
            "convert_to_markdown": False,
        }))
    except Exception:
        # mcp-atlassian은 미존재를 보통 예외로 던짐
        return None
    text = _unwrap_text(raw)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(parsed, dict):
        # 응답 모양: {metadata: {id, ...}, ...} 또는 {id, ...} (mcp-atlassian 버전에 따라)
        page_id = parsed.get("id") or (parsed.get("metadata") or {}).get("id")
        return page_id or None
    return None


def save_reflection(agent_name: str, day: int, text: str, quota: dict | None,
                    run_id: str | None = None, mode: str = "append") -> bool:
    """Reflection 결과를 PARENT_PAGE_ID의 자식 페이지로 저장. 성공 여부 반환.

    페이지 제목 형식: Reflection_{agent_name}_Day{day:04d}[_{run_id}]
    - mode="append": run_id suffix 붙여 매 실행마다 새 페이지 누적
    - mode="overwrite": suffix 없는 고정 제목 → 기존 있으면 update_page, 없으면 create
      (mcp-atlassian의 update_page는 version 자동 +1 처리 → 호출 측 부담 없음)

    조회는 'Reflection_{agent_name}_Day' prefix로 식별 → 실행 간 비교에 그대로 활용 가능.
    """
    try:
        tools = _ensure_init()
    except Exception as e:
        print(f"[Confluence] init 실패: {type(e).__name__}: {e}")
        return False

    title = _build_reflection_title(agent_name, day, run_id, mode)
    quota_line = json.dumps(quota, ensure_ascii=False) if quota else "(파싱 실패)"
    body = (
        f"**Agent**: {agent_name}\n\n"
        f"**Day**: {day}\n\n"
        f"**Quota**: `{quota_line}`\n\n"
        f"---\n\n"
        f"{text}\n"
    )

    # overwrite 모드: 같은 제목 페이지 검색 → 있으면 update, 없으면 create로 fallthrough
    if mode == "overwrite":
        existing_id = find_page_id_by_title(title, tools)
        if existing_id:
            update = tools.get("confluence_update_page")
            if not update:
                print("[Confluence] confluence_update_page 도구가 없음")
                return False
            try:
                _local.loop.run_until_complete(update.ainvoke({
                    "page_id": existing_id,
                    "title": title,
                    "content": body,
                    "content_format": "markdown",
                }))
                return True
            except Exception as e:
                print(f"[Confluence] update 실패 ({agent_name} Day {day}): {type(e).__name__}: {str(e)[:120]}")
                return False

    # append, 또는 overwrite인데 못 찾은 경우 → create
    create = tools.get("confluence_create_page")
    if not create:
        print("[Confluence] confluence_create_page 도구가 없음")
        return False
    try:
        _local.loop.run_until_complete(create.ainvoke({
            "space_key": SPACE_KEY,
            "title": title,
            "content": body,
            "parent_id": PARENT_PAGE_ID,
            "content_format": "markdown",
        }))
        return True
    except Exception as e:
        # 동일 제목 중복 등으로 실패 가능 — 시뮬레이션은 계속 진행
        print(f"[Confluence] save 실패 ({agent_name} Day {day}): {type(e).__name__}: {str(e)[:120]}")
        return False


def _unwrap_text(result) -> str:
    """MCP 도구 응답을 텍스트로 변환.
    응답은 [{'type': 'text', 'text': '...'}, ...] 또는 string 형태로 옴."""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        parts = []
        for item in result:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(item.get("text", ""))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(result)


def fetch_past_reflections_text(agent_name: str, limit: int = 3) -> str:
    """이 에이전트의 최근 Reflection N개를 텍스트로 반환. 없으면 빈 문자열.

    PARENT_PAGE_ID의 모든 자식을 가져와 제목 prefix로 클라이언트 필터링한다.
    (search는 CQL 토큰화/인덱싱 지연으로 직후 조회가 비어 나오는 문제가 있음)
    """
    try:
        tools = _ensure_init()
    except Exception as e:
        print(f"[Confluence] init 실패: {type(e).__name__}: {e}")
        return ""

    get_children = tools.get("confluence_get_page_children")
    if not get_children:
        return ""

    try:
        raw = _local.loop.run_until_complete(get_children.ainvoke({
            "parent_id": PARENT_PAGE_ID,
            "limit": 50,
            "include_content": True,
            "convert_to_markdown": True,
        }))
    except Exception as e:
        print(f"[Confluence] fetch 실패 ({agent_name}): {type(e).__name__}: {str(e)[:120]}")
        return ""

    text = _unwrap_text(raw)
    title_prefix = f"Reflection_{agent_name}_Day"

    # 응답: {parent_id, count, results: [{id, title, content: {value, format}, ...}]}
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return ""
    children = parsed.get("results", []) if isinstance(parsed, dict) else []
    if not isinstance(children, list):
        return ""

    # 제목 prefix 매칭 + day 번호 내림차순 정렬
    # 제목: Reflection_{agent}_Day{NNNN}[_{run_id}] → prefix 뒤 4자리만 day 번호로 파싱
    matched = []
    for c in children:
        if not isinstance(c, dict):
            continue
        title = c.get("title", "")
        if not title.startswith(title_prefix):
            continue
        try:
            day_num = int(title[len(title_prefix):len(title_prefix) + 4])
        except ValueError:
            continue
        content = c.get("content") or {}
        body = content.get("value", "") if isinstance(content, dict) else ""
        matched.append((day_num, title, body))
    matched.sort(key=lambda x: -x[0])

    out_parts = []
    for day_num, title, body in matched[:limit]:
        out_parts.append(f"[Day {day_num}] {title}\n{body[:600]}")
    joined = "\n\n---\n\n".join(out_parts)
    return joined[:3000]

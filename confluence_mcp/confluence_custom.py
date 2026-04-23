"""클라이언트 wrapper — 직접 만든 MCP 서버를 stdio transport로 띄워 호출.

[설계 의도]
- 공식 브랜치의 confluence_official.py와 같은 인터페이스(save_reflection, fetch_past_reflections_text)
  → main.py 입장에서는 import 한 줄만 바꾸면 교체 가능. 두 브랜치가 같은 use case로 비교 가능.
- 다른 점은 서버 spawn 명령(`python -m confluence_mcp_server.server`)뿐.
- 호출 인자가 우리 도메인 그대로(agent_name, day, text, ...)라 인자 조립 코드가 거의 없음.
- 응답도 도메인 모양({day, text, quota})으로 와서 클라이언트 측 필터링/정렬/파싱 불필요.
"""
import asyncio
import json
import os
import sys
import threading

from langchain_mcp_adapters.client import MultiServerMCPClient


_local = threading.local()


def _build_subprocess_env() -> dict:
    """우리 서버(subprocess)가 필요로 하는 환경변수만 추려서 전달.
    PATH·시스템 + Atlassian 인증."""
    base = {k: v for k, v in os.environ.items()
            if k.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP",
                             "USERPROFILE", "APPDATA", "LOCALAPPDATA"}}
    base.update({
        "CONFLUENCE_URL": os.environ["CONFLUENCE_URL"],
        "CONFLUENCE_USERNAME": os.environ["CONFLUENCE_USERNAME"],
        "CONFLUENCE_API_TOKEN": os.environ["CONFLUENCE_API_TOKEN"],
    })
    return base


def _ensure_init() -> dict:
    """현재 스레드의 MCP 클라이언트가 우리 서버에 연결되어 있는지 확인하고 도구 dict 반환."""
    if hasattr(_local, "tools"):
        return _local.tools

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = MultiServerMCPClient({
        "confluence_custom": {
            "command": sys.executable,                       # 같은 Python 인터프리터 사용
            "args": ["-m", "confluence_mcp_server.server"],   # 우리 서버 모듈 실행
            "transport": "stdio",
            "env": _build_subprocess_env(),
        }
    })
    tool_list = loop.run_until_complete(client.get_tools())

    _local.loop = loop
    _local.client = client
    _local.tools = {t.name: t for t in tool_list}
    return _local.tools


def _unwrap_response(raw):
    """MCP 응답을 Python 객체로 정규화.
    FastMCP는 복합 반환값을 [{type:'text', text:'JSON 문자열'}] 형태로 직렬화."""
    if isinstance(raw, (list, dict)):
        # langchain-mcp-adapters가 이미 파싱해 준 경우
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = item.get("text", "")
                    try:
                        return json.loads(text)
                    except (json.JSONDecodeError, ValueError):
                        return text
            return raw
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return raw
    return raw


def save_reflection(agent_name: str, day: int, text: str,
                    quota: dict | None, run_id: str | None = None) -> bool:
    """Reflection을 우리 MCP 서버를 통해 Confluence에 저장. 성공 여부 반환."""
    try:
        tools = _ensure_init()
    except Exception as e:
        print(f"[Confluence-Custom] init 실패: {type(e).__name__}: {e}")
        return False

    save_tool = tools.get("save_reflection")
    if not save_tool:
        print("[Confluence-Custom] save_reflection 도구가 없음")
        return False

    try:
        _local.loop.run_until_complete(save_tool.ainvoke({
            "agent_name": agent_name,
            "day": day,
            "text": text,
            "quota": quota,
            "run_id": run_id,
        }))
        return True
    except Exception as e:
        print(f"[Confluence-Custom] save 실패 ({agent_name} Day {day}): {type(e).__name__}: {str(e)[:120]}")
        return False


def fetch_past_reflections_text(agent_name: str, limit: int = 3) -> str:
    """이 에이전트의 최근 Reflection N개를 프롬프트 주입용 텍스트로 반환.
    공식 브랜치와 같은 시그니처 — main.py가 동일 호출 패턴 유지."""
    try:
        tools = _ensure_init()
    except Exception as e:
        print(f"[Confluence-Custom] init 실패: {type(e).__name__}: {e}")
        return ""

    fetch_tool = tools.get("fetch_past_reflections")
    if not fetch_tool:
        return ""

    try:
        raw = _local.loop.run_until_complete(fetch_tool.ainvoke({
            "agent_name": agent_name,
            "limit": limit,
        }))
    except Exception as e:
        print(f"[Confluence-Custom] fetch 실패 ({agent_name}): {type(e).__name__}: {str(e)[:120]}")
        return ""

    items = _unwrap_response(raw)
    if not isinstance(items, list) or not items:
        return ""

    # 서버가 이미 day 내림차순 + prefix 필터링 + 본문 추출 다 해줬음 → 단순 포맷팅만
    out_parts = []
    for item in items:
        if not isinstance(item, dict):
            continue
        day = item.get("day", "?")
        title = item.get("title", "")
        text = item.get("text", "")
        out_parts.append(f"[Day {day}] {title}\n{text[:600]}")
    return "\n\n---\n\n".join(out_parts)[:3000]

"""[용도] mcp-atlassian이 제공하는 Confluence 도구들의 인자/필수여부를 일괄 출력.
[언제] mcp-atlassian이 업데이트되어 도구 시그니처가 바뀐 의심이 들 때, 또는
       confluence_official.py에 새 도구 호출을 추가하기 전에 인자명을 확인할 때.
       (단순 연결만 보고 싶으면 test_mcp.py가 더 가벼움)

실행: python test_mcp_schema.py
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient


# 우리가 통합에 사용할 후보 도구들
TARGET_TOOLS = [
    "confluence_create_page",
    "confluence_update_page",
    "confluence_search",
    "confluence_get_page",
    "confluence_get_page_children",
    "confluence_get_page_descendants",
]


async def main():
    load_dotenv()

    subprocess_env = {
        k: v for k, v in os.environ.items()
        if k.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA"}
    }
    subprocess_env.update({
        "CONFLUENCE_URL": os.environ["CONFLUENCE_URL"],
        "CONFLUENCE_USERNAME": os.environ["CONFLUENCE_USERNAME"],
        "CONFLUENCE_API_TOKEN": os.environ["CONFLUENCE_API_TOKEN"],
    })

    client = MultiServerMCPClient({
        "atlassian": {
            "command": "mcp-atlassian",
            "args": [],
            "transport": "stdio",
            "env": subprocess_env,
        }
    })

    tools = await client.get_tools()
    by_name = {t.name: t for t in tools}

    print(f"[+] 총 {len(tools)}개 도구 로드됨\n")
    print(f"[ 전체 Confluence 도구 목록 ]")
    for name in sorted(n for n in by_name if "confluence" in n.lower()):
        print(f"  - {name}")
    print()

    for target in TARGET_TOOLS:
        print("=" * 70)
        if target not in by_name:
            print(f"[!] {target} : 도구 없음")
            continue
        t = by_name[target]
        print(f"[+] {target}")
        print(f"  description (첫 줄): {(t.description or '').split(chr(10))[0]}")
        print(f"  args:")
        # langchain BaseTool의 args는 dict[str, dict] 형태
        for arg_name, arg_info in (t.args or {}).items():
            arg_type = arg_info.get("type", "?")
            arg_title = arg_info.get("title", "")
            arg_desc = arg_info.get("description", "")[:80]
            print(f"    - {arg_name} ({arg_type}) {arg_title}: {arg_desc}")
        # required 필드도 확인
        schema = getattr(t, "args_schema", None)
        if schema and hasattr(schema, "model_json_schema"):
            full = schema.model_json_schema()
            req = full.get("required", [])
            print(f"  required: {req}")
        print()


if __name__ == "__main__":
    asyncio.run(main())

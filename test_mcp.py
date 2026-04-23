"""[용도] mcp-atlassian 서버 자체가 떠서 페이지 1개를 읽을 수 있는지만 확인.
[언제] 인증/연결 의심될 때 가장 먼저 돌리는 최소 단위 테스트.
       (도구 스키마 전수조사는 test_mcp_schema.py, wrapper 검증은 test_confluence_official.py)

사전 조건: .env에 다음 3개 변수가 있어야 함
  CONFLUENCE_URL=https://atdev-ai.atlassian.net/wiki
  CONFLUENCE_USERNAME=<Atlassian 로그인 이메일>
  CONFLUENCE_API_TOKEN=<https://id.atlassian.com/manage-profile/security/api-tokens 에서 발급>

실행: python test_mcp.py
"""
import asyncio
import os
import sys
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient


TEST_PAGE_ID = "120520708"  # mcptest 스페이스의 README.md 페이지


async def main():
    load_dotenv()

    required = ["CONFLUENCE_URL", "CONFLUENCE_USERNAME", "CONFLUENCE_API_TOKEN"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"[!] .env 누락 변수: {missing}", file=sys.stderr)
        sys.exit(1)

    # mcp-atlassian 서버를 subprocess로 띄우는 설정.
    # subprocess에 PATH 등 시스템 환경변수를 넘겨야 mcp-atlassian 실행 파일을 찾을 수 있다.
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

    print("[*] MCP 서버 연결 중...")
    tools = await client.get_tools()
    print(f"[+] {len(tools)}개 도구 로드됨\n")

    conf_tools = [t for t in tools if "confluence" in t.name.lower()]
    print(f"=== Confluence 도구 ({len(conf_tools)}개) ===")
    for t in conf_tools:
        desc = (t.description or "").split("\n")[0][:80]
        print(f"  {t.name}: {desc}")

    get_page = next((t for t in conf_tools if "get_page" in t.name.lower()), None)
    if not get_page:
        print("\n[!] confluence_get_page 도구를 찾지 못함", file=sys.stderr)
        sys.exit(1)

    print(f"\n=== {get_page.name} 스키마 ===")
    print(f"args_schema: {get_page.args}")

    print(f"\n=== 페이지 {TEST_PAGE_ID} 읽기 시도 ===")
    # 인자명이 page_id / pageId / id 중 어느 것인지 모르므로 순차 시도
    last_err = None
    for arg_name in ["page_id", "pageId", "id"]:
        try:
            result = await get_page.ainvoke({arg_name: TEST_PAGE_ID})
            print(f"[+] '{arg_name}' 인자로 성공\n")
            output = result if isinstance(result, str) else repr(result)
            print(output[:1500])
            if len(output) > 1500:
                print(f"\n... (총 {len(output)}자, 1500자만 표시)")
            return
        except Exception as e:
            last_err = e
            print(f"  '{arg_name}' 실패: {type(e).__name__}: {str(e)[:100]}")

    print(f"\n[!] 모든 인자명 시도 실패. 마지막 에러: {last_err}", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

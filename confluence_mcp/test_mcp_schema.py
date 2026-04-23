"""[용도] mcp-atlassian이 노출하는 Confluence 도구의 목록 + 상세 스키마 출력.
       두 섹션으로 나눠서 보여준다:
         SECTION 1: 카테고리별 한 줄 요약 — 어떤 도구가 있는지 빠른 조사
         SECTION 2: 상세 스키마 (TARGET_TOOLS) — 새 wrapper 추가 전 인자명·타입·필수여부 확인
[언제] mcp-atlassian 업데이트로 시그니처가 바뀐 의심이 들 때,
       또는 confluence_official.py에 새 도구 호출을 추가하기 전에.
       (단순 연결만 보고 싶으면 test_mcp.py가 더 가벼움)

실행: python -m confluence_mcp.test_mcp_schema   (프로젝트 루트에서)
"""
import asyncio
import os
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient


# 상세 스키마를 출력할 도구 (새 wrapper 추가 시 여기에 추가)
TARGET_TOOLS = [
    "confluence_create_page",
    "confluence_update_page",
    "confluence_search",
    "confluence_get_page",
    "confluence_get_page_children",
]

# 24개 도구 카테고리 그룹핑
CATEGORIES = {
    "페이지 조회": [
        "confluence_get_page", "confluence_get_page_children",
        "confluence_get_space_page_tree", "confluence_search",
    ],
    "페이지 생성·수정·삭제·이동": [
        "confluence_create_page", "confluence_update_page",
        "confluence_delete_page", "confluence_move_page",
    ],
    "첨부 파일": [
        "confluence_upload_attachment", "confluence_upload_attachments",
        "confluence_download_attachment", "confluence_download_content_attachments",
        "confluence_get_attachments", "confluence_delete_attachment",
    ],
    "댓글": [
        "confluence_add_comment", "confluence_get_comments", "confluence_reply_to_comment",
    ],
    "메타데이터 (라벨·이력·통계)": [
        "confluence_add_label", "confluence_get_labels",
        "confluence_get_page_history", "confluence_get_page_diff",
        "confluence_get_page_views", "confluence_get_page_images",
    ],
    "사용자": [
        "confluence_search_user",
    ],
}


async def main():
    load_dotenv()

    subprocess_env = {
        k: v for k, v in os.environ.items()
        if k.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP",
                         "USERPROFILE", "APPDATA", "LOCALAPPDATA"}
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
    conf_count = sum(1 for n in by_name if "confluence" in n.lower())
    print(f"[+] 총 {len(tools)}개 도구 로드됨 (Confluence: {conf_count}개)\n")

    # ── SECTION 1: 카테고리별 한 줄 요약 ─────────────────
    print("=" * 70)
    print("SECTION 1: 카테고리별 한 줄 요약")
    print("=" * 70)
    shown = set()
    for cat_name, names in CATEGORIES.items():
        print(f"\n[{cat_name}]")
        for name in names:
            if name not in by_name:
                print(f"  - {name}  (도구 없음)")
                continue
            desc = (by_name[name].description or "").split("\n")[0][:90]
            print(f"  - {name}")
            print(f"      {desc}")
            shown.add(name)

    # 분류에 안 들어간 confluence_* 도구 (혹시 추가/변경됐을 때)
    leftover = sorted(n for n in by_name if "confluence" in n.lower() and n not in shown)
    if leftover:
        print(f"\n[기타 (분류 미지정 — CATEGORIES에 추가하세요)]")
        for name in leftover:
            desc = (by_name[name].description or "").split("\n")[0][:90]
            print(f"  - {name}")
            print(f"      {desc}")

    # ── SECTION 2: 상세 스키마 (TARGET_TOOLS만) ──────────
    print()
    print("=" * 70)
    print(f"SECTION 2: 상세 스키마 ({len(TARGET_TOOLS)}개 대상)")
    print("=" * 70)
    for target in TARGET_TOOLS:
        print()
        if target not in by_name:
            print(f"[!] {target} : 도구 없음")
            continue
        t = by_name[target]
        print(f"[+] {target}")
        print(f"  description: {(t.description or '').split(chr(10))[0]}")
        print(f"  args:")
        for arg_name, arg_info in (t.args or {}).items():
            arg_type = arg_info.get("type", "?")
            arg_desc = arg_info.get("description", "")[:80]
            print(f"    - {arg_name} ({arg_type}): {arg_desc}")
        schema = getattr(t, "args_schema", None)
        if schema and hasattr(schema, "model_json_schema"):
            full = schema.model_json_schema()
            req = full.get("required", [])
            print(f"  required: {req}")


if __name__ == "__main__":
    asyncio.run(main())

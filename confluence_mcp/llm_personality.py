"""[용도] 성향별 프로필 페이지를 LLM이 자율적으로 작성/등록 — LLM-driven 패턴 데모.

[패턴 비교]
- code-driven (confluence_official.py): 코드가 호출 시점·인자·본문을 모두 결정. LLM은 Confluence를 모름.
- LLM-driven (이 파일): 코드는 도구 셋·제약(부모/제목 prefix)만 강제하고, 본문 작성과 도구 호출은 LLM이 자율.

[적용 시점] 시뮬레이션 시작 시 1회 (성향별 1장). Reflection 사이클과 무관.

[mode 처리]
- "append": 매 실행마다 새 제목 → confluence_create_page 1개만 LLM에 노출
- "overwrite": 코드가 미리 같은 제목 페이지를 찾아두고, 결과에 따라 update 또는 create 도구만 노출
  → LLM은 도구 선택 분기를 모름. 외부 MCP는 도메인 도구가 없어서 "어느 도구를 부를지" 결정을
    클라이언트(코드)가 책임져야 함을 보여주는 사례. (커스텀 서버는 도메인 도구 1개에 mode만 전달)
"""
import asyncio

from deepagents import create_deep_agent

from confluence_mcp.confluence_official import (
    _ensure_init, _local, PARENT_PAGE_ID, SPACE_KEY, find_page_id_by_title,
)


PROFILE_TIMEOUT_SEC = 90   # OpenAI Responses API 응답 stall 방어 — 초과 시 본 성향 Profile만 포기


def create_personality_profile(
    personality, agent_name: str, run_id: str, model: str,
    mode: str = "append",
) -> bool:
    """성향 정보를 LLM에게 주고, LLM이 자율적으로 Confluence에 프로필 페이지를 작성한다.

    LLM이 결정: 본문 형식·톤·강조 포인트.
    코드가 강제: 노출 도구(1개), 부모 페이지 ID, 제목 prefix, mode에 따른 분기.
    실패해도 시뮬레이션은 계속 진행 — bool 반환.
    """
    try:
        tools = _ensure_init()
    except Exception as e:
        print(f"[LLM-Confluence] init 실패: {type(e).__name__}: {e}")
        return False

    # 제목 — append: run_id suffix, overwrite: suffix 없는 고정 제목
    if mode == "append" and run_id:
        title = f"Profile_{agent_name}_{run_id}"
    else:
        title = f"Profile_{agent_name}"

    # overwrite 모드: 코드가 먼저 검색 → 있으면 update 도구만 노출, 없으면 create만 노출.
    # LLM은 분기를 알 필요 없음 (외부 MCP의 도메인 부재를 클라이언트 코드가 흡수)
    existing_id = None
    if mode == "overwrite":
        existing_id = find_page_id_by_title(title, tools)

    if existing_id:
        update_page = tools.get("confluence_update_page")
        if not update_page:
            print("[LLM-Confluence] confluence_update_page 도구가 없음")
            return False
        exposed_tool = update_page
        tool_instruction = (
            f"- confluence_update_page 도구를 정확히 1번만 호출하세요.\n"
            f"- 인자값:\n"
            f'  - page_id: "{existing_id}"\n'
            f'  - title: "{title}" (이 제목 그대로, 변경 금지)\n'
            f'  - content_format: "markdown"\n'
            f"  - content: 마크다운으로 자유 작성 (아래 가이드 참조)"
        )
    else:
        create_page = tools.get("confluence_create_page")
        if not create_page:
            print("[LLM-Confluence] confluence_create_page 도구가 없음")
            return False
        exposed_tool = create_page
        tool_instruction = (
            f"- confluence_create_page 도구를 정확히 1번만 호출하세요.\n"
            f"- 인자값:\n"
            f'  - space_key: "{SPACE_KEY}"\n'
            f'  - parent_id: "{PARENT_PAGE_ID}"\n'
            f'  - title: "{title}" (이 제목 그대로, 변경 금지)\n'
            f'  - content_format: "markdown"\n'
            f"  - content: 마크다운으로 자유 작성 (아래 가이드 참조)"
        )

    system_prompt = f"""당신은 회사원 시뮬레이션의 AI 에이전트입니다.
당신의 성향: {personality.name}
{personality.description}

방금 시뮬레이션을 시작했습니다. 자신의 프로필 페이지를 Confluence에 1장 작성하세요.

[작성 규칙 — 반드시 지킬 것]
{tool_instruction}

[content 가이드]
- 자기소개 한 문단 (당신이 누구인지)
- 이 성향의 강점과 약점 (당신이 판단한 대로)
- 시뮬레이션에서 어떻게 행동할 계획인지 (예상 전략)
- 다른 4개 성향("균형형", "성과형", "사교형", "정치형", "워라밸형" 중 본인 제외)과 비교한 차별점

본문은 자유롭게 — 테이블, 불릿, 산문 어떤 형식이든 OK.
도구 호출 후에는 별도의 응답 없이 종료하세요.
"""

    profile_agent = create_deep_agent(
        model=f"openai:{model}",
        tools=[exposed_tool],
        system_prompt=system_prompt,
        name=f"profile_{agent_name}",
    )

    # MCP 도구는 async-only(StructuredTool sync 미지원)이라 Deep Agent도 ainvoke로 돌려야 한다.
    # asyncio.wait_for로 90초 timeout — Responses API stall 시 30분 대기 방지
    try:
        _local.loop.run_until_complete(asyncio.wait_for(
            profile_agent.ainvoke({
                "messages": [{"role": "user", "content": "프로필 페이지를 작성하세요."}]
            }),
            timeout=PROFILE_TIMEOUT_SEC,
        ))
        return True
    except asyncio.TimeoutError:
        print(f"[LLM-Confluence] profile 작성 timeout ({agent_name}, {PROFILE_TIMEOUT_SEC}s 초과) — 본체 시뮬은 계속")
        return False
    except Exception as e:
        print(f"[LLM-Confluence] profile 작성 실패 ({agent_name}): {type(e).__name__}: {str(e)[:120]}")
        return False

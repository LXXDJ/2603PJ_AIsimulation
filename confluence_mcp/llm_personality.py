"""[용도] 성향별 프로필 페이지를 LLM이 자율적으로 작성/등록 — LLM-driven 패턴 데모.

[패턴 비교]
- code-driven (confluence_custom.py): 코드가 호출 시점·인자·본문을 모두 결정. LLM은 도구 모름.
- LLM-driven (이 파일): 코드는 도구 셋과 시스템 프롬프트만 강제, 본문 작성·도구 호출은 LLM 자율.

[공식 브랜치와의 차이]
- 공식 브랜치는 LLM에 일반 create_page를 노출 → LLM이 space_key/parent_id/title prefix까지
  시스템 프롬프트를 보고 직접 채워야 함 (실수 위험·프롬프트 길어짐).
- 본 브랜치는 서버에 도메인 도구 save_personality_profile을 추가 → LLM은 도메인 인자
  (personality_name, agent_name, content, run_id)만 채우면 끝. 부수 인자는 서버가 알아서.

[적용 시점] 시뮬레이션 시작 시 1회 (성향별 1장).
[노출 도구] save_personality_profile 1개만 (다른 호출 봉쇄).
"""
import asyncio

from deepagents import create_deep_agent

from confluence_mcp.confluence_custom import _ensure_init, _local


PROFILE_TIMEOUT_SEC = 90   # OpenAI 호출 hang 방어 — 이 시간 초과하면 해당 성향 프로필만 포기하고 본체 시뮬은 계속


def create_personality_profile(
    personality, agent_name: str, run_id: str, model: str,
    mode: str = "append",
) -> bool:
    """성향 정보를 LLM에게 주고, LLM이 자율적으로 Confluence에 프로필 페이지를 작성한다.

    LLM이 결정: 본문 형식·톤·강조 포인트, 도구 호출 자체.
    코드가 강제: 노출 도구 셋(1개), 시스템 프롬프트 규약.
    실패해도 시뮬레이션은 계속 진행 — bool 반환.
    """
    try:
        tools = _ensure_init()
    except Exception as e:
        print(f"[LLM-Custom] init 실패: {type(e).__name__}: {e}")
        return False

    save_profile = tools.get("save_personality_profile")
    if not save_profile:
        print("[LLM-Custom] save_personality_profile 도구가 없음")
        return False

    system_prompt = f"""당신은 회사원 시뮬레이션의 AI 에이전트입니다.
당신의 성향: {personality.name}
{personality.description}

방금 시뮬레이션을 시작했습니다. 자신의 프로필 페이지를 Confluence에 1장 작성하세요.

[작성 규칙]
- save_personality_profile 도구를 정확히 1번만 호출하세요.
- 인자값:
  - personality_name: "{personality.name}"
  - agent_name: "{agent_name}"
  - run_id: "{run_id}"
  - mode: "{mode}"
  - content: 마크다운으로 자유 작성 (아래 가이드 참조)

[content 가이드]
- 자기소개 한 문단
- 이 성향의 강점과 약점
- 시뮬레이션에서 어떻게 행동할 계획인지
- 다른 4개 성향("균형형", "성과형", "사교형", "정치형", "워라밸형" 중 본인 제외)과 비교한 차별점

도구 호출 후에는 별도 응답 없이 종료하세요.
"""

    profile_agent = create_deep_agent(
        model=f"openai:{model}",
        tools=[save_profile],
        system_prompt=system_prompt,
        name=f"profile_{agent_name}",
    )

    # langchain-mcp-adapters가 async-only → ainvoke로 thread-local loop 위에서 실행
    # OpenAI 호출이 가끔 응답을 안 줘서 hang 발생 → asyncio.wait_for로 시간 제한
    try:
        _local.loop.run_until_complete(asyncio.wait_for(
            profile_agent.ainvoke({
                "messages": [{"role": "user", "content": "프로필 페이지를 작성하세요."}]
            }),
            timeout=PROFILE_TIMEOUT_SEC,
        ))
        return True
    except asyncio.TimeoutError:
        print(f"[LLM-Custom] profile 작성 timeout ({agent_name}, {PROFILE_TIMEOUT_SEC}s 초과) — 본체 시뮬은 계속")
        return False
    except Exception as e:
        print(f"[LLM-Custom] profile 작성 실패 ({agent_name}): {type(e).__name__}: {str(e)[:120]}")
        return False

from llm.client import LLMClient


def compress_history(history: list[dict], llm: LLMClient, window: int = 30) -> str:
    """
    에이전트의 최근 history를 LLM으로 요약한다.
    컨텍스트 한계 문제를 해결하기 위한 핵심 모듈.
    """
    if not history:
        return ""

    recent = history[-window:]
    history_text = "\n".join(
        f"[{h['day']}일] {h['action']}" for h in recent
    )

    system = "당신은 회사원 에이전트의 행동 기록을 요약하는 역할입니다."
    user = (
        f"다음은 에이전트의 최근 {len(recent)}일 행동 기록입니다.\n\n"
        f"{history_text}\n\n"
        "3문장 이내로 전략적 패턴과 주요 변화를 요약하세요."
    )

    return llm.call(system=system, messages=[{"role": "user", "content": user}], max_tokens=200)

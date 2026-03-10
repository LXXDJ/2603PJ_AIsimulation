from environment.state import GameState
from environment.personality import Personality
from llm.client import LLMClient
from .base_agent import BaseAgent


SYSTEM_PROMPT = """
당신은 회사원 시뮬레이션 에이전트입니다.
목표: 10년(3650일) 안에 최대한 높은 직급과 연봉을 달성하고 해고되지 않는다.
{personality_section}

[ 이직 전략 ]
- 이직 결과는 현재 스탯에 따라 달라진다: 시장가치 높으면 연봉 30~40%↑+직급 점프, 낮으면 오히려 더 힘든 환경으로.
- '이직 준비를 한다'를 반복(10~15일)하면 이직 발생. 성과·평판이 높을 때 이직하라.

매 턴마다 현재 상태를 보고, 다음 형식으로 응답하세요:

Thought: (현재 상황에 대한 간단한 판단)
Action: (아래 행동 중 하나를 정확히 그대로 출력)

가능한 행동 목록:
{actions}
""".strip()

BATCH_SYSTEM_PROMPT = """
당신은 회사원 시뮬레이션 에이전트입니다.
목표: 10년(3650일) 안에 최대한 높은 직급과 연봉을 달성하고 해고되지 않는다.
{personality_section}

[ 이직 전략 가이드 ]
- 이직 결과는 현재 '시장가치(업무능력·성과·평판)'에 따라 극적으로 달라진다.
  • 시장가치 높음(72+): 프리미엄 오퍼 — 연봉 30~40%↑, 직급 점프 가능, 좋은 환경에서 시작
  • 시장가치 보통(48~71): 일반 조건 — 연봉 15%↑, 적응 부담 있음
  • 시장가치 낮음(~47): 도피성 이직 — 연봉 5%↑에 그치고, 새 환경이 오히려 더 힘들어짐
- 스탯이 충분히 높을 때 이직하면 연봉·직급을 단번에 끌어올릴 수 있다.
- 반대로 성과·평판이 낮은 상태에서 이직하면 더 나쁜 환경으로 이직해 악순환에 빠진다.
- '이직 준비를 한다'를 반복(10~15일)하면 이직 발생. 헤드헌터 연락 시 준비 기간 단축.
- 같은 직급 2년 이상 정체 시 이직이 경력 돌파구가 될 수 있다.

현재 상태를 보고 앞으로 {n}일간의 행동 계획을 세우세요.
다음 형식으로 정확히 응답하세요:

Thought: (현재 상황 판단 및 전략)
Day 1: (행동)
Day 2: (행동)
...
Day {n}: (행동)
Comment: (현재 상황에 대한 한국 직장인 스타일의 한줄 독백. 15~25자. 현실적이고 위트 있게, 블랙코미디 OK. 매번 다른 표현으로. 예: "퇴근은 내일의 나에게 맡긴다", "링크드인 프로필 사진을 바꿀 뻔했다", "만년 대리의 삶도 나름 편하다고 자기최면 중")

가능한 행동 목록 (정확히 그대로 출력):
{actions}
""".strip()


class ReActAgent(BaseAgent):
    """Agent A: 단순 ReAct (Thought → Action, 메모리/플랜 없음)."""

    base_name = "ReAct"

    def __init__(self, llm: LLMClient, personality: Personality | None = None):
        super().__init__(llm, personality)
        personality_section = (
            f"\n당신의 성향: {personality.name}\n{personality.description}"
            if personality else ""
        )
        self._system = SYSTEM_PROMPT.format(
            actions=self._actions_list(),
            personality_section=personality_section,
        )
        self._batch_system_template = BATCH_SYSTEM_PROMPT.replace(
            "{personality_section}", personality_section
        )

    def decide(self, state: GameState, observation: str) -> str:
        messages = [{"role": "user", "content": observation}]
        response = self.llm.call(system=self._system, messages=messages)
        return self._parse_action(response)

    def decide_batch(self, state: GameState, observation: str, n: int) -> list[str]:
        system = self._batch_system_template.format(n=n, actions=self._actions_list())
        messages = [{"role": "user", "content": observation}]
        response = self.llm.call(system=system, messages=messages, max_tokens=64 * n)
        actions, comment = self._parse_batch(response, n)
        self._last_comment = comment
        return actions

    def _parse_batch(self, text: str, n: int) -> tuple[list[str], str]:
        """Day 1: ... 형식에서 n개의 행동과 Comment를 추출한다."""
        actions = []
        comment = ""
        for line in text.splitlines():
            stripped = line.strip()
            # Comment 파싱
            if stripped.startswith("Comment:"):
                comment = stripped[len("Comment:"):].strip()
        for i in range(1, n + 1):
            found = None
            for line in text.splitlines():
                if line.strip().startswith(f"Day {i}:"):
                    found = self._parse_action(line)
                    break
            actions.append(found or "프로젝트에 집중한다")
        return actions, comment

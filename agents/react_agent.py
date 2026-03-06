from environment.state import GameState
from llm.client import LLMClient
from .base_agent import BaseAgent


SYSTEM_PROMPT = """
당신은 회사원 시뮬레이션 에이전트입니다.
목표: 3년(1095일) 안에 최대한 높은 직급과 연봉을 달성하고 해고되지 않는다.

매 턴마다 현재 상태를 보고, 다음 형식으로 응답하세요:

Thought: (현재 상황에 대한 간단한 판단)
Action: (아래 행동 중 하나를 정확히 그대로 출력)

가능한 행동 목록:
{actions}
""".strip()

BATCH_SYSTEM_PROMPT = """
당신은 회사원 시뮬레이션 에이전트입니다.
목표: 3년(1095일) 안에 최대한 높은 직급과 연봉을 달성하고 해고되지 않는다.

현재 상태를 보고 앞으로 {n}일간의 행동 계획을 세우세요.
다음 형식으로 정확히 응답하세요:

Thought: (현재 상황 판단 및 전략)
Day 1: (행동)
Day 2: (행동)
...
Day {n}: (행동)

가능한 행동 목록 (정확히 그대로 출력):
{actions}
""".strip()


class ReActAgent(BaseAgent):
    """Agent A: 단순 ReAct (Thought → Action, 메모리/플랜 없음)."""

    name = "ReAct"

    def __init__(self, llm: LLMClient):
        super().__init__(llm)
        self._system = SYSTEM_PROMPT.format(actions=self._actions_list())

    def decide(self, state: GameState, observation: str) -> str:
        messages = [{"role": "user", "content": observation}]
        response = self.llm.call(system=self._system, messages=messages)
        return self._parse_action(response)

    def decide_batch(self, state: GameState, observation: str, n: int) -> list[str]:
        system = BATCH_SYSTEM_PROMPT.format(n=n, actions=self._actions_list())
        messages = [{"role": "user", "content": observation}]
        response = self.llm.call(system=system, messages=messages, max_tokens=64 * n)
        return self._parse_batch(response, n)

    def _parse_batch(self, text: str, n: int) -> list[str]:
        """Day 1: ... 형식에서 n개의 행동을 순서대로 추출한다."""
        actions = []
        for i in range(1, n + 1):
            found = None
            for line in text.splitlines():
                if line.strip().startswith(f"Day {i}:"):
                    found = self._parse_action(line)
                    break
            actions.append(found or "프로젝트에 집중한다")
        return actions

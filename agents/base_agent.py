from abc import ABC, abstractmethod
from environment.state import GameState, ACTIONS
from llm.client import LLMClient


class BaseAgent(ABC):
    """모든 에이전트의 공통 인터페이스."""

    name: str = "BaseAgent"

    def __init__(self, llm: LLMClient):
        self.llm = llm
        self.history: list[dict] = []   # {"day": int, "action": str, "observation": str}

    @abstractmethod
    def decide(self, state: GameState, observation: str) -> str:
        """현재 상태를 받아 행동 하나를 반환한다."""

    def decide_batch(self, state: GameState, observation: str, n: int) -> list[str]:
        """현재 상태를 받아 n일치 행동 계획을 반환한다. 기본은 decide()를 n번 호출."""
        return [self.decide(state, observation)] * n

    def record(self, day: int, action: str, observation: str):
        self.history.append({"day": day, "action": action, "observation": observation})

    def reset(self):
        self.history = []

    # ------------------------------------------------------------------
    # 공통 유틸
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_action(text: str) -> str:
        """LLM 응답 텍스트에서 유효한 행동 하나를 추출한다."""
        for action in ACTIONS:
            if action in text:
                return action
        # 파싱 실패 시 기본 행동
        return "프로젝트에 집중한다"

    @staticmethod
    def _actions_list() -> str:
        return "\n".join(f"- {a}" for a in ACTIONS)

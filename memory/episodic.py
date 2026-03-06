from dataclasses import dataclass, field


@dataclass
class Episode:
    day: int
    action: str
    events: list[str]
    outcome_summary: str    # "승진", "해고 위기", "평범한 하루" 등
    state_snapshot: dict    # 핵심 수치 스냅샷


class EpisodicMemory:
    """
    에이전트가 경험한 중요한 사건들을 저장한다.
    중요도 기반으로 최근 N개만 유지한다.
    """

    def __init__(self, capacity: int = 50):
        self.capacity = capacity
        self.episodes: list[Episode] = []

    def add(self, episode: Episode):
        self.episodes.append(episode)
        if len(self.episodes) > self.capacity:
            # 오래된 것 중 중요도 낮은 것 제거 (현재는 단순 FIFO)
            self.episodes.pop(0)

    def recall_recent(self, n: int = 10) -> list[Episode]:
        return self.episodes[-n:]

    def recall_by_outcome(self, keyword: str) -> list[Episode]:
        return [e for e in self.episodes if keyword in e.outcome_summary]

    def to_text(self, n: int = 10) -> str:
        recent = self.recall_recent(n)
        if not recent:
            return "기억 없음"
        lines = []
        for e in recent:
            lines.append(
                f"[{e.day}일차] 행동: {e.action} | 결과: {e.outcome_summary}"
                + (f" | 이벤트: {', '.join(e.events)}" if e.events else "")
            )
        return "\n".join(lines)

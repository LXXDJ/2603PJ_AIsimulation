from dataclasses import dataclass, field


POSITIONS = ["사원", "대리", "과장", "팀장"]

ACTIONS = [
    "야근한다",
    "상사와 점심을 먹는다",
    "동료를 도와준다",
    "정치적으로 행동한다",
    "이직 준비를 한다",
    "휴가를 쓴다",
    "자기계발을 한다",
    "프로젝트에 집중한다",
]


@dataclass
class GameState:
    day: int = 0

    # 역량 지표 (0-100)
    performance: float = 50.0
    boss_favor: float = 50.0
    peer_relation: float = 50.0
    reputation: float = 50.0
    political_skill: float = 30.0

    # 컨디션 지표 (0-100)
    stress: float = 30.0
    energy: float = 80.0

    # 커리어
    salary: int = 3000000       # 월급 (원)
    position: str = "사원"
    is_fired: bool = False
    is_resigned: bool = False

    # 오늘 발생한 이벤트 (텍스트 리스트)
    events_today: list = field(default_factory=list)

    @property
    def year(self) -> int:
        return self.day // 365 + 1

    @property
    def month(self) -> int:
        return (self.day % 365) // 30 + 1

    @property
    def is_alive(self) -> bool:
        return not self.is_fired and not self.is_resigned

    @property
    def position_level(self) -> int:
        return POSITIONS.index(self.position)

    def clamp_all(self):
        self.performance = max(0.0, min(100.0, self.performance))
        self.boss_favor = max(0.0, min(100.0, self.boss_favor))
        self.peer_relation = max(0.0, min(100.0, self.peer_relation))
        self.reputation = max(0.0, min(100.0, self.reputation))
        self.political_skill = max(0.0, min(100.0, self.political_skill))
        self.stress = max(0.0, min(100.0, self.stress))
        self.energy = max(0.0, min(100.0, self.energy))

    def to_observation(self) -> str:
        lines = [
            f"[{self.year}년 {self.month}월 / {self.day}일차] 직급: {self.position} | 월급: {self.salary:,}원",
            "",
            "[ 현재 상태 ]",
            f"  업무 성과: {self._label(self.performance)}  ({self.performance:.0f})",
            f"  상사 신뢰: {self._label(self.boss_favor)}  ({self.boss_favor:.0f})",
            f"  동료 관계: {self._label(self.peer_relation)}  ({self.peer_relation:.0f})",
            f"  평판:     {self._label(self.reputation)}  ({self.reputation:.0f})",
            f"  정치력:   {self._label(self.political_skill)}  ({self.political_skill:.0f})",
            "",
            "[ 컨디션 ]",
            f"  스트레스: {self._stress_label()}  ({self.stress:.0f})",
            f"  에너지:   {self._energy_label()}  ({self.energy:.0f})",
        ]

        # 위험 경고
        warnings = self._warnings()
        if warnings:
            lines += ["", "[ 경고 ]"] + [f"  ! {w}" for w in warnings]

        return "\n".join(lines)

    @staticmethod
    def _label(value: float) -> str:
        if value >= 80:
            return "매우 좋음"
        if value >= 60:
            return "양호"
        if value >= 40:
            return "보통"
        if value >= 20:
            return "위험"
        return "매우 위험"

    def _stress_label(self) -> str:
        if self.stress >= 80:
            return "극심함 - 번아웃 직전"
        if self.stress >= 60:
            return "높음 - 판단력 저하 가능"
        if self.stress >= 40:
            return "보통"
        return "낮음"

    def _energy_label(self) -> str:
        if self.energy >= 70:
            return "충분"
        if self.energy >= 40:
            return "보통"
        if self.energy >= 20:
            return "피로 - 효율 저하"
        return "탈진 상태"

    def _warnings(self) -> list[str]:
        w = []
        if self.performance < 25:
            w.append("업무 성과가 해고 위험 수준입니다.")
        if self.boss_favor < 20:
            w.append("상사 신뢰가 매우 낮습니다. 해고될 수 있습니다.")
        if self.stress > 80:
            w.append("스트레스가 위험 수준입니다. 번아웃 또는 자진퇴사 가능성이 있습니다.")
        if self.energy < 15:
            w.append("에너지가 거의 없습니다. 휴식이 필요합니다.")
        return w

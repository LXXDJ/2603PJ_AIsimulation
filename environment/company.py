import copy
import random
from .state import GameState, ACTIONS, POSITIONS
from .events import roll_events


# 행동 → 상태 변화 정의
ACTION_EFFECTS: dict[str, dict] = {
    "야근한다": {
        "performance": 8,
        "boss_favor": 5,
        "stress": 15,
        "energy": -20,
        "peer_relation": -2,
    },
    "상사와 점심을 먹는다": {
        "boss_favor": 12,
        "political_skill": 5,
        "peer_relation": 2,
        "energy": -5,
    },
    "동료를 도와준다": {
        "peer_relation": 10,
        "reputation": 5,
        "performance": -3,
        "energy": -8,
    },
    "정치적으로 행동한다": {
        "political_skill": 8,
        "boss_favor": 6,
        "peer_relation": -5,
        "reputation": -3,
    },
    "이직 준비를 한다": {
        "energy": 5,
        "performance": -5,
        "stress": -5,
    },
    "휴가를 쓴다": {
        "energy": 30,
        "stress": -25,
        "performance": -5,
        "boss_favor": -3,
    },
    "자기계발을 한다": {
        "performance": 5,
        "reputation": 3,
        "energy": -10,
        "stress": 5,
    },
    "프로젝트에 집중한다": {
        "performance": 10,
        "reputation": 5,
        "stress": 10,
        "energy": -15,
        "boss_favor": 3,
    },
}

# 승진 조건
PROMOTION_REQUIREMENTS: dict[str, dict] = {
    "사원": {"performance": 65, "boss_favor": 60, "reputation": 55, "min_days": 180},
    "대리": {"performance": 75, "boss_favor": 65, "reputation": 65, "min_days": 540},
    "과장": {"performance": 85, "boss_favor": 70, "reputation": 75, "min_days": 900},
}

# 해고 조건
FIRE_THRESHOLD = {"performance": 20, "boss_favor": 15}


class CompanyEnvironment:
    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.state = GameState()
        self._promotion_cooldown = 0   # 승진 후 일정 기간 재승진 방지

    def reset(self) -> GameState:
        self.state = GameState()
        self._promotion_cooldown = 0
        return copy.deepcopy(self.state)

    def step(self, action: str) -> tuple[GameState, str]:
        """
        행동 하나를 받아 환경을 1일 전진시킨다.
        반환: (새 상태, 관찰 텍스트)
        """
        assert action in ACTIONS, f"유효하지 않은 행동: {action}"

        self.state.day += 1
        self.state.events_today = []
        log_lines = []

        # 1. 행동 효과 적용
        effects = ACTION_EFFECTS[action]
        self._apply_effects(effects)
        log_lines.append(f"행동: {action}")

        # 2. 자연 회복 / 자연 저하 (매일 소폭 변화)
        self._apply_daily_drift()

        # 3. 랜덤 이벤트 발생
        events = roll_events(self.rng)
        for event in events:
            self._apply_effects(event.effects)
            self.state.events_today.append(event.name)
            log_lines.append(f"이벤트: {event.description}")

        # 4. 수치 범위 클램프
        self.state.clamp_all()

        # 5. 해고 판정
        if self._check_fired():
            self.state.is_fired = True
            log_lines.append("결과: 해고되었다.")

        # 6. 승진 판정
        elif self._check_promotion():
            old_pos = self.state.position
            idx = POSITIONS.index(self.state.position)
            self.state.position = POSITIONS[idx + 1]
            self.state.salary = int(self.state.salary * 1.15)
            self._promotion_cooldown = 90
            log_lines.append(f"결과: {old_pos} → {self.state.position} 승진! 월급 15% 인상.")

        else:
            if self._promotion_cooldown > 0:
                self._promotion_cooldown -= 1
            # 연봉 인상 (180일마다 소폭)
            if self.state.day % 180 == 0:
                self.state.salary = int(self.state.salary * 1.03)
                log_lines.append("결과: 정기 연봉 인상 (3%).")

        observation = self.state.to_observation()
        if log_lines:
            observation += "\n" + "\n".join(log_lines)

        return copy.deepcopy(self.state), observation

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _apply_effects(self, effects: dict):
        for key, value in effects.items():
            current = getattr(self.state, key, None)
            if current is not None:
                setattr(self.state, key, current + value)

    def _apply_daily_drift(self):
        """매일 소폭 자연 회복/저하."""
        self.state.energy += 5          # 하루 자고 나면 에너지 회복
        self.state.stress -= 2          # 스트레스 자연 감소
        self.state.boss_favor -= 0.5    # 방치하면 서서히 낮아짐
        self.state.peer_relation -= 0.3

    def _check_fired(self) -> bool:
        if self.state.is_fired or self.state.is_resigned:
            return False
        return (
            self.state.performance < FIRE_THRESHOLD["performance"]
            or self.state.boss_favor < FIRE_THRESHOLD["boss_favor"]
        )

    def _check_promotion(self) -> bool:
        if self._promotion_cooldown > 0:
            return False
        pos = self.state.position
        if pos not in PROMOTION_REQUIREMENTS:
            return False
        req = PROMOTION_REQUIREMENTS[pos]
        return (
            self.state.performance >= req["performance"]
            and self.state.boss_favor >= req["boss_favor"]
            and self.state.reputation >= req["reputation"]
            and self.state.day >= req["min_days"]
        )

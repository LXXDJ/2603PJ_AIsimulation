import copy
import random
from .state import GameState, ACTIONS, POSITIONS
from .events import roll_events
from .personality import Personality


# 행동 → 상태 변화 정의
# 설계 원칙: 일상 행동 = 현상 유지 수준, 사건(event)이 유의미한 변화의 주요 원천
# performance/boss_favor/reputation은 skill처럼 느리게 쌓임 (peer_relation은 상대적으로 유동적)
ACTION_EFFECTS: dict[str, dict] = {
    "야근한다": {
        "skill": 0.10,
        "performance": 0.07,
        "stress": 15,
        "energy": -20,
        "peer_relation": -1,   # 야근 중엔 동료 관계 소홀
        # boss_favor 없음: 야근은 아웃풋 행동, 관계 행동이 아님
    },
    "상사와 점심을 먹는다": {
        "boss_favor": 2.0,     # 관계 쌓기는 중요하지만 한 번 밥 먹는다고 확 오르진 않음
        "political_skill": 0.04,
        "peer_relation": 0.5,
        "energy": -3,
    },
    "동료를 도와준다": {
        "peer_relation": 3,    # 동료 관계는 상대적으로 빠르게 반응 (유동적)
        "reputation": 0.15,    # 평판은 쌓이는 데 오래 걸림
        "performance": -0.04,
        "energy": -8,
    },
    "정치적으로 행동한다": {
        "political_skill": 0.06,
        "boss_favor": 0.8,
        "peer_relation": -1.5,
        "reputation": -0.25,
    },
    "이직 준비를 한다": {
        "energy": 5,
        "performance": -0.12,
        "stress": -5,
    },
    "휴가를 쓴다": {
        "energy": 30,
        "stress": -25,
        "performance": -0.12,
        "boss_favor": -1.5,
    },
    "자기계발을 한다": {
        "skill": 0.20,
        "performance": 0.05,
        "reputation": 0.12,    # 자기계발도 평판에 조금씩 영향
        "energy": -10,
        "stress": 5,
    },
    "프로젝트에 집중한다": {
        "skill": 0.12,
        "performance": 0.10,   # 매일 집중해도 한달 +2 — 사건이 큰 도약 계기, 행동은 기반 유지
        "reputation": 0.18,
        "stress": 10,
        "energy": -15,
        "boss_favor": 0.4,     # 성과 내면 상사에게 소폭 인정받음
    },
}

# 직급별 추가 연차 (근로기준법 기본 + 회사 관행)
POSITION_LEAVE_BONUS: dict[str, int] = {
    "사원": 0,
    "대리": 1,
    "과장": 3,
    "차장": 5,
    "부장": 7,
    "이사": 10,
    "임원": 15,
}

# 해고 조건 (성과/관계가 모두 느리게 쌓이는 새 스케일에 맞게 조정)
FIRE_THRESHOLD = {"performance": 10, "boss_favor": 10}
PROBATION_DAYS = 365  # 입사(이직) 후 해고 유예 기간 (1년)

# 직급별 연봉 상한 (원) — 한국 대기업 기준 현실적 밴드
SALARY_CAP = {
    "사원": 50_000_000,       # 5천만
    "대리": 65_000_000,       # 6500만
    "과장": 85_000_000,       # 8500만
    "차장": 110_000_000,      # 1.1억
    "부장": 140_000_000,      # 1.4억
    "이사": 200_000_000,      # 2억
    "임원": 300_000_000,      # 3억
}

# 주말 활동 풀 (성향별 가중치로 선택)
WEEKEND_ACTIVITIES: dict[str, dict] = {
    "휴식":     {"energy": 10,  "stress": -7},
    "자기계발": {"energy": 8,   "stress": -4,  "skill": 0.06, "performance": 0.04},
    "사교":     {"energy": 12,  "stress": -6,  "peer_relation": 3, "reputation": 0.08},
    "인맥관리": {"energy": 10,  "stress": -5,  "boss_favor": 1.0,  "political_skill": 0.03},
    "여행":     {"energy": -8,  "stress": -18},
}


class CompanyEnvironment:
    def __init__(self, seed: int | None = None, personality: Personality | None = None, max_days: int = 1825):
        self.rng = random.Random(seed)
        self.personality = personality
        self.max_days = max_days
        self.state = GameState()
        self._promotion_cooldown = 0   # 승진 후 일정 기간 재승진 방지
        self._burnout_counter = 0      # 번아웃 조건 연속 일수 카운터
        self._chronic_stress_days = 0  # 만성 스트레스 누적 일수 (스트레스 70+ 시 +1, 아래면 -2)
        self._job_change_counter = 0   # 이직 준비 연속 일수 카운터
        self._last_hoesik_day = -30    # 마지막 회식 발생일 (30일 쿨다운)
        # 승진 요건: min_days는 단순 잠금 기간 (6개월~1년), 실제 병목은 스탯
        # 설계: performance 평형점 ≈ skill + 5 (프로젝트집중 0.05/0.01), boss_favor는 적극 관리 필요
        # 성향마다 다른 스탯이 병목이 됨: 성과형→boss_favor, 사교형→performance, 균형형→균형
        self.promotion_requirements = {
            "사원": {"skill": 22, "performance": 30, "boss_favor": 40, "reputation": 20,
                     "min_days": 365},   # 1년 잠금
            "대리": {"skill": 32, "performance": 42, "boss_favor": 48, "reputation": 35,
                     "min_days": 1095},  # 3년 잠금
            "과장": {"skill": 42, "performance": 52, "boss_favor": 53, "reputation": 45,
                     "min_days": 1825},  # 5년 잠금
            "차장": {"skill": 50, "performance": 60, "boss_favor": 58, "reputation": 55,
                     "min_days": 2555},  # 7년 잠금
            "부장": {"skill": 56, "performance": 66, "boss_favor": 62, "reputation": 62,
                     "min_days": 3100},  # 8.5년 잠금
        }

    def reset(self) -> GameState:
        self.state = GameState()
        self._promotion_cooldown = 0
        self._burnout_counter = 0
        self._chronic_stress_days = 0
        self._job_change_counter = 0
        self._last_hoesik_day = -30
        return copy.deepcopy(self.state)

    def step_weekend(self) -> tuple[GameState, str, str]:
        """
        주말 하루: 에이전트 행동 없이 자연 회복만 적용.
        평일보다 에너지/스트레스 회복량이 크다.
        """
        self.state.day += 1
        self.state.events_today = []
        log_lines = []

        # 주말 활동: 성향별 가중치로 랜덤 선택
        activities = list(WEEKEND_ACTIVITIES.keys())
        weights = [
            (self.personality.weekend_weights.get(a, 2) if self.personality else 2)
            for a in activities
        ]
        chosen = self.rng.choices(activities, weights=weights, k=1)[0]
        for key, value in WEEKEND_ACTIVITIES[chosen].items():
            current = getattr(self.state, key, None)
            if current is not None:
                setattr(self.state, key, current + value)
        log_lines.append(f"주말 활동: {chosen}")

        # 자연 감소 (주말에도 소폭)
        self.state.boss_favor -= 0.1
        self.state.peer_relation -= 0.15

        # 랜덤 이벤트 (주말에도 발생 가능)
        events = self._filter_events(roll_events(self.rng, self.personality, self.state))
        for event in events:
            self._apply_effects(event.effects)
            for key, value in event.resets.items():
                if hasattr(self.state, key):
                    setattr(self.state, key, float(value))
            self.state.events_today.append(event.name)
            log_lines.append(f"이벤트: {event.description}")

        self.state.clamp_all()

        # 번아웃 / 만성스트레스 / 해고 판정 (주말에도 유효)
        if self._check_burnout():
            self.state.is_resigned = True
            log_lines.append(f"결과: 번아웃으로 자진퇴사했다. (극한 상태 {self._burnout_counter}일 지속)")
        elif self._check_chronic_stress():
            self.state.is_resigned = True
            log_lines.append(f"결과: 만성 스트레스로 자진퇴사했다. (고스트레스 누적 {self._chronic_stress_days}일)")
        else:
            fire_reason = self._check_fired()
            if fire_reason:
                self.state.is_fired = True
                log_lines.append(f"결과: {fire_reason}")

        if self._promotion_cooldown > 0:
            self._promotion_cooldown -= 1

        observation = self.state.to_observation()
        if log_lines:
            observation += "\n" + "\n".join(log_lines)

        return copy.deepcopy(self.state), observation, chosen

    def step(self, action: str) -> tuple[GameState, str]:
        """
        행동 하나를 받아 환경을 1일 전진시킨다.
        반환: (새 상태, 관찰 텍스트)
        """
        assert action in ACTIONS, f"유효하지 않은 행동: {action}"

        self.state.day += 1
        self.state.events_today = []
        log_lines = []

        # 1. 행동 효과 적용 (성향 보정 포함)
        # 연차 소진 시 휴가 차단
        if action == "휴가를 쓴다":
            remaining = self.state.annual_leave - self.state.leaves_used_this_year
            if remaining <= 0:
                log_lines.append("행동: 휴가를 쓴다 → 연차 소진! 쉬고 싶지만 쉴 수 없다.")
                self.state.stress += 5  # 못 쉬는 스트레스
                action = "프로젝트에 집중한다"  # 강제 대체
            else:
                self.state.leaves_used_this_year += 1
                log_lines.append(f"행동: {action}  (잔여 연차: {remaining - 1}일)")
        else:
            log_lines.append(f"행동: {action}")

        # 이직 준비 카운터 업데이트 (누적식 — 다른 행동해도 느리게 감소)
        if action == "이직 준비를 한다":
            self._job_change_counter += 3
        else:
            self._job_change_counter = max(0, self._job_change_counter - 1)

        effects = ACTION_EFFECTS[action]
        self._apply_effects(effects, action)

        # 2. 자연 회복 / 자연 저하 (매일 소폭 변화)
        self._apply_daily_drift()

        # 3. 랜덤 이벤트 발생
        events = self._filter_events(roll_events(self.rng, self.personality, self.state))
        for event in events:
            self._apply_effects(event.effects)
            for key, value in event.resets.items():
                if hasattr(self.state, key):
                    setattr(self.state, key, float(value))
            if event.name == "헤드헌터 연락":
                self._job_change_counter += 15  # 헤드헌터 연락 시 이직 의향 강화
            self.state.events_today.append(event.name)
            log_lines.append(f"이벤트: {event.description}")

        # 4. 수치 범위 클램프
        self.state.clamp_all()

        # 5. 번아웃 / 만성스트레스 판정 (해고보다 먼저)
        if self._check_burnout():
            self.state.is_resigned = True
            log_lines.append(f"결과: 번아웃으로 자진퇴사했다. (극한 상태 {self._burnout_counter}일 지속)")
        elif self._check_chronic_stress():
            self.state.is_resigned = True
            log_lines.append(f"결과: 만성 스트레스로 자진퇴사했다. (고스트레스 누적 {self._chronic_stress_days}일)")

        # 6. 해고 판정
        else:
            fire_reason = self._check_fired()
            if fire_reason:
                self.state.is_fired = True
                log_lines.append(f"결과: {fire_reason}")

        if not self.state.is_fired and not self.state.is_resigned:
            # 7. 이직 판정 (비종료 — 새 회사에서 계속)
            if self._check_job_change():
                log_lines.append(self._do_job_change())

            # 8. 승진 판정 (이직 후엔 스킵)
            elif self._check_promotion():
                old_pos = self.state.position
                idx = POSITIONS.index(self.state.position)
                self.state.position = POSITIONS[idx + 1]
                self.state.salary = int(self.state.salary * 1.15)
                # 직급별 재승진 대기 기간 (새 직급 기준)
                cooldown_by_pos = {"대리": 180, "과장": 365, "차장": 365, "부장": 545, "이사": 730}
                self._promotion_cooldown = cooldown_by_pos.get(self.state.position, 0)
                # 승진 시 연차 즉시 재계산 (직급 보너스 반영)
                new_leave = self._calc_annual_leave()
                added = new_leave - self.state.annual_leave
                self.state.annual_leave = new_leave
                bonus_str = f" (+{added}일 연차 추가)" if added > 0 else ""
                log_lines.append(f"결과: {old_pos} → {self.state.position} 승진! 연봉 15% 인상.{bonus_str}")
                self.state.position_entry_day = self.state.day  # 직급 진입일 갱신

            else:
                if self._promotion_cooldown > 0:
                    self._promotion_cooldown -= 1
                # 직급 정체 자동 이직 욕구: 같은 직급 2년 이상 + 승진 불가 상태면 이직 욕구 상승
                days_at_pos = self.state.day - self.state.position_entry_day
                if days_at_pos > 730 and self._promotion_cooldown > 0:
                    self._job_change_counter = min(
                        self._job_change_counter + 0.4, 35
                    )


        # 연초(1월 1일) 처리: 연봉협상 + 연차 리셋
        day_in_year = self.state.day % 365
        if day_in_year == 1 and self.state.day > 1:
            # 연봉 인상 (성과 기반 차등 인상)
            rate = self._calc_salary_raise_rate()
            self.state.salary = int(self.state.salary * (1 + rate))
            rate_pct = int(rate * 100)
            if rate_pct == 0:
                log_lines.append("새해: 연봉협상 완료 — 성과 부진으로 연봉 동결.")
            else:
                log_lines.append(f"새해: 연봉협상 완료 — {rate_pct}% 인상.")
            # 연차 초기화 + 근속연수 + 직급 반영
            new_leave = self._calc_annual_leave()
            self.state.annual_leave = new_leave
            self.state.leaves_used_this_year = 0
            log_lines.append(f"새해: 연차 {new_leave}일 지급.")

        # 연봉 상한 적용
        cap = SALARY_CAP.get(self.state.position)
        if cap and self.state.salary > cap:
            self.state.salary = cap

        observation = self.state.to_observation()
        if log_lines:
            observation += "\n" + "\n".join(log_lines)

        return copy.deepcopy(self.state), observation

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _calc_salary_raise_rate(self) -> float:
        """전년도 스탯 기반 연봉 인상률 계산 (0% ~ 6%)."""
        score = (
            self.state.skill           * 0.20 +
            self.state.performance     * 0.30 +
            self.state.boss_favor      * 0.25 +
            self.state.reputation      * 0.15 +
            self.state.political_skill * 0.10
        )
        if score < 30:  return 0.00   # 동결
        if score < 45:  return 0.01   # 1%
        if score < 60:  return 0.02   # 2%
        if score < 70:  return 0.03   # 3% (기본)
        if score < 80:  return 0.04   # 4%
        if score < 90:  return 0.05   # 5%
        return 0.06                   # 6%

    def _filter_events(self, events: list) -> list:
        """회식 30일 쿨다운 등 이벤트 후처리 필터."""
        result = []
        for event in events:
            if event.name == "회식":
                if self.state.day - self._last_hoesik_day < 30:
                    continue  # 쿨다운 중 — 스킵
                self._last_hoesik_day = self.state.day
            result.append(event)
        return result

    def _apply_effects(self, effects: dict, action: str | None = None):
        for key, value in effects.items():
            current = getattr(self.state, key, None)
            if current is not None:
                if action and self.personality:
                    value = value * self.personality.get_multiplier(action, key)
                # skill 성장 diminishing returns: 높을수록 느리게 (높은 역량은 쌓기 어렵다)
                if key == "skill" and value > 0:
                    # skill=10 → 1.5배 / skill=50 → 0.83배 / skill=80 → 0.33배
                    value = value * max(0.15, (100.0 - current) / 60.0)
                setattr(self.state, key, current + value)

    def _calc_annual_leave(self) -> int:
        """현재 회사 근속연수 + 직급 기반 연차 일수 계산."""
        tenure_leave = min(15 + (self.state.company_year - 1) // 2, 25)
        position_bonus = POSITION_LEAVE_BONUS.get(self.state.position, 0)
        return tenure_leave + position_bonus

    def _check_job_change(self) -> bool:
        """이직 준비를 30일 이상 지속하면 이직 발생."""
        return self._job_change_counter >= 30

    def _do_job_change(self) -> str:
        """이직 처리: 시장가치(스탯)에 따라 결과가 극적으로 달라진다.

        시장가치 높음 → 프리미엄 이직 (연봉 대폭↑, 직급 점프, 쾌적한 새 환경)
        시장가치 보통 → 일반 이직 (연봉 소폭↑, 직급 유지, 표준 적응 부담)
        시장가치 낮음 → 도피성 이직 (연봉 거의 동결, 더 힘든 환경, 해고 리스크 지속)
        """
        # 시장가치: 실력·성과·평판 중심으로 계산
        market_value = (
            self.state.skill        * 0.35 +
            self.state.performance  * 0.35 +
            self.state.reputation   * 0.20 +
            self.state.political_skill * 0.10
        )

        old_salary = self.state.salary
        old_pos    = self.state.position
        promoted   = False

        if market_value >= 72:
            # ── 프리미엄 이직: 실력자가 좋은 오퍼를 받는 경우 ──────────────
            raise_rate = 0.40 if market_value >= 85 else 0.30
            tier_label = "프리미엄 오퍼"

            # 직급 점프 (boss_favor 요건 면제 — 내부 정치가 아닌 외부 시장 평가)
            next_idx = POSITIONS.index(self.state.position) + 1
            if next_idx < len(POSITIONS):
                next_pos = POSITIONS[next_idx]
                req = self.promotion_requirements.get(next_pos)
                if req and (
                    self.state.skill       >= req["skill"] and
                    self.state.performance >= req["performance"] and
                    self.state.reputation  >= req["reputation"]
                ):
                    self.state.position = next_pos
                    self.state.position_entry_day = self.state.day
                    promoted = True

            # 좋은 회사 → 기대감 높고, 환경도 우호적
            self.state.boss_favor    = 65.0
            self.state.peer_relation = 45.0
            self.state.reputation    = max(0.0, self.state.reputation   - 3.0)
            self.state.political_skill = max(0.0, self.state.political_skill - 2.0)
            self.state.stress  = max(0.0,   self.state.stress  - 30.0)
            self.state.energy  = min(100.0, self.state.energy  + 20.0)

        elif market_value >= 48:
            # ── 일반 이직: 평범한 조건, 현실적인 적응 부담 ──────────────────
            raise_rate = 0.15
            tier_label = "일반 조건"

            # 표준 적응: 관계·성과 일부 리셋
            self.state.boss_favor    = 45.0
            self.state.peer_relation = 30.0
            self.state.reputation    = max(0.0, self.state.reputation   - 8.0)
            self.state.political_skill = max(0.0, self.state.political_skill - 4.0)
            self.state.performance   = max(0.0, self.state.performance  - 8.0)
            self.state.stress  = max(0.0,   self.state.stress  - 15.0)
            self.state.energy  = min(100.0, self.state.energy  + 5.0)

        else:
            # ── 도피성 이직: 실력·평판 부족 → 고만고만한 곳에서 악조건으로 시작 ──
            raise_rate = 0.05
            tier_label = "도피성 이직"

            # 새 환경이 오히려 더 힘듦 — 성과·관계 크게 하락, 스트레스 증가
            self.state.boss_favor    = 30.0
            self.state.peer_relation = 20.0
            self.state.reputation    = max(0.0, self.state.reputation   - 15.0)
            self.state.political_skill = max(0.0, self.state.political_skill - 5.0)
            self.state.performance   = max(0.0, self.state.performance  - 15.0)
            self.state.stress  = min(100.0, self.state.stress  + 15.0)
            self.state.energy  = max(0.0,   self.state.energy  - 10.0)

        self.state.salary = int(self.state.salary * (1 + raise_rate))

        # 새 회사 근속 리셋
        self.state.company_start_day     = self.state.day
        self.state.job_changes          += 1
        self.state.annual_leave          = self._calc_annual_leave()
        self.state.leaves_used_this_year = 0
        if not promoted:
            self.state.position_entry_day = self.state.day

        # 카운터/쿨다운 리셋
        self._job_change_counter  = 0
        self._promotion_cooldown  = 0

        raise_pct = int(raise_rate * 100)
        mv_str = f"시장가치 {market_value:.0f}"
        result = (
            f"결과: [{tier_label}] 이직! ({mv_str}) "
            f"연봉 {raise_pct}% 인상 ({old_salary:,} → {self.state.salary:,}원)"
        )
        if promoted:
            result += f" + {old_pos} → {self.state.position} 직급 상승!"
        else:
            result += f". {self.state.position}으로 새 회사 시작."
        return result

    def _apply_daily_drift(self):
        """평일 소폭 자연 회복/저하.
        설계 원칙: 행동 없이 방치 시 '현상 유지~소폭 하락', 적극 행동 시 조금씩 상승.
        peer_relation은 상대적으로 유동적 (동료 관계는 최근 행동에 민감).
        """
        self.state.energy += 5           # 하루 자고 나면 에너지 회복
        self.state.stress -= 2           # 스트레스 자연 감소

        # 관계·평판: 관리 안 하면 소폭 하락 → 적극 행동 시 서서히 성장
        # 설계 기준: 대표 행동 1회/일 시 net +0.1~0.3/일 (연간 +25~75 수준의 느린 성장)
        self.state.boss_favor -= 0.2     # 방치 시 주당 -1 → 프로젝트집중(+0.4)하면 +0.2/일 순성장
        self.state.peer_relation -= 0.3  # 동료 관계는 상대적으로 유동적
        self.state.reputation -= 0.03    # 평판은 오래 쌓이고 천천히 바램 (연간 -11, 행동으로 충분히 상쇄)

        # performance는 skill 수준으로 수렴 (방치하면 역량 수준까지 회귀)
        self.state.performance += (self.state.skill - self.state.performance) * 0.01
        self.state.skill -= 0.02         # 평시 자연 감소 (연간 약 -7)
        if self.state.stress >= 80:
            self.state.skill -= 0.05     # 극심한 스트레스 시 집중력 저하로 추가 감소
        # political_skill은 기질 — 자연 소멸 없음 (이벤트/행동으로만 변화)

    def _check_burnout(self) -> bool:
        """스트레스 ≥ 90 AND 체력 ≤ 10 상태가 30일 연속이면 번아웃 자진퇴사."""
        if self.state.is_fired or self.state.is_resigned:
            return False
        if self.state.stress >= 90 and self.state.energy <= 10:
            self._burnout_counter += 1
        else:
            self._burnout_counter = 0
        return self._burnout_counter >= 30

    def _check_chronic_stress(self) -> bool:
        """스트레스 70 이상이 누적 180일 이상이면 만성 스트레스 퇴사."""
        if self.state.is_fired or self.state.is_resigned:
            return False
        if self.state.stress >= 70:
            self._chronic_stress_days += 1
        else:
            # 스트레스 해소되면 천천히 회복 (하루에 2일분 감소)
            self._chronic_stress_days = max(0, self._chronic_stress_days - 2)
        return self._chronic_stress_days >= 180

    # 총 경력(day) 대비 최소 직급 — 이 경력에서 해당 직급 이하면 권고사직
    # (경력 기준일, 최소 직급 인덱스)  직급: 사원=0, 대리=1, 과장=2, 차장=3, 부장=4, 이사=5
    CAREER_POSITION_FLOOR = [
        (5 * 365,  1),   # 경력 5년 → 최소 대리
        (8 * 365,  2),   # 경력 8년 → 최소 과장
    ]

    def _check_fired(self) -> str:
        """해고 사유를 문자열로 반환. 해고 아니면 빈 문자열."""
        if self.state.is_fired or self.state.is_resigned:
            return ""
        # 입사(이직) 후 유예 기간 동안은 해고 없음
        days_at_company = self.state.day - self.state.company_start_day
        if days_at_company < PROBATION_DAYS:
            return ""

        # 1) 성과 + 상사 신뢰 동시 저조 → 해고
        if (
            self.state.performance < FIRE_THRESHOLD["performance"]
            and self.state.boss_favor < FIRE_THRESHOLD["boss_favor"]
        ):
            return "성과 부진으로 해고되었다."

        # 2) 총 경력 대비 직급 미달 → 권고사직 (이직으로 리셋 안 됨)
        total_career = self.state.day  # day 1부터 시작 = 총 경력
        current_level = self.state.position_level
        for career_threshold, min_level in self.CAREER_POSITION_FLOOR:
            if total_career >= career_threshold and current_level < min_level:
                years = total_career // 365
                return f"경력 {years}년차 {self.state.position} — 승진 미달로 권고사직 처리되었다."

        return ""

    def _check_promotion(self) -> bool:
        if self._promotion_cooldown > 0:
            return False
        pos = self.state.position
        if pos not in self.promotion_requirements:
            return False

        # 승진은 연 2회 인사 시즌에만 가능: 1월(1~30일), 7월(181~210일)
        day_in_year = self.state.day % 365
        in_jan = 1 <= day_in_year <= 30
        in_jul = 181 <= day_in_year <= 210
        if not (in_jan or in_jul):
            return False

        req = self.promotion_requirements[pos]
        return (
            self.state.skill >= req["skill"]
            and self.state.performance >= req["performance"]
            and self.state.boss_favor >= req["boss_favor"]
            and self.state.reputation >= req["reputation"]
            and self.state.day >= req["min_days"]
        )

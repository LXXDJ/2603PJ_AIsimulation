import json
import time
from datetime import datetime
from pathlib import Path
from tqdm import tqdm
from environment.company import CompanyEnvironment
from agents.base_agent import BaseAgent


def run_simulation(
    agent: BaseAgent,
    env: CompanyEnvironment,
    max_days: int = 1095,
    log_interval: int = 30,
    decision_interval: int = 1,
    log_dir: str = "logs",
    verbose: bool = True,
    tqdm_position: int = 0,
) -> dict:
    """
    시뮬레이션을 실행하고 결과를 반환한다.
    decision_interval > 1이면 배치 모드: N일치 행동을 한 번에 결정한다.
    상세 로그는 .txt 파일에 기록, 콘솔에는 진행률(%)만 출력한다.
    반환값: 최종 결과 딕셔너리
    """
    state = env.reset()
    agent.reset()
    step_logs = []
    pending_actions: list[str] = []
    recent_events: list[tuple[int, str]] = []  # (day, 이벤트명) 누적
    current_comment: str = ""  # LLM이 생성한 한줄 코멘트

    # 시뮬 시작 시 즉시 파일 생성 (중간에 중단해도 기록 보존)
    Path(log_dir).mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%y%m%d_%H%M%S')
    log_path = Path(log_dir) / f"{timestamp}_{agent.name}.jsonl"
    txt_path  = Path(log_dir) / f"{timestamp}_{agent.name}.txt"

    log_file = open(log_path, "w", encoding="utf-8")
    txt_file  = open(txt_path,  "w", encoding="utf-8")

    log_file.write(json.dumps({"type": "meta", "agent": agent.name,
                               "started_at": datetime.now().isoformat()}, ensure_ascii=False) + "\n")
    log_file.flush()
    txt_file.write(f"{'='*60}\n에이전트: {agent.name}  (시작: {datetime.now().isoformat()})\n{'='*60}\n")
    txt_file.flush()

    pbar = tqdm(
        total=max_days,
        desc=f"{agent.name}",
        position=tqdm_position,
        leave=True,
        unit="일",
        bar_format="{desc:<10} {percentage:3.0f}% |{bar:25}| {n_fmt}/{total_fmt}일  {postfix}",
        disable=not verbose,
    )

    for day in range(1, max_days + 1):
        is_weekend = (day - 1) % 7 >= 5  # 토(5)/일(6)

        if is_weekend:
            # 주말: 성향별 가중치로 활동 선택
            state, full_observation, action = env.step_weekend()
        else:
            # 배치 모드: 평일 계획이 소진되면 새로 요청
            if not pending_actions:
                observation = state.to_observation()
                remaining = min(decision_interval, max_days - day + 1)
                if decision_interval > 1:
                    pending_actions = agent.decide_batch(state, observation, remaining)
                    current_comment = getattr(agent, '_last_comment', '') or ""
                else:
                    pending_actions = [agent.decide(state, observation)]

            action = pending_actions.pop(0)

            # 환경 1일 전진
            state, full_observation = env.step(action)

        # 기록
        agent.record(day, action, full_observation)
        step = {
            "type": "step",
            "day": day,
            "action": action,
            "position": state.position,
            "salary": state.salary,
            "skill": round(state.skill, 1),
            "performance": round(state.performance, 1),
            "boss_favor": round(state.boss_favor, 1),
            "peer_relation": round(state.peer_relation, 1),
            "reputation": round(state.reputation, 1),
            "political_skill": round(state.political_skill, 1),
            "stress": round(state.stress, 1),
            "energy": round(state.energy, 1),
            "events": state.events_today,
            "job_changes": state.job_changes,
            "comment": current_comment,
        }
        step_logs.append(step)
        log_file.write(json.dumps(step, ensure_ascii=False) + "\n")
        log_file.flush()

        # 이벤트 누적
        for evt in state.events_today:
            recent_events.append((day, evt))

        # tqdm 매 스텝 업데이트 + postfix는 log_interval마다 갱신
        pbar.update(1)

        if day % log_interval == 0:
            leave_left = state.annual_leave - state.leaves_used_this_year
            job_str = f"  이직:{state.job_changes}회" if state.job_changes > 0 else ""
            detail = (
                f"[{agent.name}] Day {day:4d}  {state.position}  연봉: {state.salary:,}원 - "
                f"업무능력:{state.skill:.0f}  성과:{state.performance:.0f}  상사호감도:{state.boss_favor:.0f}  "
                f"동료관계:{state.peer_relation:.0f}  평판:{state.reputation:.0f}  정치능력:{state.political_skill:.0f}  "
                f"스트레스:{state.stress:.0f}  체력:{state.energy:.0f}  잔여연차:{leave_left}일{job_str}"
            )
            txt_file.write(detail + "\n")
            if recent_events:
                events_str = "  /  ".join(f"Day{d} {e}" for d, e in recent_events)
                txt_file.write(f"         └ 이벤트: {events_str}\n")
            txt_file.flush()
            recent_events = []

            pbar.set_postfix_str(f"{state.position}  {state.salary:,}원", refresh=False)

        if not state.is_alive:
            status = "해고" if state.is_fired else "자진퇴사"
            txt_file.write(f"[{agent.name}] {day}일차에 {status}됨.\n")
            txt_file.flush()
            pbar.set_postfix_str(f"→ {status}", refresh=True)
            break

    result = _build_result(agent.name, state, step_logs, max_days)

    # 결과 기록 후 파일 닫기
    log_file.write(json.dumps({"type": "result", **result}, ensure_ascii=False) + "\n")
    log_file.close()
    txt_file.write(f"\n결과 저장: {log_path}\n")
    txt_file.close()

    pbar.close()

    result["log_path"] = str(log_path)
    result["txt_path"] = str(txt_path)

    return result


def _stress_cause(state) -> str:
    """스트레스가 높을 때 가장 유력한 원인을 추론한다."""
    if state.boss_favor < 40:
        return "상사 때문에"
    if state.peer_relation < 35:
        return "동료들 눈치 보느라"
    if state.performance < 40:
        return "실적 압박으로"
    if state.energy < 25:
        return "과로가 쌓여"
    return "누적 스트레스로"


def _status_summary(state, burnout_counter: int) -> str:
    """현재 상태를 한 줄 위트 있게 요약한다."""
    # 번아웃 카운터 (최우선)
    if burnout_counter >= 20:
        return f"🚨 {burnout_counter}일째 한계 — 퇴사 각이 보인다"
    if burnout_counter >= 10:
        return f"😵 {burnout_counter}일째 버티는 중 — 몸이 먼저 나가떨어질 것 같다"
    if burnout_counter >= 1:
        return f"😰 한계 상태 {burnout_counter}일째 — 이러다 번아웃 온다"

    # 해고 위험
    if state.performance < 25 and state.boss_favor < 20:
        return "🔥 성과도 없고 상사 눈 밖에도 났다 — 짤릴 것 같은 느낌적 느낌"
    if state.performance < 25:
        return "📉 이 성과면 조만간 면담 각이다"
    if state.boss_favor < 20:
        return "😬 상사가 나를 못 마땅히 여기는 게 느껴진다"

    # 스트레스/체력 위험
    cause = _stress_cause(state)
    if state.stress >= 85 and state.energy <= 25:
        return f"💀 {cause} 스트레스 폭발 직전 + 체력도 바닥"
    if state.stress >= 85:
        return f"😤 {cause} 스트레스 폭발 직전 — 휴가가 절실하다"
    if state.stress >= 70:
        return f"😓 {cause} 스트레스가 슬슬 쌓이고 있다"
    if state.energy <= 10:
        return "🪫 몸이 한계 신호를 보내고 있다"
    if state.energy <= 25:
        return "😩 체력이 위험하다 — 좀 쉬어야 할 것 같다"

    # 긍정
    if state.stress < 35 and state.energy >= 75 and state.performance >= 75:
        return "😎 회사원이 천직인듯 — 승승장구 중"
    if state.performance >= 80:
        return "💪 이 기세면 진급도 문제없다"
    if state.boss_favor >= 80:
        return "🌟 상사한테 완전 낙점됐다"
    if state.peer_relation >= 80:
        return "🤝 사내 인싸 등극 — 동료들 사이 인기 최고"
    if state.stress < 40 and state.energy >= 60:
        return "✅ 회사생활 이상무!"
    return "🙂 그럭저럭 버티는 중"


def _build_result(agent_name: str, state, step_logs: list, max_days: int) -> dict:
    survived_days = step_logs[-1]["day"] if step_logs else 0
    return {
        "agent": agent_name,
        "survived_days": survived_days,
        "max_days": max_days,
        "final_position": state.position,
        "final_salary": state.salary,
        "is_fired": state.is_fired,
        "is_resigned": state.is_resigned,
        "promoted": state.position != "사원",
        "final_skill": round(state.skill, 1),
        "final_performance": round(state.performance, 1),
        "final_boss_favor": round(state.boss_favor, 1),
        "final_stress": round(state.stress, 1),
    }

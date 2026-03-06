import json
import time
from pathlib import Path
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
) -> dict:
    """
    시뮬레이션을 실행하고 결과를 반환한다.
    decision_interval > 1이면 배치 모드: N일치 행동을 한 번에 결정한다.
    반환값: 최종 결과 딕셔너리
    """
    state = env.reset()
    agent.reset()
    step_logs = []
    pending_actions: list[str] = []

    for day in range(1, max_days + 1):
        # 배치 모드: 계획이 소진되면 새로 요청
        if not pending_actions:
            observation = state.to_observation()
            remaining = min(decision_interval, max_days - day + 1)
            if decision_interval > 1:
                pending_actions = agent.decide_batch(state, observation, remaining)
            else:
                pending_actions = [agent.decide(state, observation)]

        action = pending_actions.pop(0)

        # 환경 1일 전진
        state, full_observation = env.step(action)

        # 기록
        agent.record(day, action, full_observation)
        step_logs.append({
            "day": day,
            "action": action,
            "position": state.position,
            "salary": state.salary,
            "performance": round(state.performance, 1),
            "boss_favor": round(state.boss_favor, 1),
            "stress": round(state.stress, 1),
            "energy": round(state.energy, 1),
            "events": state.events_today,
        })

        if verbose and day % log_interval == 0:
            print(f"[{agent.name}] Day {day:4d} | {state.position} | "
                  f"성과:{state.performance:.0f} 상사:{state.boss_favor:.0f} "
                  f"스트레스:{state.stress:.0f} | 월급:{state.salary:,}원")

        if not state.is_alive:
            if verbose:
                status = "해고" if state.is_fired else "자진퇴사"
                print(f"[{agent.name}] {day}일차에 {status}됨.")
            break

    result = _build_result(agent.name, state, step_logs)

    # 로그 저장
    Path(log_dir).mkdir(exist_ok=True)
    log_path = Path(log_dir) / f"{agent.name}_{int(time.time())}.json"
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump({"result": result, "steps": step_logs}, f, ensure_ascii=False, indent=2)

    if verbose:
        print(f"\n결과 저장: {log_path}")

    return result


def _build_result(agent_name: str, state, step_logs: list) -> dict:
    survived_days = step_logs[-1]["day"] if step_logs else 0
    return {
        "agent": agent_name,
        "survived_days": survived_days,
        "final_position": state.position,
        "final_salary": state.salary,
        "is_fired": state.is_fired,
        "is_resigned": state.is_resigned,
        "promoted": state.position != "사원",
        "final_performance": round(state.performance, 1),
        "final_boss_favor": round(state.boss_favor, 1),
        "final_stress": round(state.stress, 1),
    }

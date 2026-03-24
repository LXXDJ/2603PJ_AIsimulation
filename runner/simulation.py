import json
import time
from datetime import datetime
from pathlib import Path
from tqdm import tqdm
from environment.company import CompanyEnvironment
from agents.base_agent import BaseAgent
from memory.episodic import Episode


def run_simulation(
    agent: BaseAgent,
    env: CompanyEnvironment,
    max_days: int = 1095,
    log_interval: int = 30,
    decision_interval: int = 1,
    reflection_interval: int = 90,
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
    state = env.reset()                         # 환경 초기화
    agent.reset()                               # 에이전트 초기화
    step_logs = []
    pending_actions: list[str] = []             # LLM이 짜준 행동 계획 리스트
    recent_events: list[tuple[int, str]] = []   # (day, 이벤트명) 누적
    last_reflection_day = 0                     # 마지막 성찰 시점

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
            # 배치 모드: 30일 계획이 소진되면 새로 요청
            if not pending_actions:
                # Reflection: 분기(90일)마다 자기성찰 (llm_reflect가 있을 때만)
                if (hasattr(agent, 'reflect') and agent.llm_reflect
                        and day - last_reflection_day >= reflection_interval
                        and len(agent.history) >= reflection_interval):
                    reflection_text = agent.reflect( # 최근 90일 행동 기록 + 현재 스탯 + 승진 요건을 보내서 전략 조언받기
                        state, window=reflection_interval, promotion_requirements=env.promotion_requirements,
                    )
                    last_reflection_day = day       # day 값으로 last_reflection_day 갱신
                    if reflection_text:             # 텍스트 로그 파일에 성찰 내용 기록
                        txt_file.write(f"  [성찰] Day {day}\n")
                        for line in reflection_text.splitlines():
                            txt_file.write(f"    {line}\n")
                        txt_file.flush()
                        log_file.write(json.dumps({ # JSONL 로그에도 동일하게 기록
                            "type": "reflection", "day": day,
                            "text": reflection_text,
                        }, ensure_ascii=False) + "\n")
                        log_file.flush()            # flush(): 버퍼에 안 남기고 즉시 파일에 쓰라는 뜻

                observation = state.to_observation()    # 현재 스탯 8종을 LLM이 읽을 수 있는 텍스트로 변환
                remaining = min(decision_interval, max_days - day + 1)  # 배치 주기와 남은 일수 중 작은 값으로 요청
                if decision_interval > 1:
                    pending_actions = agent.decide_batch(state, observation, remaining) # LLM을 호출해서 30일치 행동 리스트 받아오기
                else:
                    pending_actions = [agent.decide(state, observation)]

            action = pending_actions.pop(0)         # 리스트 맨 앞에서 하나를 꺼냄 (매일 하나씩 꺼내서 실행)

            # 환경 1일 전진
            state, full_observation = env.step(action)  # full_observation: 오늘 일어난 일의 텍스트 설명

        # 기록
        agent.record(day, action, full_observation)
        _store_episode_if_important(agent, day, action, state, full_observation)
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

        # 승진/이직 분석 로그
        if "승진!" in full_observation:
            analysis_text = _format_promotion_analysis(env)
            txt_file.write(f"[{agent.name}] Day {day} 승진!\n{analysis_text}\n")
            txt_file.flush()
            # JSONL에도 기록
            log_file.write(json.dumps({
                "type": "promotion", "day": day,
                "analysis": env.analyze_promotion(),
            }, ensure_ascii=False) + "\n")
            log_file.flush()

        if not state.is_alive:
            if state.is_fired:
                fire_detail = env.analyze_fire().get("detail", "") if env else ""
                status = "권고사직" if "권고사직" in fire_detail else "해고"
            else:
                status = "자진퇴사"
            analysis_text = _format_exit_analysis(env)
            txt_file.write(f"[{agent.name}] {day}일차에 {status}됨.\n{analysis_text}\n")
            txt_file.flush()
            # JSONL에도 분석 기록
            exit_analysis = env.analyze_fire() if state.is_fired else env.analyze_resignation()
            log_file.write(json.dumps({
                "type": "exit", "day": day, "status": status,
                "analysis": exit_analysis,
            }, ensure_ascii=False) + "\n")
            log_file.flush()
            pbar.set_postfix_str(f"→ {status}", refresh=True)
            break

    result = _build_result(agent.name, state, step_logs, max_days, env)

    # 결과 기록 후 파일 닫기
    log_file.write(json.dumps({"type": "result", **result}, ensure_ascii=False) + "\n")
    log_file.close()
    txt_file.write(f"\n결과 저장: {log_path}\n")
    txt_file.close()

    pbar.close()

    result["log_path"] = str(log_path)
    result["txt_path"] = str(txt_path)

    return result


STAT_LABELS = {
    "skill": "업무능력",
    "performance": "성과",
    "boss_favor": "상사신뢰",
    "reputation": "평판",
}


def _format_exit_analysis(env) -> str:
    """해고/퇴사 시 상세 원인 분석 텍스트를 생성한다."""
    state = env.state
    lines = []

    if state.is_fired:
        info = env.analyze_fire()
        if info["reason"] == "성과_부진":
            lines.append("  원인: 성과 + 상사신뢰 동시 저조")
            for k, v in info["stats"].items():
                label = STAT_LABELS.get(k, k)
                lines.append(f"    {label}: {v['value']} (해고 기준: {v['threshold']} 미만)")
        elif info["reason"] == "승진_미달":
            lines.append(f"  원인: 경력 대비 직급 미달 (요구: {info['target_position']})")
            lines.append(f"  승진 병목:")
            for k, v in info["stats"].items():
                label = STAT_LABELS.get(k, k)
                mark = " ← 미달" if k in info["bottlenecks"] else " ✓"
                lines.append(f"    {label}: {v['value']} / {v['required']}{mark}")

    elif state.is_resigned:
        info = env.analyze_resignation()
        if info["reason"] == "번아웃":
            lines.append(f"  원인: 번아웃 (극한 상태 {info['duration']}일 연속)")
            lines.append(f"    스트레스: {info['stress']}  체력: {info['energy']}")
        elif info["reason"] == "만성_스트레스":
            lines.append(f"  원인: 만성 스트레스 (고스트레스 누적 {info['duration']}일)")
            lines.append(f"    스트레스: {info['stress']}  체력: {info['energy']}")
        elif info["reason"] == "희망퇴직":
            lines.append(f"  원인: 희망퇴직 (경력 {info['career_years']}년차 {info['position']})")
            lines.append(f"    스트레스: {info['stress']}  체력: {info['energy']}")

    # 공통: 최종 스탯 요약
    lines.append(f"  최종 상태: {state.position} / 연봉 {state.salary:,}원")
    lines.append(
        f"    능력:{state.skill:.0f} 성과:{state.performance:.0f} "
        f"상사:{state.boss_favor:.0f} 동료:{state.peer_relation:.0f} "
        f"평판:{state.reputation:.0f} 정치:{state.political_skill:.0f} "
        f"스트레스:{state.stress:.0f} 체력:{state.energy:.0f}"
    )
    return "\n".join(lines)


def _format_promotion_analysis(env) -> str:
    """승진 시 어떤 스탯이 강점이었는지 분석 텍스트."""
    info = env.analyze_promotion()
    lines = ["  승진 심사:"]
    for k, v in info["stats"].items():
        label = STAT_LABELS.get(k, k)
        surplus = v["value"] - v["required"]
        bar = "★" if k == info["strength"] else " "
        lines.append(f"   {bar} {label}: {v['value']} / {v['required']} (+{surplus:.0f})")
    lines.append(f"  강점: {STAT_LABELS.get(info['strength'], info['strength'])}")
    return "\n".join(lines)


def _classify_outcome(state, observation: str) -> str | None:
    """오늘 하루의 결과를 분류한다. 중요하지 않으면 None 반환."""
    obs_lower = observation
    # 승진
    if "승진!" in obs_lower:
        return f"승진: {state.position}"
    # 이직
    if "이직!" in obs_lower:
        return f"이직 (연봉 {state.salary:,}원)"
    # 해고/퇴사
    if state.is_fired:
        return "해고됨"
    if state.is_resigned:
        return "자진퇴사"
    # 랜덤 이벤트 발생
    if state.events_today:
        return f"이벤트: {', '.join(state.events_today)}"
    # 위험 상태 진입 (스트레스 80+ 또는 체력 15 이하)
    if state.stress >= 80 and state.energy <= 15:
        return "번아웃 위기 (스트레스↑ 체력↓)"
    if state.performance < 15 and state.boss_favor < 15:
        return "해고 위기 (성과↓ 상사신뢰↓)"
    # 평범한 날은 저장하지 않음
    return None


def _store_episode_if_important(agent, day: int, action: str, state, observation: str):
    """중요한 날만 에피소딕 메모리에 저장한다."""
    outcome = _classify_outcome(state, observation)
    if outcome is None:
        return
    episode = Episode(
        day=day,
        action=action,
        events=list(state.events_today),
        outcome_summary=outcome,
        state_snapshot={
            "position": state.position,
            "salary": state.salary,
            "skill": round(state.skill, 1),
            "performance": round(state.performance, 1),
            "boss_favor": round(state.boss_favor, 1),
            "stress": round(state.stress, 1),
            "energy": round(state.energy, 1),
        },
    )
    agent.memory.add(episode)


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


def _build_result(agent_name: str, state, step_logs: list, max_days: int,
                   env=None) -> dict:
    survived_days = step_logs[-1]["day"] if step_logs else 0
    # 정년퇴직: MAX_DAYS까지 생존한 경우
    # 부장/이사 → 정년퇴직, 임원 → 현직유지, 차장 이하 → 명예퇴직(사실상 불가능하지만 안전장치)
    reached_end = (survived_days >= max_days and not state.is_fired and not state.is_resigned)
    is_retired = reached_end and state.position in ("부장", "이사")
    result = {
        "agent": agent_name,
        "survived_days": survived_days,
        "max_days": max_days,
        "final_position": state.position,
        "final_salary": state.salary,
        "is_fired": state.is_fired,
        "is_resigned": state.is_resigned,
        "is_retired": is_retired,
        "promoted": state.position != "사원",
        "final_skill": round(state.skill, 1),
        "final_performance": round(state.performance, 1),
        "final_boss_favor": round(state.boss_favor, 1),
        "final_stress": round(state.stress, 1),
    }
    # 종료 원인 분석 첨부
    if env and (state.is_fired or state.is_resigned):
        result["exit_analysis"] = (
            env.analyze_fire() if state.is_fired else env.analyze_resignation()
        )
    elif is_retired:
        years = survived_days // 365
        result["exit_analysis"] = {
            "reason": "정년퇴직",
            "detail": f"경력 {years}년 — {state.position}으로 정년퇴직",
            "position": state.position,
            "career_years": years,
        }
    elif reached_end and state.position == "임원":
        years = survived_days // 365
        result["exit_analysis"] = {
            "reason": "현직유지",
            "detail": f"경력 {years}년 — 임원 현직 유지",
            "position": state.position,
            "career_years": years,
        }
    elif reached_end and state.position_level <= 3:  # 차장 이하로 20년 도달 (안전장치)
        years = survived_days // 365
        is_retired = True
        result["is_retired"] = True
        result["exit_analysis"] = {
            "reason": "명예퇴직",
            "detail": f"경력 {years}년 — {state.position}으로 명예퇴직",
            "position": state.position,
            "career_years": years,
        }
    return result

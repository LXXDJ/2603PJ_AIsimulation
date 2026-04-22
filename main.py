"""
회사원 시뮬레이션 - Deep Agents (LangChain) 버전
실행: python main_deepagent.py

기존 main.py와 동일한 시뮬레이션을 Deep Agents(create_deep_agent)로 구현.
환경(CompanyEnvironment), 성향, 스탯, 이벤트 등은 기존 모듈 그대로 사용.
"""
import os
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from tqdm import tqdm
from dotenv import load_dotenv
from langchain_core.tools import tool

from deepagents import create_deep_agent

from environment.company import CompanyEnvironment
from environment.personality import PERSONALITIES
from environment.state import ACTIONS
from evaluation.metrics import compare_agents
from memory.episodic import Episode, EpisodicMemory


# ── 실험 설정 ──────────────────────────────────────────
EXPERIMENT_SEED    = 42     # 모든 에이전트가 동일한 이벤트 시퀀스를 경험 (랜덤 이벤트 순서를 고정하는 값) : 값 자체는 아무 숫자나 상관없고, 바꾸면 이벤트 순서가 달라짐
MAX_DAYS           = 7300   # 시뮬레이션 기간 (일) — 20년
LOG_INTERVAL       = 30     # 콘솔 출력 주기 (일)
DECISION_INTERVAL  = 30     # 배치 결정 주기 (일) — 한달치 한 번에 결정

# ── Reflection 설정 ────────────────────────────────────
USE_REFLECTION     = True              # 자기성찰 기능 on/off
REFLECTION_INTERVAL = 90                # 성찰 주기 (일) — 분기마다
MODEL_DECISION     = "gpt-4.1-mini"     # 배치 결정 + 히스토리 압축용 (저렴/빠름)
MODEL_REFLECTION   = "gpt-4.1"          # Reflection 전용 (고품질)

# ── 비교할 성향 목록 ────────────────────────────────────
# 사용 가능한 성향: "균형형", "성과형", "사교형", "정치형", "워라밸형"
ACTIVE_PERSONALITIES = ["균형형", "성과형", "사교형", "정치형", "워라밸형"]

# ── Reflection on/off 비교 실험 설정 ────────────────────
AB_COMPARE = ["정치형"]


# ── Reflection 프롬프트 (기존과 동일) ──────────────────
REFLECTION_PROMPT = """
당신은 회사원 시뮬레이션의 전략 컨설턴트입니다.
에이전트가 지난 {window}일간 실행한 행동과 결과를 분석하고, 생존과 승진을 위한 구체적 행동 배분을 처방하세요.

[!] 중요: 성향에 맞는 행동만 반복하면 특정 스탯만 올라가고 승진 요건을 못 채워 해고됩니다.
승진에 필요한 스탯(업무능력, 성과, 상사신뢰, 평판) 중 부족한 것을 집중적으로 올리는 행동을 처방하세요.
성향과 다른 행동이라도 생존을 위해 반드시 필요합니다.

{personality_section}

[ 승진 요건 vs 현재 스탯 ]
{promotion_gap}

[ 해고/퇴직 조건 ]
- 성과 부진: 성과 < 20 AND 상사신뢰 < 20 → 즉시 해고
- 승진 미달: 경력 5년차에 대리 미만, 8년차에 과장 미만, 15년차에 부장 미만 → 권고사직/명예퇴직
- 희망퇴직: 경력 12년+ 시 직급·스트레스·성향에 따라 자발적 퇴직 가능성
  [!] 스트레스가 높고 체력이 낮으면 희망퇴직 확률이 크게 상승한다!
  스트레스 80+ → 퇴직확률 +15%, 체력 20 이하 → +10%
  반대로 스트레스 20 이하, 체력 80 이상이면 퇴직 욕구가 크게 감소한다.
- 번아웃: 스트레스 90+ AND 체력 10 이하 30일 지속 → 자진퇴사

[!][!] 체력/스트레스 관리 필수 원칙 [!][!]
- 체력 30 이하 또는 스트레스 70 이상이면 반드시 휴가를 처방에 포함하세요.
- 야근은 스트레스를 급격히 올리고 체력을 깎으므로, 스트레스 50 이상일 때는 절대 처방하지 마세요.
- 장기 생존이 승진보다 중요합니다. 죽으면 승진도 없습니다.

[ 행동별 효과 참고 ]
- 프로젝트에 집중한다: 업무능력↑ 성과↑ (승진 핵심)
- 야근한다: 업무능력↑ 성과↑↑ (단, 스트레스↑↑ 체력↓↓ — 남용 금지!)
- 상사와 점심을 먹는다: 상사신뢰↑ (승진 핵심)
- 동료를 도와준다: 동료관계↑ 평판↑
- 자기계발을 한다: 업무능력↑
- 정치적으로 행동한다: 정치능력↑ 상사신뢰↑ (단, 평판에 도움 안됨)
- 휴가를 쓴다: 스트레스↓↓ 체력↑↑ (생존 핵심!)

[ 지난 {window}일 행동 기록 ]
{history_summary}

[ 현재 상태 ]
{current_state}

[ 에피소딕 메모리 (주요 과거 경험) ]
{memory_text}

다음 형식으로 정확히 응답하세요:

평가: (지난 기간 행동 비율과 스탯 변화를 수치로 평가. 어떤 행동을 너무 많이/적게 했는지 지적)
문제점: (승진 요건 대비 가장 부족한 스탯을 구체적 수치와 함께 지적. 해고 데드라인까지 남은 시간도 언급)
처방: 다음 90일 행동 배분 (30일 기준):
- (행동명) X일 (이유)
- (행동명) Y일 (이유)
- (행동명) Z일 (이유)
합계 30일. 반드시 부족한 스탯을 올리는 행동을 최우선으로 배분하세요.

[!] 마지막에 반드시 아래 JSON 블록을 출력하세요. 이 JSON이 코드에서 직접 파싱되어 행동 계획을 강제 보정합니다.
행동명은 반드시 가능한 행동 목록에 있는 이름을 정확히 사용하세요.
값은 30일 기준 최소 일수입니다. 합계가 정확히 30이어야 합니다.

```json
{{"야근한다": 0, "상사와 점심을 먹는다": 0, "동료를 도와준다": 0, "정치적으로 행동한다": 0, "이직 준비를 한다": 0, "휴가를 쓴다": 0, "자기계발을 한다": 0, "프로젝트에 집중한다": 0}}
```
""".strip()


# ── 배치 결정 시스템 프롬프트 (기존과 동일) ────────────
BATCH_SYSTEM_PROMPT = """
당신은 회사원 시뮬레이션 에이전트입니다.
목표: 20년(7300일) 안에 최대한 높은 직급과 연봉을 달성하고 해고되지 않는다.
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

{memory_section}
현재 상태를 보고 앞으로 {n}일간의 행동 계획을 세우세요.

[!] 핵심 원칙: "최우선 전략 지침"이 위에 있다면, 그 처방된 행동 배분을 반드시 따르세요.
성향에 맞는 행동만 반복하면 특정 스탯만 편중되어 승진 요건을 못 채우고 해고됩니다.
처방된 비율대로 행동을 배분하되, 스트레스가 80 이상이면 휴가를 우선 배치하세요.

다음 형식으로 정확히 응답하세요:

Thought: (현재 상황 판단 — 특히 전략 지침에서 지적한 부족 스탯을 어떻게 올릴지)
Day 1: (행동)
Day 2: (행동)
...
Day {n}: (행동)

가능한 행동 목록 (정확히 그대로 출력):
{actions}
""".strip()


def _extract_text(message) -> str:
    """Deep Agent 응답 메시지에서 텍스트를 추출한다.
    content가 str일 수도 있고, list[dict]일 수도 있음."""
    content = message.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [block["text"] for block in content if isinstance(block, dict) and "text" in block]
        return "\n".join(parts).strip()
    return str(content).strip()


def _actions_list() -> str:
    return "\n".join(f"- {a}" for a in ACTIONS)


def _parse_action(text: str) -> str:
    for action in ACTIONS:
        if action in text:
            return action
    return "프로젝트에 집중한다"


def _parse_batch(text: str, n: int) -> list[str]:
    actions = []
    for i in range(1, n + 1):
        found = None
        for line in text.splitlines():
            if line.strip().startswith(f"Day {i}:"):
                found = _parse_action(line)
                break
        actions.append(found or "프로젝트에 집중한다")
    return actions


import re as _re


def _parse_quota(reflection_text: str) -> dict[str, int] | None:
    """Reflection 응답에서 JSON 처방 블록을 파싱하여 {행동명: 최소일수} dict로 반환.
    파싱 실패 시 None을 반환하여 기존 텍스트 방식으로 폴백."""
    # ```json ... ``` 블록 추출
    m = _re.search(r"```json\s*(\{.*?\})\s*```", reflection_text, _re.DOTALL)
    if not m:
        # 코드블록 없이 bare JSON인 경우도 시도
        m = _re.search(r'(\{[^{}]*"[^{}]*\})', reflection_text, _re.DOTALL)
    if not m:
        return None
    try:
        quota = json.loads(m.group(1))
    except json.JSONDecodeError:
        return None
    # 유효성 검증: 모든 키가 ACTIONS에 있는지, 값이 정수인지
    valid = {}
    for action in ACTIONS:
        val = quota.get(action, 0)
        valid[action] = max(0, int(val))
    # 합계가 30이 아니면 비례 보정
    total = sum(valid.values())
    if total == 0:
        return None
    if total != 30:
        factor = 30 / total
        adjusted = {k: max(0, round(v * factor)) for k, v in valid.items()}
        # 반올림 오차 보정 — 가장 큰 항목에서 조정
        diff = 30 - sum(adjusted.values())
        if diff != 0:
            max_key = max(adjusted, key=adjusted.get)
            adjusted[max_key] += diff
        valid = adjusted
    return valid


def _enforce_quota(actions: list[str], quota: dict[str, int]) -> list[str]:
    """LLM이 생성한 행동 계획(actions)을 quota 기준으로 강제 보정.
    quota에 명시된 최소 일수를 반드시 충족시킨다."""
    from collections import Counter
    n = len(actions)
    current = Counter(actions)

    # 부족한 행동 파악
    deficits: dict[str, int] = {}
    for action_name, min_days in quota.items():
        shortage = min_days - current.get(action_name, 0)
        if shortage > 0:
            deficits[action_name] = shortage

    if not deficits:
        return actions  # 이미 충족

    # 초과 배정된 행동 파악 (교체 후보)
    # quota보다 많이 배정된 행동에서 빼온다 (단, 휴가는 보호)
    excess_indices: list[int] = []
    excess_count: dict[str, int] = {}
    for action_name in ACTIONS:
        if action_name == "휴가를 쓴다":
            continue  # 휴가는 LLM이 더 넣은 걸 허용 (생존 보호)
        surplus = current.get(action_name, 0) - quota.get(action_name, 0)
        if surplus > 0:
            excess_count[action_name] = surplus

    # 초과분이 큰 행동부터 교체 후보 인덱스 수집 (뒤에서부터)
    for idx in reversed(range(n)):
        act = actions[idx]
        if act == "휴가를 쓴다":
            continue  # 휴가 슬롯은 교체 대상에서 제외
        if excess_count.get(act, 0) > 0:
            excess_indices.append(idx)
            excess_count[act] -= 1

    # 부족한 행동을 교체
    result = list(actions)
    replace_idx = 0
    for action_name, shortage in sorted(deficits.items(), key=lambda x: -x[1]):
        for _ in range(shortage):
            if replace_idx < len(excess_indices):
                result[excess_indices[replace_idx]] = action_name
                replace_idx += 1
            # 교체 후보가 부족하면 그대로 둠 (최선의 보정)

    return result


def _build_promotion_gap(state, requirements: dict | None) -> str:
    if not requirements:
        return "승진 요건 정보 없음"
    pos = state.position
    req = requirements.get(pos)
    if not req:
        return f"현재 직급({pos})은 최고 직급이거나 승진 요건이 없습니다."
    stat_map = {
        "skill": ("업무능력", state.skill),
        "performance": ("성과", state.performance),
        "boss_favor": ("상사신뢰", state.boss_favor),
        "reputation": ("평판", state.reputation),
    }
    lines = [f"현재 직급: {pos} → 다음 승진 요건:"]
    for key, (label, current) in stat_map.items():
        required = req.get(key, 0)
        gap = required - current
        status = f"부족 {gap:.0f}" if gap > 0 else "충족 ✓"
        lines.append(f"  {label}: {current:.0f} / {required} ({status})")
    min_days = req.get("min_days", 0)
    days_left = max(0, min_days - state.day)
    if days_left > 0:
        lines.append(f"  최소 근무일: {state.day}일 / {min_days}일 (잔여 {days_left}일)")
    else:
        lines.append(f"  최소 근무일: 충족 ✓")
    career_days = state.day
    if career_days < 5 * 365:
        remaining = 5 * 365 - career_days
        lines.append(f"\n[!] 경력 5년 해고심사까지 {remaining}일 남음 — 그때까지 대리 이상 필수!")
    elif career_days < 8 * 365:
        remaining = 8 * 365 - career_days
        lines.append(f"\n[!] 경력 8년 해고심사까지 {remaining}일 남음 — 그때까지 과장 이상 필수!")
    elif career_days < 15 * 365:
        remaining = 15 * 365 - career_days
        lines.append(f"\n[!] 경력 15년 명예퇴직 심사까지 {remaining}일 남음 — 그때까지 부장 이상 필수!")
    return "\n".join(lines)


def _build_memory_section(memory: EpisodicMemory, reflection: str,
                          history: list[dict], llm_compress) -> str:
    """에피소딕 메모리 + 히스토리 압축 + Reflection을 프롬프트용 텍스트로 조합."""
    parts = []
    if reflection:
        parts.append(
            f"[!][!][!] 최우선 전략 지침 (자기성찰 결과) [!][!][!]\n"
            f"아래 처방된 행동 배분을 반드시 따르세요. 성향과 다르더라도 생존을 위해 필수입니다.\n"
            f"{reflection}\n"
            f"[!] 위 처방을 무시하고 성향대로만 행동하면 해고됩니다."
        )
    memory_text = memory.to_text(n=10)
    if memory_text != "기억 없음":
        parts.append(f"[ 과거 주요 경험 ]\n{memory_text}")
    if len(history) >= 30 and llm_compress:
        from memory.compressor import compress_history
        summary = compress_history(history, llm_compress, window=30)
        if summary:
            parts.append(f"[ 최근 행동 패턴 요약 ]\n{summary}")
    if not parts:
        return ""
    return "\n\n".join(parts)


def _classify_outcome(state, observation: str) -> str | None:
    if "승진!" in observation:
        return f"승진: {state.position}"
    if "이직!" in observation:
        return f"이직 (연봉 {state.salary:,}원)"
    if state.is_fired:
        return "해고됨"
    if state.is_resigned:
        return "자진퇴사"
    if state.events_today:
        return f"이벤트: {', '.join(state.events_today)}"
    if state.stress >= 80 and state.energy <= 15:
        return "번아웃 위기 (스트레스↑ 체력↓)"
    if state.performance < 15 and state.boss_favor < 15:
        return "해고 위기 (성과↓ 상사신뢰↓)"
    return None


def _store_episode_if_important(memory: EpisodicMemory, day: int, action: str, state, observation: str):
    outcome = _classify_outcome(state, observation)
    if outcome is None:
        return
    episode = Episode(
        day=day, action=action, events=list(state.events_today),
        outcome_summary=outcome,
        state_snapshot={
            "position": state.position, "salary": state.salary,
            "skill": round(state.skill, 1), "performance": round(state.performance, 1),
            "boss_favor": round(state.boss_favor, 1),
            "stress": round(state.stress, 1), "energy": round(state.energy, 1),
        },
    )
    memory.add(episode)


def _run_one(personality_name: str, tqdm_position: int = 0,
             reflection_override: bool | None = None, name_suffix: str = "") -> dict:
    """단일 에이전트 시뮬레이션 실행 (Deep Agents 버전)."""
    use_reflect = reflection_override if reflection_override is not None else USE_REFLECTION
    personality = PERSONALITIES[personality_name]
    agent_name = f"DeepAgent_{personality_name}"
    if name_suffix:
        agent_name = f"{agent_name}_{name_suffix}"

    personality_section = f"\n당신의 성향: {personality.name}\n{personality.description}"
    batch_template = BATCH_SYSTEM_PROMPT.replace("{personality_section}", personality_section)

    # ── Deep Agent 생성 (배치 결정용) ──
    decision_agent = create_deep_agent(
        model=f"openai:{MODEL_DECISION}",
        tools=[],  # 커스텀 Tool 없음 — 프롬프트 기반 배치 결정
        system_prompt=batch_template,
        name=f"decision_{personality_name}",
    )

    # ── Reflection용 Deep Agent (고급 모델) ──
    reflection_agent = None
    if use_reflect:
        reflection_agent = create_deep_agent(
            model=f"openai:{MODEL_REFLECTION}",
            tools=[],
            system_prompt="당신은 회사원 시뮬레이션의 전략 컨설턴트입니다.",
            name=f"reflection_{personality_name}",
        )

    # ── 환경 생성 (기존과 동일) ──
    env = CompanyEnvironment(seed=EXPERIMENT_SEED, personality=personality, max_days=MAX_DAYS)

    # ── 시뮬레이션 루프 (기존 runner/simulation.py와 동일한 로직) ──
    state = env.reset()
    memory = EpisodicMemory(capacity=50)
    history: list[dict] = []
    step_logs = []
    pending_actions: list[str] = []
    recent_events: list[tuple[int, str]] = []
    last_reflection_day = 0
    reflection_text = ""
    action_quota: dict[str, int] | None = None  # Reflection이 처방한 행동 배분 (구조적 강제)

    # LLM 압축용 클라이언트 (기존 모듈 재사용)
    from llm.client import LLMClient
    llm_compress = LLMClient(model=MODEL_DECISION)

    # 로그 파일
    Path("logs").mkdir(exist_ok=True)
    timestamp = datetime.now().strftime('%y%m%d_%H%M%S')
    log_path = Path("logs") / f"{timestamp}_{agent_name}.jsonl"
    txt_path = Path("logs") / f"{timestamp}_{agent_name}.txt"
    log_file = open(log_path, "w", encoding="utf-8")
    txt_file = open(txt_path, "w", encoding="utf-8")

    log_file.write(json.dumps({"type": "meta", "agent": agent_name,
                                "started_at": datetime.now().isoformat()}, ensure_ascii=False) + "\n")
    log_file.flush()
    txt_file.write(f"{'='*60}\n에이전트: {agent_name}  (시작: {datetime.now().isoformat()})\n{'='*60}\n")
    txt_file.flush()

    pbar = tqdm(
        total=MAX_DAYS, desc=f"{agent_name}", position=tqdm_position,
        leave=True, unit="일",
        bar_format="{desc:<20} {percentage:3.0f}% |{bar:25}| {n_fmt}/{total_fmt}일  {postfix}",
    )

    for day in range(1, MAX_DAYS + 1):
        is_weekend = (day - 1) % 7 >= 5

        if is_weekend:
            state, full_observation, action = env.step_weekend()
        else:
            if not pending_actions:
                # Reflection (90일마다)
                if (reflection_agent
                        and day - last_reflection_day >= REFLECTION_INTERVAL
                        and len(history) >= REFLECTION_INTERVAL):

                    recent = history[-REFLECTION_INTERVAL:]
                    history_lines = []
                    for h in recent:
                        events_part = ""
                        if "이벤트" in h.get("observation", "") or "승진" in h.get("observation", ""):
                            events_part = f" → {h['observation'][:60]}"
                        history_lines.append(f"Day {h['day']}: {h['action']}{events_part}")
                    history_summary = "\n".join(history_lines)

                    promotion_gap = _build_promotion_gap(state, env.promotion_requirements)
                    memory_text_for_reflect = memory.to_text(n=5)
                    personality_section_reflect = f"에이전트 성향: {personality.name}\n{personality.description}"

                    reflect_prompt = REFLECTION_PROMPT.format(
                        window=REFLECTION_INTERVAL,
                        personality_section=personality_section_reflect,
                        history_summary=history_summary,
                        current_state=state.to_observation(),
                        memory_text=memory_text_for_reflect,
                        promotion_gap=promotion_gap,
                    )

                    # Deep Agent invoke로 Reflection 실행
                    reflect_result = reflection_agent.invoke(
                        {"messages": [
                            {"role": "system", "content": reflect_prompt},
                            {"role": "user", "content": "성찰을 시작하세요."},
                        ]},
                    )
                    # 마지막 AI 메시지에서 텍스트 추출
                    reflection_text = _extract_text(reflect_result["messages"][-1])
                    last_reflection_day = day

                    if reflection_text:
                        # JSON 처방 파싱 (구조적 강제)
                        action_quota = _parse_quota(reflection_text)

                        txt_file.write(f"  [성찰] Day {day}\n")
                        for line in reflection_text.splitlines():
                            txt_file.write(f"    {line}\n")
                        if action_quota:
                            txt_file.write(f"  [처방 quota] {action_quota}\n")
                        else:
                            txt_file.write(f"  [처방 quota] 파싱 실패 — 텍스트 방식 폴백\n")
                        txt_file.flush()
                        log_file.write(json.dumps({
                            "type": "reflection", "day": day, "text": reflection_text,
                            "quota": action_quota,
                        }, ensure_ascii=False) + "\n")
                        log_file.flush()

                # 배치 결정 (30일치)
                observation = state.to_observation()
                remaining = min(DECISION_INTERVAL, MAX_DAYS - day + 1)
                memory_section = _build_memory_section(memory, reflection_text, history, llm_compress)
                system_prompt = batch_template.format(
                    n=remaining, actions=_actions_list(), memory_section=memory_section,
                )

                # Deep Agent invoke로 배치 결정 실행
                batch_result = decision_agent.invoke(
                    {"messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": observation},
                    ]},
                )
                response_text = _extract_text(batch_result["messages"][-1])
                pending_actions = _parse_batch(response_text, remaining)

                # 구조적 강제 보정: quota가 있으면 LLM 계획을 강제 수정
                # 단, 위험 상태(스트레스 70+/체력 30 이하)에서는 스킵 — 생존 우선
                if action_quota and state.stress < 70 and state.energy > 30:
                    pending_actions = _enforce_quota(pending_actions, action_quota)

            action = pending_actions.pop(0)
            state, full_observation = env.step(action)

        # 기록
        history.append({"day": day, "action": action, "observation": full_observation})
        _store_episode_if_important(memory, day, action, state, full_observation)
        step = {
            "type": "step", "day": day, "action": action,
            "position": state.position, "salary": state.salary,
            "skill": round(state.skill, 1), "performance": round(state.performance, 1),
            "boss_favor": round(state.boss_favor, 1), "peer_relation": round(state.peer_relation, 1),
            "reputation": round(state.reputation, 1), "political_skill": round(state.political_skill, 1),
            "stress": round(state.stress, 1), "energy": round(state.energy, 1),
            "events": state.events_today, "job_changes": state.job_changes,
        }
        step_logs.append(step)
        log_file.write(json.dumps(step, ensure_ascii=False) + "\n")
        log_file.flush()

        for evt in state.events_today:
            recent_events.append((day, evt))

        pbar.update(1)

        if day % LOG_INTERVAL == 0:
            leave_left = state.annual_leave - state.leaves_used_this_year
            job_str = f"  이직:{state.job_changes}회" if state.job_changes > 0 else ""
            detail = (
                f"[{agent_name}] Day {day:4d}  {state.position}  연봉: {state.salary:,}원 - "
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
            if state.is_fired:
                fire_detail = env.analyze_fire().get("detail", "")
                status = "권고사직" if "권고사직" in fire_detail else "해고"
            else:
                status = "자진퇴사"
            txt_file.write(f"[{agent_name}] {day}일차에 {status}됨.\n")
            txt_file.flush()
            exit_analysis = env.analyze_fire() if state.is_fired else env.analyze_resignation()
            log_file.write(json.dumps({
                "type": "exit", "day": day, "status": status, "analysis": exit_analysis,
            }, ensure_ascii=False) + "\n")
            log_file.flush()
            pbar.set_postfix_str(f"→ {status}", refresh=True)
            break

    # 결과 빌드
    survived_days = step_logs[-1]["day"] if step_logs else 0
    reached_end = (survived_days >= MAX_DAYS and not state.is_fired and not state.is_resigned)
    is_retired = reached_end and state.position in ("부장", "이사")
    result = {
        "agent": agent_name, "survived_days": survived_days, "max_days": MAX_DAYS,
        "final_position": state.position, "final_salary": state.salary,
        "is_fired": state.is_fired, "is_resigned": state.is_resigned,
        "is_retired": is_retired, "promoted": state.position != "사원",
        "final_skill": round(state.skill, 1), "final_performance": round(state.performance, 1),
        "final_boss_favor": round(state.boss_favor, 1), "final_stress": round(state.stress, 1),
    }
    if state.is_fired or state.is_resigned:
        result["exit_analysis"] = env.analyze_fire() if state.is_fired else env.analyze_resignation()
    elif is_retired:
        years = survived_days // 365
        result["exit_analysis"] = {
            "reason": "정년퇴직", "detail": f"경력 {years}년 — {state.position}으로 정년퇴직",
            "position": state.position, "career_years": years,
        }
    elif reached_end and state.position == "임원":
        years = survived_days // 365
        result["exit_analysis"] = {
            "reason": "현직유지", "detail": f"경력 {years}년 — 임원 현직 유지",
            "position": state.position, "career_years": years,
        }

    log_file.write(json.dumps({"type": "result", **result}, ensure_ascii=False) + "\n")
    log_file.close()
    txt_file.write(f"\n결과 저장: {log_path}\n")
    txt_file.close()
    pbar.close()

    result["log_path"] = str(log_path)
    result["txt_path"] = str(txt_path)
    return result


def main():
    load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY 환경변수를 설정하세요.")

    tqdm.set_lock(threading.RLock())

    jobs: list[dict] = []
    if AB_COMPARE and USE_REFLECTION:
        for p in AB_COMPARE:
            jobs.append({"key": f"{p}_Reflect",
                         "args": (p,), "kwargs": {"reflection_override": True, "name_suffix": "Reflect"}})
            jobs.append({"key": f"{p}_NoReflect",
                         "args": (p,), "kwargs": {"reflection_override": False, "name_suffix": "NoReflect"}})
    else:
        for p in ACTIVE_PERSONALITIES:
            jobs.append({"key": p, "args": (p,), "kwargs": {}})

    results_map: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        future_to_key = {}
        for i, job in enumerate(jobs):
            future = executor.submit(_run_one, *job["args"], tqdm_position=i, **job["kwargs"])
            future_to_key[future] = job["key"]
        for future in as_completed(future_to_key):
            key = future_to_key[future]
            try:
                results_map[key] = future.result()
            except Exception as e:
                print(f"[오류] {key} 실행 실패: {e}")

    results = [results_map[job["key"]] for job in jobs if job["key"] in results_map]

    print("\n" * len(jobs))
    print(f"{'='*60}")
    print("최종 비교 결과 (Deep Agents 버전)")
    print(f"{'='*60}")
    ranking = compare_agents(results)
    agent_results = {r["agent"]: r for r in results}
    for m in ranking:
        r = agent_results.get(m["agent"], {})
        exit_reason = (r.get("exit_analysis") or {}).get("reason", "")
        if m["fired"]:
            detail = (r.get("exit_analysis") or {}).get("detail", "")
            end_status = "권고사직" if "권고사직" in detail else "해고"
        elif exit_reason == "희망퇴직":
            end_status = "희망퇴직"
        elif r.get("is_resigned"):
            end_status = "퇴사"
        elif r.get("is_retired"):
            end_status = "정년퇴직"
        else:
            end_status = "생존"
        print(
            f"[{m['rank']}위] {m['agent']} | 총점: {m['total_score']:.1f} | "
            f"{m['final_position']} | {m['final_salary']:,}원 | "
            f"생존: {m['survived_days']}일 | {end_status}"
        )

    if globals().get("AUTO_VISUALIZE", True):
        from pathlib import Path
        from visualize_plotly import draw_comparison_html
        log_paths = [Path(r["log_path"]) for r in results if "log_path" in r]
        if log_paths:
            draw_comparison_html(log_paths, show=False)


if __name__ == "__main__":
    main()

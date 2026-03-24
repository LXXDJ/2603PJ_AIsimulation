"""
회사원 시뮬레이션 - 딥 에이전트 아키텍처 비교 실험
실행: python main.py
"""
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from dotenv import load_dotenv
from environment.company import CompanyEnvironment
from environment.personality import PERSONALITIES
from agents.react_agent import ReActAgent
from llm.client import LLMClient
from runner.simulation import run_simulation
from evaluation.metrics import compare_agents


# ── 실험 설정 ──────────────────────────────────────────
EXPERIMENT_SEED    = 42     # 모든 에이전트가 동일한 이벤트 시퀀스를 경험 (랜덤 이벤트 순서를 고정하는 값) : 값 자체는 아무 숫자나 상관없고, 바꾸면 이벤트 순서가 달라짐
MAX_DAYS           = 7300   # 시뮬레이션 최대 기간 (일) — 20년
LOG_INTERVAL       = 30     # 콘솔 출력 주기 (일) — 분기마다
DECISION_INTERVAL  = 30     # 배치 결정 주기 (일) — 한달치 한 번에 결정

# ── Reflection 설정 ────────────────────────────────────
USE_REFLECTION     = False              # 자기성찰 기능 on/off
REFLECTION_INTERVAL = 90                # 성찰 주기 (일) — 분기마다
MODEL_DECISION     = "gpt-4.1-mini"     # 배치 결정 + 히스토리 압축용 (저렴/빠름)
MODEL_REFLECTION   = "gpt-4.1"          # Reflection 전용 (고품질)

# ── 비교할 성향 목록 ────────────────────────────────────
# 사용 가능한 성향: "균형형", "성과형", "사교형", "정치형", "워라밸형"
ACTIVE_PERSONALITIES = ["균형형", "성과형", "사교형", "정치형", "워라밸형"]

# ── A/B 비교 실험 설정 ────────────────────────────────────
# 특정 성향의 Reflection on/off를 나란히 비교하려면 여기에 성향명 추가
# 예: ["정치형"] → 정치형(Reflection) vs 정치형(NoReflect) 동시 실행
AB_COMPARE = ["정치형"]
# ────────────────────────────────────────────────────────


def _run_one(personality_name: str, tqdm_position: int = 0,
             reflection_override: bool | None = None, name_suffix: str = "") -> dict:
    """단일 에이전트 시뮬레이션 실행 (스레드별 독립 실행)."""
    use_reflect = reflection_override if reflection_override is not None else USE_REFLECTION
    llm = LLMClient(model=MODEL_DECISION)
    llm_reflect = LLMClient(model=MODEL_REFLECTION) if use_reflect else None
    agent = ReActAgent(llm=llm, personality=PERSONALITIES[personality_name], llm_reflect=llm_reflect)
    # A/B 비교 시 이름 구분
    if name_suffix:
        agent.name = f"{agent.name}_{name_suffix}"
    env = CompanyEnvironment(seed=EXPERIMENT_SEED, personality=agent.personality, max_days=MAX_DAYS)

    return run_simulation(
        agent=agent, env=env,
        max_days=MAX_DAYS, log_interval=LOG_INTERVAL,
        decision_interval=DECISION_INTERVAL,
        reflection_interval=REFLECTION_INTERVAL, verbose=True,
        tqdm_position=tqdm_position,
    )


def main():
    load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY 환경변수를 설정하세요.")

    # tqdm 멀티스레드 커서 충돌 방지
    tqdm.set_lock(threading.RLock())

    # 실행 작업 목록 구성
    jobs: list[dict] = []  # {"key": 결과 키, "args": _run_one 인자}

    if AB_COMPARE and USE_REFLECTION:
        # A/B 비교 모드: Reflection on 상태에서만 작동, 지정된 성향만 Reflection on/off 나란히
        for p in AB_COMPARE:
            jobs.append({"key": f"{p}_Reflect",
                         "args": (p,), "kwargs": {"reflection_override": True, "name_suffix": "Reflect"}})
            jobs.append({"key": f"{p}_NoReflect",
                         "args": (p,), "kwargs": {"reflection_override": False, "name_suffix": "NoReflect"}})
    else:
        # 일반 모드: 전체 성향 실행
        for p in ACTIVE_PERSONALITIES:
            jobs.append({"key": p, "args": (p,), "kwargs": {}})

    # 병렬 실행
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

    # 원래 순서 복원
    results = [results_map[job["key"]] for job in jobs if job["key"] in results_map]

    # tqdm 멀티스레드 잔여 커서 정리
    print("\n" * len(jobs))
    print(f"{'='*60}")
    print("최종 비교 결과")
    print(f"{'='*60}")
    ranking = compare_agents(results)
    # agent name → result 매핑
    agent_results = {r["agent"]: r for r in results}
    for m in ranking:
        r = agent_results.get(m["agent"], {})
        exit_reason = (r.get("exit_analysis") or {}).get("reason", "")
        if m["fired"]:
            detail = (r.get("exit_analysis") or {}).get("detail", "")
            if "권고사직" in detail:
                end_status = "권고사직"
            else:
                end_status = "해고"
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

    # 비교 차트 HTML 생성 (브라우저 자동 열기 없음)
    if globals().get("AUTO_VISUALIZE", True):
        from pathlib import Path
        from visualize_plotly import draw_comparison_html
        log_paths = [Path(r["log_path"]) for r in results if "log_path" in r]
        if log_paths:
            draw_comparison_html(log_paths, show=False)


if __name__ == "__main__":
    main()

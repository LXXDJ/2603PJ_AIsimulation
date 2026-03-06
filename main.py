"""
회사원 시뮬레이션 - 딥 에이전트 아키텍처 비교 실험
실행: python main.py
"""
import os
from dotenv import load_dotenv
from environment.company import CompanyEnvironment
from agents.react_agent import ReActAgent
from llm.client import LLMClient
from runner.simulation import run_simulation
from evaluation.metrics import compare_agents


# ── 실험 설정 ──────────────────────────────────────────
EXPERIMENT_SEED    = 42   # 모든 에이전트가 동일한 이벤트 시퀀스를 경험 (랜덤 이벤트 순서를 고정하는 값) : 값 자체는 아무 숫자나 상관없고, 바꾸면 이벤트 순서가 달라짐
MAX_DAYS           = 365  # 시뮬레이션 최대 기간 (일) — 기본 3년(1095)
LOG_INTERVAL       = 30    # 콘솔 출력 주기 (일)
DECISION_INTERVAL  = 7     # 배치 결정 주기 (일) — 1이면 매일 호출, 7이면 7일치 한 번에 결정
# ────────────────────────────────────────────────────────


def main():
    load_dotenv()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise EnvironmentError("OPENAI_API_KEY 환경변수를 설정하세요.")

    llm = LLMClient()

    # 현재는 ReAct 에이전트만 구현됨
    # 추후: PlannnerAgent, ReflectionAgent, MemoryAgent 추가
    agents = [
        ReActAgent(llm=llm),
    ]

    results = []
    for agent in agents:
        # 에이전트마다 동일한 seed로 새 환경 생성 → 공정한 비교
        env = CompanyEnvironment(seed=EXPERIMENT_SEED)
        print(f"\n{'='*50}")
        print(f"에이전트: {agent.name} 시뮬레이션 시작 (seed={EXPERIMENT_SEED})")
        print(f"{'='*50}")
        result = run_simulation(agent=agent, env=env, max_days=MAX_DAYS, log_interval=LOG_INTERVAL, decision_interval=DECISION_INTERVAL, verbose=True)
        results.append(result)

    print(f"\n{'='*50}")
    print("최종 비교 결과")
    print(f"{'='*50}")
    ranking = compare_agents(results)
    for m in ranking:
        print(
            f"[{m['rank']}위] {m['agent']} | 총점: {m['total_score']:.1f} | "
            f"{m['final_position']} | {m['final_salary']:,}원 | "
            f"생존: {m['survived_days']}일 | 해고: {m['fired']}"
        )


if __name__ == "__main__":
    main()

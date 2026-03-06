from environment.state import POSITIONS


def compute_metrics(result: dict) -> dict:
    """단일 시뮬레이션 결과에서 지표를 계산한다."""
    survival_rate = result["survived_days"] / 1095
    position_score = POSITIONS.index(result["final_position"]) / (len(POSITIONS) - 1)
    salary_score = min(result["final_salary"] / 8_000_000, 1.0)  # 800만 기준 정규화

    # 종합 점수 (0-100)
    score = (
        survival_rate * 40
        + position_score * 35
        + salary_score * 25
    ) * 100

    return {
        "agent": result["agent"],
        "survival_rate": round(survival_rate, 3),
        "position_score": round(position_score, 3),
        "salary_score": round(salary_score, 3),
        "total_score": round(score, 2),
        "survived_days": result["survived_days"],
        "final_position": result["final_position"],
        "final_salary": result["final_salary"],
        "fired": result["is_fired"],
    }


def compare_agents(results: list[dict]) -> list[dict]:
    """여러 에이전트 결과를 지표화하고 순위를 매긴다."""
    metrics = [compute_metrics(r) for r in results]
    metrics.sort(key=lambda x: x["total_score"], reverse=True)
    for rank, m in enumerate(metrics, 1):
        m["rank"] = rank
    return metrics

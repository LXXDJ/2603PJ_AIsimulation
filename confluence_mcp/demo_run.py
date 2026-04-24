"""[용도] 5성향 1년 시뮬레이션 데모 — code-driven Reflection + LLM-driven Profile 동시 실행.
       Confluence(MCP - AI Simulation 페이지)에 다음 두 종류 페이지가 생성된다:
         - Profile_DeepAgent_{성향}_{run_id}        → LLM-driven (성향당 1장, 시작 시 1회)
         - Reflection_DeepAgent_{성향}_Day{N}_{run_id} → code-driven (성향당 ~2장, Reflection 트리거)
       총 ≈ 5 + 10 = 15장 페이지.
[언제] 두 모드 동시 실행 + 결과 비교가 필요할 때. OpenAI API 비용 다수 발생.

실행: python -m confluence_mcp.demo_run    (프로젝트 루트에서)
"""
import main

main.MAX_DAYS = 365
main.AB_COMPARE = []
main.ACTIVE_PERSONALITIES = ["균형형", "성과형", "사교형", "정치형", "워라밸형"]
main.LOG_INTERVAL = 30
main.AUTO_VISUALIZE = False

if __name__ == "__main__":
    main.main()

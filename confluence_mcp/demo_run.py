"""[용도] 5성향 1년 시뮬레이션 데모 — code-driven (Reflection 저장/조회) + LLM-driven (성향 프로필) 동시 실행.
       Confluence에 다음 두 종류 페이지가 생성된다:
         - Profile_DeepAgent_{성향}_{run_id}        → LLM-driven (성향당 1장, 시작 시 1회)
         - Reflection_DeepAgent_{성향}_Day{N}_{run_id} → code-driven (성향당 ~2장, Reflection 트리거 시)
       총 ≈ 5 + 10 = 15장 페이지.
[언제] 두 모드 동시 실행 + 결과 시각 비교가 필요할 때. 본 실행은 데모 목적.
       OpenAI API 호출이 다수 발생 (5 agents × LLM 호출들 + 5 profile + ~10 reflection).

실행: python -m confluence_mcp.demo_run    (프로젝트 루트에서)
"""
import main

main.MAX_DAYS = 365
main.AB_COMPARE = []                # A/B (Reflect/NoReflect) 분기 끔
main.ACTIVE_PERSONALITIES = ["균형형", "성과형", "사교형", "정치형", "워라밸형"]
main.LOG_INTERVAL = 30
main.AUTO_VISUALIZE = False         # HTML 시각화는 데모 범위 밖

if __name__ == "__main__":
    main.main()

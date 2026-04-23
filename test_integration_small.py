"""[용도] main.py 시뮬레이션 + 직접 만든 MCP 서버 통합이 한 사이클 끝까지 도는지 확인 (스모크).
       MAX_DAYS=365, 정치형 1명 → Reflection 2~3회 → 저장·조회 경로 점검.
       성능/평가가 아니라 "파이프라인이 막히지 않는다"만 본다.
[언제] main.py나 confluence_mcp_server/ 수정 후, 풀 실행 전 안전 확인.
       OpenAI API 호출 발생 (비용은 작지만 0은 아님).

실행: python test_integration_small.py
"""
import main

main.MAX_DAYS = 365
main.AB_COMPARE = []
main.ACTIVE_PERSONALITIES = ["정치형"]
main.LOG_INTERVAL = 30
main.AUTO_VISUALIZE = False

if __name__ == "__main__":
    main.main()

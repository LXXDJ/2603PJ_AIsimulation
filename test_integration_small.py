"""[용도] main.py 시뮬레이션 + Confluence 연동이 한 사이클이라도 끝까지 도는지 확인 (스모크).
       MAX_DAYS=365, 정치형 1명 → reflection 약 3회 발생 → 저장/조회 경로 점검.
       성능/평가가 아니라 "파이프라인이 막히지 않는다"만 본다.
[언제] main.py나 confluence_official.py를 만진 후, 7300일 풀 실행 전에 안전 확인.
       OpenAI API 호출이 일어나므로 비용은 작지만 0은 아님.

실행: python test_integration_small.py
"""
import main

# 365일 / 정치형 1개 → 90·180·270·360일 부근에 reflection 3~4회 발생
main.MAX_DAYS = 365
main.AB_COMPARE = []                # A/B 분기 끔
main.ACTIVE_PERSONALITIES = ["정치형"]
main.LOG_INTERVAL = 30

# 비교 시각화는 1개 결과만으론 의미 없으니 비활성화
main.AUTO_VISUALIZE = False

if __name__ == "__main__":
    main.main()

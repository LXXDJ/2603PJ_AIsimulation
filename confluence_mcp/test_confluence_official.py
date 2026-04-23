"""[용도] confluence_official.save_reflection → fetch_past_reflections_text 한 사이클 검증.
       시뮬레이션 본체(main.py) 없이 wrapper만 단독으로 실제 Confluence에 페이지를 만들고 다시 읽는다.
[언제] confluence_official.py를 수정한 직후 회귀 확인 (시뮬레이션 전체를 돌리지 않고 빠르게).
       매 실행마다 agent_name에 timestamp가 붙어 페이지 충돌은 안 남.

실행: python test_confluence_official.py
"""
from datetime import datetime
from dotenv import load_dotenv

from confluence_official import save_reflection, fetch_past_reflections_text


def main():
    load_dotenv()

    # 같은 제목 중복을 피하기 위해 timestamp를 agent_name에 포함
    agent_name = f"TEST_{datetime.now().strftime('%H%M%S')}"

    print(f"[*] save_reflection 호출 — agent={agent_name}, day=90")
    ok = save_reflection(
        agent_name=agent_name,
        day=90,
        text="평가: 야근만 12일, 휴가 0일.\n문제점: 스트레스 85.\n처방: 휴가 8일.",
        quota={"휴가를 쓴다": 8, "프로젝트에 집중한다": 12, "상사와 점심을 먹는다": 5,
               "자기계발을 한다": 5, "야근한다": 0, "동료를 도와준다": 0,
               "정치적으로 행동한다": 0, "이직 준비를 한다": 0},
    )
    print(f"[+] save 결과: {ok}\n")

    print(f"[*] save_reflection 호출 — agent={agent_name}, day=180")
    ok = save_reflection(
        agent_name=agent_name,
        day=180,
        text="평가: 휴가 처방 잘 따랐음. 스트레스 50으로 회복.\n처방: 다음은 평판 작업.",
        quota={"동료를 도와준다": 10, "프로젝트에 집중한다": 10, "휴가를 쓴다": 5,
               "자기계발을 한다": 5, "야근한다": 0, "상사와 점심을 먹는다": 0,
               "정치적으로 행동한다": 0, "이직 준비를 한다": 0},
    )
    print(f"[+] save 결과: {ok}\n")

    print(f"[*] fetch_past_reflections_text — agent={agent_name}, limit=5")
    past = fetch_past_reflections_text(agent_name, limit=5)
    print(f"[+] fetch 결과 ({len(past)}자):")
    print("─" * 70)
    print(past)
    print("─" * 70)


if __name__ == "__main__":
    main()

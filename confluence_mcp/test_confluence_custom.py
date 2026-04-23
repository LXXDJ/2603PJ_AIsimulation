"""[용도] confluence_custom wrapper 단독 검증 — 우리 MCP 서버를 subprocess로 띄우고
       save_reflection → fetch_past_reflections_text 한 사이클 동작 확인.
       MCP 프로토콜 통신이 끝까지 도는지(서버 spawn → 도구 호출 → 응답 파싱) 점검.

[언제] confluence_custom.py 또는 confluence_mcp_server/ 수정 직후 회귀.

실행: python -m confluence_mcp.test_confluence_custom   (프로젝트 루트에서)
"""
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

from confluence_mcp.confluence_custom import save_reflection, fetch_past_reflections_text


def main():
    agent = f"TEST_WRAPPER_{datetime.now().strftime('%H%M%S')}"

    print(f"[*] save_reflection (MCP 프로토콜 경유) — agent={agent}, day=90")
    ok1 = save_reflection(
        agent_name=agent, day=90,
        text="평가: 야근 12일.\n처방: 휴가 8일.",
        quota={"휴가를 쓴다": 8, "프로젝트에 집중한다": 22},
    )
    print(f"[+] save 결과: {ok1}\n")

    print(f"[*] save_reflection — agent={agent}, day=180")
    ok2 = save_reflection(
        agent_name=agent, day=180,
        text="평가: 휴가 처방 잘 따랐음.\n처방: 평판 작업.",
        quota={"동료를 도와준다": 10, "휴가를 쓴다": 5},
    )
    print(f"[+] save 결과: {ok2}\n")

    print(f"[*] fetch_past_reflections_text — agent={agent}, limit=5")
    past = fetch_past_reflections_text(agent_name=agent, limit=5)
    print(f"[+] fetch 결과 ({len(past)}자):")
    print("─" * 70)
    print(past)
    print("─" * 70)


if __name__ == "__main__":
    main()

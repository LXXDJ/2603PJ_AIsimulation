"""[용도] 직접 만든 MCP 서버의 도메인 도구가 정상 동작하는지 단독 검증.
       MCP 프로토콜은 우회하고 도구 함수를 직접 호출 (서버 init·도구 정의가 제대로 됐는지 + REST 통신 OK인지 확인).

[언제] server.py·confluence_client.py 수정 직후, 또는 .env 인증 의심될 때.

실행: python -m confluence_mcp_server.test_server   (프로젝트 루트에서)
"""
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# server.py에서 도구 함수를 직접 import (FastMCP 서버 띄우지 않음)
from confluence_mcp_server.server import save_reflection, fetch_past_reflections


def main():
    agent = f"TEST_CUSTOM_{datetime.now().strftime('%H%M%S')}"

    print(f"[*] save_reflection 호출 — agent={agent}, day=90")
    r1 = save_reflection.fn(
        agent_name=agent,
        day=90,
        text="평가: 야근 12일.\n처방: 휴가 8일.",
        quota={"휴가를 쓴다": 8, "프로젝트에 집중한다": 22},
    )
    print(f"[+] 결과: {r1}\n")

    print(f"[*] save_reflection 호출 — agent={agent}, day=180")
    r2 = save_reflection.fn(
        agent_name=agent,
        day=180,
        text="평가: 휴가 처방 잘 따랐음.\n처방: 평판 작업.",
        quota={"동료를 도와준다": 10, "휴가를 쓴다": 5},
    )
    print(f"[+] 결과: {r2}\n")

    print(f"[*] fetch_past_reflections — agent={agent}, limit=5")
    past = fetch_past_reflections.fn(agent_name=agent, limit=5)
    print(f"[+] 결과 ({len(past)}건):")
    for item in past:
        print(f"  - Day {item['day']}: {item['title']}")
        print(f"      text 발췌: {item['text'][:60]}")
        print(f"      quota: {item['quota']}")


if __name__ == "__main__":
    main()

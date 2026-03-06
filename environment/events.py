import random
from dataclasses import dataclass


@dataclass
class Event:
    name: str
    description: str
    effects: dict   # {"performance": +10, "stress": +20, ...}
    probability: float  # 하루에 발생할 확률


# 항상 등록되어 있는 이벤트 풀
EVENT_POOL: list[Event] = [
    Event(
        name="상사 칭찬",
        description="상사가 최근 업무를 칭찬했다.",
        effects={"boss_favor": 10, "reputation": 5, "stress": -5},
        probability=0.05,
    ),
    Event(
        name="상사 질책",
        description="상사가 실수를 크게 질책했다.",
        effects={"boss_favor": -15, "stress": 20, "energy": -10},
        probability=0.05,
    ),
    Event(
        name="프로젝트 성공",
        description="담당 프로젝트가 좋은 평가를 받았다.",
        effects={"performance": 15, "reputation": 10, "boss_favor": 8},
        probability=0.04,
    ),
    Event(
        name="프로젝트 실패",
        description="담당 프로젝트가 실패했다. 책임 소재가 논의되고 있다.",
        effects={"performance": -20, "reputation": -10, "stress": 25},
        probability=0.03,
    ),
    Event(
        name="구조조정 공지",
        description="회사에서 구조조정을 예고했다. 분위기가 어수선하다.",
        effects={"stress": 30, "peer_relation": -10},
        probability=0.02,
    ),
    Event(
        name="상사 교체",
        description="직속 상사가 갑자기 교체됐다. 새 상사와의 관계를 다시 쌓아야 한다.",
        effects={"boss_favor": -20, "stress": 15},
        probability=0.015,
    ),
    Event(
        name="팀원 퇴사",
        description="가까운 팀원이 갑자기 퇴사했다. 업무 부담이 늘었다.",
        effects={"stress": 15, "peer_relation": -5, "performance": -5},
        probability=0.03,
    ),
    Event(
        name="소문 발생",
        description="나에 대한 좋지 않은 소문이 돌고 있다.",
        effects={"reputation": -15, "peer_relation": -10, "stress": 10},
        probability=0.02,
    ),
    Event(
        name="회식",
        description="팀 회식이 있었다. 동료들과 관계가 가까워졌다.",
        effects={"peer_relation": 10, "boss_favor": 5, "energy": -10},
        probability=0.04,
    ),
    Event(
        name="헤드헌터 연락",
        description="헤드헌터로부터 이직 제안이 왔다.",
        effects={"reputation": 5},
        probability=0.02,
    ),
]


def roll_events(rng: random.Random | None = None) -> list[Event]:
    """오늘 발생할 이벤트를 확률적으로 선택해 반환."""
    r = rng or random
    triggered = []
    for event in EVENT_POOL:
        if r.random() < event.probability:
            triggered.append(event)
    return triggered

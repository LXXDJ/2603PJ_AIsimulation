# Confluence 연동 (공식/커뮤니티 MCP 사용)

이 브랜치(`feature/mcp-confluence-official`)는 **시뮬레이션 본체에 손을 대지 않고 Confluence를 붙이는** 작업의 결과물이다.
시뮬레이션이 매 분기 만들어내는 Reflection(자기성찰 결과)을 Confluence 페이지로 영구 저장하고, 다음 회차의 프롬프트에 다시 주입한다.

핵심 의도는 **"이미 있는 MCP 서버를 그대로 끼워 쓰는 경로"의 비용·구조를 코드로 박제해 두는 것**이다. 다른 브랜치(`feature/mcp-confluence-custom`)에서 직접 만든 MCP 서버와 줄나란히 놓고 비교하기 위함.

---

## 목차

1. [사전 준비](#1-사전-준비)
2. [전체 구조](#2-전체-구조)
3. [지금 코드가 실제로 하는 일](#3-지금-코드가-실제로-하는-일)
4. [mcp-atlassian이 노출하는 도구 전수](#4-mcp-atlassian이-노출하는-도구-전수)
5. [사용 예시 (코드 스니펫)](#5-사용-예시-코드-스니펫)
6. [통합 패턴 두 가지: code-driven vs LLM-driven](#6-통합-패턴-두-가지-code-driven-vs-llm-driven)
7. [검증 스크립트 (4개)](#7-검증-스크립트-4개)
8. [현 구조의 한계 (다른 브랜치와의 비교 포인트)](#8-현-구조의-한계-다른-브랜치와의-비교-포인트)

---

## 1. 사전 준비

### 1-1. 의존성

```bash
pip install langchain-mcp-adapters mcp-atlassian python-dotenv
```

- `mcp-atlassian` — Python으로 작성된 커뮤니티 MCP 서버 (Atlassian 공식 제공이 아님). API Token 인증.
- `langchain-mcp-adapters` — MCP 도구를 LangChain `BaseTool`로 어댑팅하는 브릿지.

### 1-2. 환경변수 (`.env`)

```dotenv
CONFLUENCE_URL=https://atdev-ai.atlassian.net/wiki
CONFLUENCE_USERNAME=<Atlassian 로그인 이메일>
CONFLUENCE_API_TOKEN=<https://id.atlassian.com/manage-profile/security/api-tokens 에서 발급>
```

> Atlassian의 **공식 Remote MCP**(OAuth 2.1+PKCE)는 Python에서 LangChain 어댑터가 OAuth 2.1을 아직 지원하지 않아 직접 못 붙는다 (관련 이슈 close됨, "not planned"). 그래서 이 브랜치에서는 커뮤니티 서버 `mcp-atlassian`(API Token)을 사용한다. 이것 자체가 "공식 vs 커뮤니티"의 한 차이점이며, README 8장의 한계 항목에 이어진다.

### 1-3. 저장 대상 페이지

`confluence_official.py` 상단의 두 상수가 저장 위치를 정한다.

```python
PARENT_PAGE_ID = "120520708"  # 이 페이지의 자식으로 모든 Reflection을 매단다
SPACE_KEY = "mcptest"
```

테스트용 스페이스/페이지를 미리 만들어 두고 ID만 바꾸면 어디든 붙일 수 있다.

---

## 2. 전체 구조

### 2-1. 파일 구성

| 파일 | 역할 |
|---|---|
| [confluence_official.py](confluence_mcp/confluence_official.py) | MCP 클라이언트 wrapper. save/fetch 함수 2개 노출 |
| [main.py](main.py) | 시뮬레이션 본체. Reflection 시점 전후로 wrapper 호출만 추가 |
| [test_mcp.py](confluence_mcp/test_mcp.py) | MCP 연결 자체 sanity check |
| [test_mcp_schema.py](confluence_mcp/test_mcp_schema.py) | mcp-atlassian이 노출한 도구의 인자 스키마 일괄 출력 |
| [test_confluence_official.py](confluence_mcp/test_confluence_official.py) | wrapper save→fetch 한 사이클 단독 검증 |
| [test_integration_small.py](test_integration_small.py) | main.py + Confluence 통합 스모크 (200일/1성향) |

### 2-2. 호출 흐름 (Reflection 1회 발생 시)

```
시뮬레이션 진행
   │
   ├─ Day N에서 90일 지났음, history 누적 충분 → Reflection 트리거
   │
   ├─ [1] confluence_official.fetch_past_reflections_text(agent_name, limit=3)
   │      └─ get_page_children(parent_id=120520708) → results 필터링/정렬 → 텍스트 N개
   │
   ├─ [2] reflection_prompt에 "[ 과거 Reflection 기록 ]" 섹션으로 주입
   │
   ├─ [3] reflection_agent.invoke(...) → LLM이 새 처방 생성
   │
   ├─ [4] _parse_quota(reflection_text) → JSON quota 추출
   │
   └─ [5] confluence_official.save_reflection(agent_name, day, text, quota, run_id=timestamp)
          └─ create_page(parent_id, title="Reflection_{agent}_Day{NNNN}_{run_id}", content=markdown)
```

### 2-3. 스레드 모델

`main.py`는 5명의 에이전트(성향)를 `ThreadPoolExecutor`로 동시에 돌린다. mcp-atlassian은 stdio transport(서브프로세스)이고 stdio는 thread-safe하지 않으므로 **워커 스레드마다 별도의 mcp-atlassian 서브프로세스 + 별도 asyncio 이벤트 루프**를 둔다. 이는 `threading.local()`과 첫 호출 시 lazy init 패턴으로 구현된다 (`confluence_official._ensure_init`).

> 트레이드오프: 스레드별 init 첫 호출은 2~3초가 걸린다. 다만 이후 호출은 같은 서브프로세스를 재사용하므로 반복 호출 비용은 무시할 수준.

---

## 3. 지금 코드가 실제로 하는 일

`confluence_official.py`는 **24개 중 2개의 도구만** 사용한다.

| wrapper 함수 | 호출하는 MCP 도구 | 사용 시점 |
|---|---|---|
| `save_reflection(agent, day, text, quota, run_id)` | `confluence_create_page` | 매 Reflection 직후 |
| `fetch_past_reflections_text(agent, limit)` | `confluence_get_page_children` | 매 Reflection 직전 |

### 페이지 제목 규약

```
Reflection_{agent_name}_Day{day:04d}[_{run_id}]
예: Reflection_DeepAgent_정치형_Day0090_260423_102135
```

- `Day{day:04d}` 4자리 zero-padding → 문자열 정렬도 시간 순서 유지
- `run_id`(시뮬레이션 시작 timestamp)를 suffix로 붙여 **같은 에이전트로 여러 번 돌려도 제목 충돌 없이 공존**
- 조회는 `Reflection_{agent_name}_Day` prefix만 매칭하므로 run_id가 있어도 자연스럽게 잡힘

### 왜 검색(search)이 아니라 자식 조회(get_page_children)인가

- `confluence_search`는 CQL 토큰화/인덱싱 지연 때문에 **방금 만든 페이지가 즉시 검색되지 않는** 경우가 발생 (실제 디버깅 중 확인됨)
- `confluence_get_page_children`은 **부모 페이지 트리를 즉시 일관성 있게 반환**
- 부모 페이지 한 곳에 모든 Reflection을 매다는 구조라면 자식 조회가 더 정확하고 빠르다

대신 자식 조회는 limit이 1~50이라 페이지가 50개를 초과하면 페이지네이션이 필요하다 (현 구현에서는 미처리, [한계](#8-현-구조의-한계-다른-브랜치와의-비교-포인트) 참조).

---

## 4. mcp-atlassian이 노출하는 도구 전수

`test_mcp_schema.py`가 출력하는 24개 Confluence 도구. **현재 wrapper에서 쓰는 2개 외에 나머지 22개를 그대로 활용 가능하다** (추가 코드 변경 없이 같은 클라이언트로).

| 분류 | 도구 | 용도 (요약) |
|---|---|---|
| **페이지 R** | `confluence_get_page` | ID 또는 (제목+space)로 단일 페이지 |
| | `confluence_get_page_children` ★ | 부모 페이지의 자식 리스트 (현재 사용) |
| | `confluence_get_space_page_tree` | 스페이스 전체 트리 |
| | `confluence_search` | CQL 또는 자연어 검색 |
| **페이지 CUD** | `confluence_create_page` ★ | 새 페이지 생성 (현재 사용) |
| | `confluence_update_page` | 페이지 수정 |
| | `confluence_delete_page` | 페이지 삭제 |
| | `confluence_move_page` | 페이지 이동 |
| **첨부** | `confluence_upload_attachment` / `_attachments` | 파일 업로드 |
| | `confluence_download_attachment` | 파일 다운로드 |
| | `confluence_get_attachments` | 첨부 목록 |
| | `confluence_delete_attachment` | 첨부 삭제 |
| | `confluence_download_content_attachments` | 페이지 콘텐츠 + 첨부 일괄 |
| **댓글** | `confluence_add_comment` | 코멘트 작성 |
| | `confluence_get_comments` | 코멘트 조회 |
| | `confluence_reply_to_comment` | 코멘트 응답 |
| **메타** | `confluence_add_label` / `_get_labels` | 라벨 |
| | `confluence_get_page_history` | 버전 이력 |
| | `confluence_get_page_diff` | 버전 간 차이 |
| | `confluence_get_page_views` | 조회수 |
| | `confluence_get_page_images` | 본문 내 이미지 |
| **사용자** | `confluence_search_user` | 사용자 검색 |

★ 표시가 현재 wrapper에서 사용 중.

### 같은 연결로 자연스럽게 확장 가능한 작업 예

- 시뮬레이션 종료 시 결과 요약을 별도 페이지로 저장 (`create_page`)
- 매 분기 Reflection을 새 페이지 대신 기존 페이지에 append 형태로 누적 (`update_page`)
- Reflection 페이지에 성향/분기 라벨 부여 → CQL로 카테고리 검색 (`add_label` + `search`)
- 결과 시각화 HTML/이미지를 페이지에 첨부 (`upload_attachment`)
- 사람이 단 코멘트를 LLM 컨텍스트로 가져와 다음 Reflection에 반영 (`get_comments`)

---

## 5. 사용 예시 (코드 스니펫)

### 5-1. 가장 최소: 한 페이지 만들고 한 페이지 읽기

```python
from dotenv import load_dotenv
from confluence_official import save_reflection, fetch_past_reflections_text

load_dotenv()

save_reflection(
    agent_name="DeepAgent_테스트",
    day=90,
    text="평가: 야근 과다.\n처방: 휴가 8일.",
    quota={"휴가를 쓴다": 8, "프로젝트에 집중한다": 22},
    run_id="manual_smoke",
)

print(fetch_past_reflections_text("DeepAgent_테스트", limit=3))
```

### 5-2. main.py에 통합된 모습 (요지)

```python
# Reflection 직전
past_reflections_section = ""
if USE_CONFLUENCE:
    past_text = confluence_official.fetch_past_reflections_text(
        agent_name, limit=PAST_REFLECT_LIMIT,
    )
    if past_text:
        past_reflections_section = f"\n[ 과거 Reflection 기록 (Confluence) ]\n{past_text}\n"

reflect_prompt = REFLECTION_PROMPT.format(
    ...,
    past_reflections_section=past_reflections_section,
)

# LLM이 새 Reflection 생성 후
if USE_CONFLUENCE:
    confluence_official.save_reflection(
        agent_name=agent_name, day=day,
        text=reflection_text, quota=action_quota,
        run_id=timestamp,
    )
```

핵심: **Confluence 호출은 시뮬레이션 루프의 정해진 자리에 박혀 있고, LLM은 Confluence의 존재를 모른다**. 이게 6장에서 말하는 "code-driven" 패턴이다.

### 5-3. 새 도구 하나 추가하고 싶다면

```python
# confluence_official.py 안에 추가
def add_label_to_reflection(page_id: str, label: str) -> bool:
    tools = _ensure_init()
    add_label = tools.get("confluence_add_label")
    if not add_label:
        return False
    try:
        _local.loop.run_until_complete(add_label.ainvoke({
            "page_id": page_id,
            "label": label,
        }))
        return True
    except Exception as e:
        print(f"[Confluence] add_label 실패: {e}")
        return False
```

도구 인자명을 모르면 `python test_mcp_schema.py`로 확인.

---

## 6. 통합 패턴 두 가지: code-driven vs LLM-driven

같은 mcp-atlassian 연결을 **누가 호출 결정을 내리느냐**에 따라 두 가지 방식으로 쓸 수 있다.

| | 옵션 B (현재) | 옵션 A |
|---|---|---|
| 누가 결정? | Python 코드 | LLM (Deep Agent) |
| 우리 코드 | `tool.ainvoke({...})` 직접 호출 | Deep Agent의 `tools=[...]`에 도구 그대로 전달 |
| 호출 시점 | 시뮬레이션 루프의 정해진 자리 | LLM이 매 단계 판단 |
| 장점 | 결정적, 디버깅 쉬움, 토큰 비용 낮음 | "지금 검색해야겠다" 같은 동적 판단 가능 |
| 단점 | 새로운 use case마다 코드 수정 필요 | 도구 잘못 호출 위험, 비용 증가, 로깅 복잡 |
| 적합 | "Reflection 끝나면 무조건 저장" 같은 명확한 시점 | "여러 페이지 중 하나를 LLM이 선택" 같은 의사결정 |

### 옵션 A로 전환하려면

`main.py`에서 `decision_agent`/`reflection_agent` 생성 부분의 `tools=[]` 자리에 MCP 도구 리스트를 넣는다.

```python
mcp_tools = list(confluence_official._ensure_init().values())
reflection_agent = create_deep_agent(
    model=f"openai:{MODEL_REFLECTION}",
    tools=mcp_tools,  # LLM이 이 도구들을 자율적으로 호출
    system_prompt="당신은 ... Confluence에 'Reflection_{agent}_Day{N}'으로 저장하세요.",
    name=f"reflection_{personality_name}",
)
```

이때 `_ensure_init`은 메인 스레드에서 한 번 호출되어야 하고, 워커 스레드는 별도 init이 필요하다는 점에 주의 (옵션 A로 가도 스레드 모델은 그대로 적용됨).

> 이 브랜치는 코드리뷰의 공정성을 위해 **옵션 B 한 가지로 통일**한다. 직접 만든 MCP 서버 브랜치도 같은 패턴(B)으로 작성될 예정.

---

## 7. 검증 스크립트 (4개)

| 파일 | 무엇을 검증 | 언제 돌리나 | 외부 호출 |
|---|---|---|---|
| [test_mcp.py](confluence_mcp/test_mcp.py) | mcp-atlassian이 떠서 페이지 1개 읽힘 | 인증/연결 의심될 때 가장 먼저 | Confluence read 1회 |
| [test_mcp_schema.py](confluence_mcp/test_mcp_schema.py) | 24개 도구 인자 스키마 | 라이브러리 업그레이드 후, 새 도구 wrapper 추가 전 | Confluence 도구 메타만 |
| [test_confluence_official.py](confluence_mcp/test_confluence_official.py) | save→fetch 한 사이클 (wrapper 단독) | `confluence_official.py` 수정 직후 회귀 | Confluence write 2회 + read 1회 |
| [test_integration_small.py](test_integration_small.py) | main.py 200일 / 1성향 스모크 | main.py나 wrapper 만진 후 풀 실행 전 | OpenAI API + Confluence write 1~2회 |

각 파일 상단 주석에 같은 정보가 정리되어 있다.

### 실행 (Windows)

콘솔이 cp949일 경우 한글 출력에서 `UnicodeEncodeError`가 난다. UTF-8로 강제:

```bash
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python test_confluence_official.py
```

---

## 8. 현 구조의 한계 (다른 브랜치와의 비교 포인트)

직접 만든 MCP 서버(`feature/mcp-confluence-custom`)와의 코드리뷰에서 짚을 항목들.

### 8-1. 도메인 무지

- mcp-atlassian의 도구는 **일반 CRUD** — "Reflection"이라는 우리 도메인 개념을 모름
- 그래서 클라이언트가 직접:
  - 제목 prefix(`Reflection_{agent}_Day`) 규약을 강제
  - 응답에서 day 번호 파싱 + 내림차순 정렬
  - 자식 페이지 중 우리 것만 필터링
- 직접 만든 MCP라면 `save_reflection(agent, day, text)` 같은 도메인 동사를 그대로 노출 가능 → 클라이언트 코드는 단순해지고, 서버가 일관성 보장

### 8-2. 응답 노이즈

- `get_page_children` 응답에 `url`, `version`, `attachments`, `space.name` 등 **우리에게 불필요한 메타데이터**가 같이 옴
- `_unwrap_text` → `json.loads` → 필드 추출의 파싱 단계가 항상 한 겹 더 들어감
- 직접 만든 MCP는 도메인에 맞춰 응답을 **반드시 필요한 필드만 깎아서** 줄 수 있음

### 8-3. 인덱싱/일관성 가정

- `confluence_search`는 인덱싱 지연으로 직후 조회 시 빈 결과를 반환할 수 있음 → 우리는 `get_page_children`으로 우회
- 직접 만든 MCP는 자체 DB/캐시로 **즉시 일관성**을 보장하도록 설계 가능

### 8-4. 페이지네이션 미처리

- `get_page_children`의 `limit`은 1~50. 부모 페이지에 자식이 50개를 넘으면 잘림
- 5명 에이전트 × 81 reflection (20년) ≈ 405개 자식 → 풀 실행 시 한 번의 호출로 못 가져옴
- 현 구현은 단일 호출만 사용하므로 정확히 가장 최근 50개 안에 들어야 하는 가정에 의존
- 직접 만든 MCP라면 "이 에이전트의 최근 N개"라는 도구를 만들어 서버에서 한 번에 처리 가능

### 8-5. 인증/거버넌스

- 공식 Atlassian Remote MCP(OAuth 2.1+PKCE)를 못 쓰고 **API Token**으로 동작 → 토큰 노출 시 영향 범위가 사용자 전체 권한
- 직접 만든 MCP는 자체 인증 정책(예: read-only 토큰, IP 제한, 사용처별 분리)을 강제 가능
- 단, 직접 만든 MCP는 직접 운영해야 함 → 운영 부담은 늘어남 (이 부분 자체가 "기획 관점" 트레이드오프)

### 8-6. 도구 시그니처 변경에 취약

- mcp-atlassian 업데이트 시 인자명/응답 구조가 바뀔 수 있음 → 통합 코드가 깨짐
- `test_mcp_schema.py`로 회귀 검출은 가능하나, 발견 후 수정은 우리 몫
- 직접 만든 MCP는 도구 시그니처를 우리가 통제

---

## 다른 브랜치

- `main` — 시뮬레이션 본체 + 기존 README
- `feature/mcp-confluence-custom` — 직접 만든 MCP 서버로 같은 use case 구현 (작업 예정)

두 feature 브랜치의 비교 분석은 별도 문서 또는 main 브랜치 README의 비교 섹션에서 진행 예정.

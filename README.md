# 직접 만든 MCP 서버로 Confluence 연결하기

---

## 목차

1. [직접 만든 MCP 서버](#1-직접-만든-mcp-서버)
2. [사전 준비](#2-사전-준비)
3. [서비스 흐름과 MCP 추가 지점](#3-서비스-흐름과-mcp-추가-지점)
4. [연결에 필요한 코드](#4-연결에-필요한-코드)
5. [부가: 코드 연결 vs LLM 연결 패턴 비교](#5-부가-코드-연결-vs-llm-연결-패턴-비교)

---

## 1. 직접 만든 MCP 서버

### 1-1. 사용 프레임워크: FastMCP

- 패키지: [FastMCP](https://gofastmcp.com/) — Python으로 MCP 서버를 빠르게 만들 수 있는 데코레이터 기반 프레임워크
- 설치: `pip install fastmcp`
- 인증: Atlassian **API Token** (서버 내부에서 직접 호출, 같은 인증 모델)
- 동작: 본 프로젝트가 작성한 서버를 **subprocess(stdio transport)**로 띄움

### 1-2. 왜 직접 만들었나

[공식 브랜치](https://github.com/LXXDJ/2603PJ_AIsimulation/tree/feature/mcp-confluence-official)에서 사용한 `mcp-atlassian`(커뮤니티 패키지)은 **24개 일반 CRUD 도구**를 노출한다. 우리 use case(Reflection 저장/조회)에 쓰려면 클라이언트가:
- 페이지 제목 prefix 규약(`Reflection_{agent}_Day...`)을 매번 외워서 적용
- 응답에서 day 번호 파싱·정렬·필터링
- 본문 마크다운 형식 통일

같은 코드를 호출 측에서 매번 반복해야 한다. 직접 만든 MCP 서버는 **이런 도메인 로직을 서버 안으로 옮긴다**

| | 공식 (외부 MCP) | 커스텀 (직접 만든 MCP) |
|---|---|---|
| 노출 도구 | 24개 일반 CRUD | **3개 도메인 도구** |
| 클라이언트가 다루는 인자 | space_key, parent_id, content_format, title 등 모두 | agent_name, day, text 등 **도메인 인자만** |
| 응답 파싱 | JSON 중첩 dict 풀기 | **도메인 모양 그대로 받음** |
| 운영 책임 | 외부 패키지에 위임 | 본 프로젝트 |
| 도구 시그니처 | mcp-atlassian 업데이트에 종속 | 본 프로젝트가 통제 |

### 1-3. 서버가 노출하는 도구 (3개)

```
save_reflection(agent_name, day, text, quota?, run_id?, mode="append")
   → Reflection 결과를 페이지로 저장
   → 응답: {id, title}

fetch_past_reflections(agent_name, limit=3)
   → 이 에이전트의 최근 Reflection 리스트
   → 응답: [{day, title, text, quota}, ...]  (day 내림차순)

save_personality_profile(personality_name, agent_name, content, run_id?, mode="append")
   → 성향별 프로필 페이지 저장 (LLM-driven 데모용)
   → 응답: {id, title}
```

> 모든 도구가 **도메인 동사**(`save_reflection`)로 명명. 일반 CRUD(`create_page`)와 차별화.

`mode` 파라미터는 페이지 저장 정책을 결정 (둘 다 본 프로젝트 도메인 정책):
- `"append"` (기본) — 매 실행마다 `_<run_id>` suffix를 붙여 새 페이지 생성. 실행 이력이 누적됨
- `"overwrite"` — 같은 `(agent, day)` 조합은 항상 같은 제목 → 기존 페이지가 있으면 update, 없으면 create (upsert)

---

## 2. 사전 준비

### 2-1. 의존성

```bash
pip install fastmcp httpx langchain-mcp-adapters python-dotenv deepagents
```

| 패키지 | 역할 |
|---|---|
| `fastmcp` | 본 프로젝트 MCP 서버 작성 프레임워크 |
| `httpx` | 서버 내부에서 Atlassian REST API 호출 |
| `langchain-mcp-adapters` | 클라이언트가 MCP 도구를 LangChain `BaseTool`로 변환하는 브릿지 (공식 브랜치와 동일) |
| `deepagents` | LangChain 위 Agent 추상화 (LLM-driven에서만 사용) |
| `python-dotenv` | `.env` 로딩 |

### 2-2. 환경변수 (`.env`)

```dotenv
CONFLUENCE_URL=https://atdev-ai.atlassian.net/wiki
CONFLUENCE_USERNAME=<Atlassian 로그인 이메일>
CONFLUENCE_API_TOKEN=<https://id.atlassian.com/manage-profile/security/api-tokens 에서 발급>
```

### 2-3. 저장 대상 페이지

```python
# confluence_mcp_server/server.py 상단
PARENT_PAGE_ID = "121896967"   # mcptest 스페이스의 'MCP - AI Simulation' 페이지
SPACE_KEY = "mcptest"
```

---

## 3. 서비스 흐름과 MCP 추가 지점

### 3-1. 시뮬레이션 전체 흐름 (MCP 추가 후)

```
┌─────────────────────────────────────────────────────────────────┐
│ main.py / _run_one (성향당 1개 스레드, 5개 동시 실행)               │
│                                                                 │
│   ★ [A] 성향별 Profile 작성  ───────────► MCP 호출 (LLM-driven)   │
│                                                                 │
│   ┌── for day in 1..MAX_DAYS ──┐                                │
│   │                            │                                │
│   │  매 30일: Decision Agent    │                                │
│   │  → 30일치 행동 계획 생성      │                                │
│   │                            │                                │
│   │  매 90일: Reflection 트리거  │                                │
│   │   ★ [B] 과거 Reflection fetch ─────► MCP 호출 (code-driven)  │
│   │      → reflection_prompt에 주입                              │
│   │   Reflection Agent 호출     │                                │
│   │      → 새 Reflection 생성   │                                │
│   │   ★ [C] 새 Reflection save ────────► MCP 호출 (code-driven)  │
│   │                            │                                │
│   └────────────────────────────┘                                │
└─────────────────────────────────────────────────────────────────┘

★ = MCP가 끼는 지점 (총 3곳, 공식 브랜치와 동일)
```

### 3-2. MCP 호출 1회는 어떤 경로를 거치나

도구 1번 호출 시 메시지가 거치는 4계층:

```
┌──────────────────────────────────────────┐
│ [A] 애플리케이션 코드 (Python)            │
│     예: tool.ainvoke({...})              │
└──────────────────┬───────────────────────┘
                   │  LangChain BaseTool 호출
                   ▼
┌──────────────────────────────────────────┐
│ [B] langchain-mcp-adapters 라이브러리     │
│     LangChain 호출 → MCP 메시지 변환      │
└──────────────────┬───────────────────────┘
                   │  MCP 프로토콜 (JSON-RPC over stdio)
                   ▼
┌──────────────────────────────────────────┐
│ [C] 본 프로젝트의 MCP 서버 (FastMCP)      │  ← 여기가 공식 브랜치와의 차이!
│     도메인 도구 → Atlassian REST 호출     │
└──────────────────┬───────────────────────┘
                   │  HTTPS (API Token 인증)
                   ▼
┌──────────────────────────────────────────┐
│ [D] Confluence (Atlassian 클라우드)       │
│     atdev-ai.atlassian.net에서 페이지 생성│
└──────────────────────────────────────────┘
```

각 계층이 무엇이고, 누가 만들었고, 본 프로젝트에서 직접 작성한 부분인지:

| 계층 | 무엇 | 누가 만들었나 |
|---|---|---|
| **[A]** 애플리케이션 코드 | 도구를 호출하는 Python 함수 | 본 프로젝트 |
| **[B]** langchain-mcp-adapters | LangChain ↔ MCP 변환 라이브러리 | LangChain 팀 |
| **[C]** **본 프로젝트의 MCP 서버** | **도메인 도구 정의 + Atlassian REST 변환** | **본 프로젝트** ⭐ |
| **[D]** Confluence | 실제 페이지가 생성되는 곳 | Atlassian |

**공식 브랜치와의 차이**: 공식 브랜치는 [C]가 외부 패키지(`mcp-atlassian`)였다. 이 브랜치는 **[C]도 본 프로젝트가 직접 작성** → [A]뿐만 아니라 [C]도 우리 책임이 됨.

### 3-3. MCP 추가로 얻은 것

| 항목 | MCP 추가 전 | MCP 추가 후 |
|---|---|---|
| **데이터 영속성** | 시뮬레이션 결과(에이전트 로그, Reflection 본문 등)가 실행한 머신의 로컬 `logs/` 폴더 안에 `.txt`, `.jsonl` 파일로만 저장된다. 다른 사람과 공유하려면 파일을 직접 전달해야 하고, 머신이 바뀌면 결과도 사라진다. | 같은 결과가 로컬에 저장되는 동시에 Confluence 페이지로도 자동 등록된다. 웹상에 보관되므로 다른 팀원이 브라우저로 즉시 열어볼 수 있고, Confluence 자체 검색 기능으로 과거 결과를 키워드로 찾을 수 있다. |
| **Reflection 컨텍스트** | Reflection이 참고할 수 있는 과거 정보는 같은 시뮬레이션 실행 안에서 누적된 `EpisodicMemory`로 한정된다. 시뮬레이션을 새로 시작하면 메모리가 초기화되어 이전 실행에서 LLM이 만들어낸 처방·통찰을 다음 실행이 이어받을 방법이 없다. | 매 Reflection 직전에 Confluence에 저장된 과거 Reflection 페이지를 `fetch_past_reflections_text()`로 가져와 프롬프트에 주입한다. 이전 실행본의 처방까지 LLM이 읽을 수 있어 분기·실행 단위를 넘어 일관된 전략을 유지할 수 있다. |

---

## 4. 연결에 필요한 코드

### 파일 구성

| 파일 | 역할 |
|---|---|
| **서버 측** | |
| [confluence_mcp_server/server.py](confluence_mcp_server/server.py) | FastMCP 서버 + 도메인 도구 3개 정의 |
| [confluence_mcp_server/confluence_client.py](confluence_mcp_server/confluence_client.py) | Atlassian REST 호출 wrapper (서버 내부) |
| [confluence_mcp_server/test_server.py](confluence_mcp_server/test_server.py) | 도구 함수 직접 호출 검증 |
| **클라이언트 측** | |
| [confluence_mcp/confluence_custom.py](confluence_mcp/confluence_custom.py) | 우리 서버를 subprocess로 띄우는 wrapper |
| [confluence_mcp/llm_personality.py](confluence_mcp/llm_personality.py) | LLM-driven 통합 (5장에서 상세) |
| [confluence_mcp/test_confluence_custom.py](confluence_mcp/test_confluence_custom.py) | wrapper save→fetch 검증 (MCP 프로토콜 경유) |
| [confluence_mcp/demo_run.py](confluence_mcp/demo_run.py) | 5성향 데모 |
| **통합** | |
| [main.py](main.py) | 시뮬레이션 본체. 호출 지점 추가 + `CONFLUENCE_WRITE_MODE` 플래그 |
| **운영 보조** | |
| [cleanup_confluence.py](cleanup_confluence.py) | 부모 페이지 아래 자식 페이지 일괄 삭제 (테스트 데이터 정리용) |

---

### 4-1. 서버: `confluence_mcp_server/server.py`

이 파일이 **본 프로젝트가 직접 작성한 MCP 서버의 본체**. FastMCP 데코레이터로 도메인 도구를 정의하고, 서버를 stdio transport로 띄움.

#### 〔A〕 서버 init (FastMCP 일반 패턴)

```python
from fastmcp import FastMCP

mcp = FastMCP("Confluence-Custom-MCP")

# ... 도구 정의 ...

if __name__ == "__main__":
    mcp.run()  # stdio transport (default)
```

`mcp.run()`이 stdin/stdout으로 MCP 프로토콜 메시지를 listen. 클라이언트는 이걸 subprocess로 띄움.

#### 〔B〕 도메인 도구 정의 (이 프로젝트 특화)

```python
@mcp.tool()
def save_reflection(agent_name: str, day: int, text: str,
                    quota: dict | None = None, run_id: str | None = None,
                    mode: str = "append") -> dict:
    """Reflection 결과를 Confluence 페이지로 저장."""
    title = _build_reflection_title(agent_name, day, run_id, mode)
    html = _build_html_body(agent_name, day, text, quota)
    return _upsert(SPACE_KEY, title, html, PARENT_PAGE_ID, mode)
```

**인자가 도메인 동사 그대로**. 클라이언트는 `save_reflection(agent_name="...", day=90, text="...")`만 부르면 됨. 페이지 제목 prefix, 본문 형식, 부모 페이지 ID 같은 부수 정보는 **서버가 자체 책임**.

#### 〔C〕 mode에 따른 분기 — `_upsert` 헬퍼

`mode` 값에 따라 create / update를 분기하는 작은 헬퍼:

```python
def _upsert(space_key, title, html_body, parent_id, mode):
    if mode == "overwrite":
        existing = find_page_by_title(space_key, title)
        if existing:
            return update_page(
                page_id=existing["id"], title=title,
                html_body=html_body,
                current_version=existing["version"],
            )
    return create_page(
        space_key=space_key, title=title,
        html_body=html_body, parent_id=parent_id,
    )
```

- `append`: 무조건 create (제목에 `_<run_id>` 들어가므로 충돌 없음)
- `overwrite`: find → 있으면 update(version+1), 없으면 create

#### 〔D〕 Atlassian REST 호출 (`confluence_client.py`)

```python
import httpx

_AUTH = (USERNAME, API_TOKEN)
_REST_ROOT = f"{CONFLUENCE_BASE_URL}/rest/api"

def _request(method, path, json_body=None, params=None):
    url = f"{_REST_ROOT}/{path.lstrip('/')}"
    response = httpx.request(method, url, auth=_AUTH,
                             json=json_body, params=params, timeout=30.0)
    response.raise_for_status()
    if not response.content:
        return {}
    return response.json()

def create_page(space_key, title, html_body, parent_id=None) -> dict:
    body = {
        "type": "page", "title": title,
        "space": {"key": space_key},
        "body": {"storage": {"value": html_body, "representation": "storage"}},
    }
    if parent_id:
        body["ancestors"] = [{"id": parent_id}]
    raw = _request("POST", "content", json_body=body)
    return {"id": raw["id"], "title": raw["title"]}

def find_page_by_title(space_key, title) -> dict | None:
    """제목 완전 일치로 1건 조회 (overwrite 모드용)."""
    raw = _request("GET", "content", params={
        "spaceKey": space_key, "title": title, "expand": "version",
    })
    results = raw.get("results", [])
    if not results: return None
    hit = results[0]
    return {"id": hit["id"], "title": hit["title"],
            "version": hit.get("version", {}).get("number", 1)}

def update_page(page_id, title, html_body, current_version) -> dict:
    """기존 페이지 본문 덮어쓰기. version은 +1 필수 (Confluence 낙관적 락)."""
    body = {
        "type": "page", "title": title,
        "version": {"number": current_version + 1},
        "body": {"storage": {"value": html_body, "representation": "storage"}},
    }
    raw = _request("PUT", f"content/{page_id}", json_body=body)
    return {"id": raw["id"], "title": raw["title"]}
```

**얇은 HTTP 래퍼**. 인증·URL 조립·에러 raise만. 도메인 로직 없음 (그건 서버가 담당).

---

### 4-2. 클라이언트 wrapper: `confluence_mcp/confluence_custom.py`

공식 브랜치의 `confluence_official.py`와 **거의 동일한 구조**. 차이는 spawn할 명령뿐.

```python
client = MultiServerMCPClient({
    "confluence_custom": {
        "command": sys.executable,                       # 같은 Python 인터프리터
        "args": ["-m", "confluence_mcp_server.server"],   # ← 우리 서버 띄움 (공식 브랜치는 "mcp-atlassian")
        "transport": "stdio",
        "env": _build_subprocess_env(),
    }
})
```

#### save_reflection wrapper

```python
def save_reflection(agent_name, day, text, quota,
                    run_id=None, mode="append") -> bool:
    tools = _ensure_init()
    save_tool = tools["save_reflection"]
    _local.loop.run_until_complete(save_tool.ainvoke({
        "agent_name": agent_name,
        "day": day,
        "text": text,
        "quota": quota,
        "run_id": run_id,
        "mode": mode,    # ← main.py의 CONFLUENCE_WRITE_MODE 그대로 통과
    }))
    return True
```

공식 브랜치 wrapper와 비교:

| | 공식 (mcp-atlassian) | 커스텀 (직접 만든 서버) |
|---|---|---|
| 호출 도구 | `confluence_create_page` | `save_reflection` |
| 인자 종류 | space_key, title, content, parent_id, content_format | **agent_name, day, text, quota, run_id** |
| 클라이언트가 조립할 것 | 제목 prefix(`f"Reflection_..."`), HTML body, parent_id 상수 | 없음 — 그대로 전달 |
| 응답 파싱 | `{type:'text', text:'JSON 문자열'}` 풀고 → JSON 파싱 → dict | 서버가 도메인 모양으로 줘서 단순 |

**호출 측 코드량이 절반 이하로 줄어듬**. 핵심: 서버가 도메인을 알기 때문.

---

### 4-3. main.py 통합

상단에 저장 정책을 결정하는 플래그 1개:

```python
CONFLUENCE_WRITE_MODE = "overwrite"     # 페이지 저장 방식: "append" | "overwrite"
```

호출 지점은 두 군데. 둘 다 위 플래그를 그대로 전달:

```python
from confluence_mcp import confluence_custom   # ← import 한 줄

# Reflection 직전: 과거 fetch
if USE_CONFLUENCE:
    past_text = confluence_custom.fetch_past_reflections_text(
        agent_name, limit=PAST_REFLECT_LIMIT,
    )
    # ... 프롬프트에 주입

# Reflection 직후: save
if USE_CONFLUENCE:
    confluence_custom.save_reflection(
        agent_name=agent_name, day=day,
        text=reflection_text, quota=action_quota,
        run_id=timestamp,
        mode=CONFLUENCE_WRITE_MODE,    # ← 한 줄로 정책 통제
    )
```

**공식 브랜치와의 차이는 `confluence_official` → `confluence_custom` 한 단어뿐**. 같은 시그니처라서 import 한 줄만 바꾸면 두 모드 전환 가능 — 비교 실험에 유리.

> `CONFLUENCE_WRITE_MODE`는 LLM-driven Profile 저장에도 동일하게 적용됨 (5장 참조). 즉 한 줄로 코드/LLM 양쪽 저장 정책을 통제.

---

## 5. 부가: 코드 연결 vs LLM 연결 패턴 비교

위 4장은 **코드 연결(code-driven)**. 이 브랜치도 공식과 마찬가지로 **LLM 연결(LLM-driven)** 패턴을 같이 구현했다 ([confluence_mcp/llm_personality.py](confluence_mcp/llm_personality.py)).

### 5-1. 코드 연결 — 해당 코드 부분만

`main.py`의 Reflection 블록에서 **코드가 직접 도구 호출** — LLM은 도구 존재를 모름.

```python
past_text = confluence_custom.fetch_past_reflections_text(agent_name, limit=3)
# ... LLM이 reflection 생성 (LLM은 Confluence 모름)
confluence_custom.save_reflection(agent_name, day, text, quota, run_id)
```

### 5-2. LLM 연결 — 해당 코드 부분만

`confluence_mcp/llm_personality.py`에서 **MCP 도구를 Deep Agent에 넘기고 호출은 LLM에 위임**.

```python
PROFILE_TIMEOUT_SEC = 90   # OpenAI 응답 stall 방어용 안전망

def create_personality_profile(personality, agent_name, run_id, model,
                               mode="append") -> bool:
    tools = _ensure_init()
    save_profile = tools["save_personality_profile"]   # ← LLM에 노출할 도메인 도구

    profile_agent = create_deep_agent(
        model=f"openai:{model}",
        tools=[save_profile],                           # ← 도구를 LLM에 넘김
        system_prompt=f"""당신은 {personality.name} 성향 에이전트입니다.
            save_personality_profile 도구를 1번 호출해서 자신의 프로필 페이지를 작성하세요.
            인자: personality_name="{personality.name}", agent_name="{agent_name}",
            run_id="{run_id}", mode="{mode}", content는 마크다운 자유 작성.""",
    )
    # asyncio.wait_for로 90초 timeout — 초과 시 본 성향 Profile만 포기하고 시뮬은 계속
    _local.loop.run_until_complete(asyncio.wait_for(
        profile_agent.ainvoke({
            "messages": [{"role": "user", "content": "프로필 페이지를 작성하세요."}]
        }),
        timeout=PROFILE_TIMEOUT_SEC,
    ))
    return True
```

**공식 브랜치와의 핵심 차이**: 공식은 LLM에게 일반 `confluence_create_page`를 줬기 때문에 LLM이 시스템 프롬프트의 규약을 보고 `space_key`, `parent_id`, `content_format`까지 직접 채워야 했음. 이 브랜치는 도메인 도구라 LLM이 **도메인 인자 5개만** 채우면 끝 → 시스템 프롬프트 짧고, LLM 실수 위험 낮음.

> `mode` 값은 시스템 프롬프트에 박혀 LLM이 도구 호출 시 그대로 전달 → 코드 연결과 동일하게 `CONFLUENCE_WRITE_MODE` 한 줄로 통제 가능.

#### 왜 timeout이 필요한가 (운영 경험)

5성향 동시 실행 중 일부 스레드가 OpenAI 응답을 못 받고 멈추는 현상이 관측됨. 원인:

- deepagents는 `"openai:"` prefix 시 [Responses API](https://platform.openai.com/docs/api-reference/responses)를 사용 (SSE 스트림 기반)
- 스트림이 stall되면 TCP 연결은 살아있어 OS가 끊지 않음
- openai SDK 디폴트: read timeout **600초** × max_retries **2회** → 최악 30분 무응답
- 우리 측에 timeout이 없으면 그 스레드 전체가 잠김 (코드 연결은 단일 HTTP 요청이라 이런 stall이 거의 없음)

`asyncio.wait_for`로 90초만 기다리고 포기 → Profile은 못 만들지만 본체 시뮬은 정상 진행.

### 5-3. 비교표

| | **코드 연결** (code-driven) | **LLM 연결** (LLM-driven) |
|---|---|---|
| 누가 도구 호출? | Python `if` 분기 | LLM 추론 |
| 호출 인자값 | 코드가 dict 조립 | LLM이 시스템 프롬프트 보고 생성 |
| 호출 시점 | 코드의 정해진 자리 | LLM이 매 추론마다 판단 |
| 본문 결정 | 코드가 정형 (도메인 도구가 본문 골격 강제) | LLM이 자유 작성 |
| 결과 일관성 | 매번 동일한 형식 | 매번 다른 형식 (맥락 적응) |
| 토큰 비용 | 0 (LLM 호출 안 함) | 시스템 프롬프트 + 도구 스키마 + 응답 |
| 디버깅 | 코드만 보면 됨 | LLM 응답 + tool call trace 함께 |
| 실패 모드 | 네트워크/인증 에러만 | + LLM이 도구 안 부르거나 잘못 부를 수 있음<br/>+ 멀티 에이전트 호출 시 응답 stall 가능 → 클라이언트 timeout 필요 |
| 새 작업 추가 | 코드 수정 필요 | 시스템 프롬프트 수정으로도 가능 |

### 5-4. 어떤 경우에 어떤 방식이 적합한가

**코드 연결이 적합한 경우**
- 호출 시점·인자가 결정적 (예: "Reflection 끝나면 무조건 저장")
- 결과 형식을 통일해야 함 (예: 배치 처리, 데이터 파이프라인)
- 토큰 비용을 0으로 유지하고 싶음
- 검증 가능성·재현성이 중요

**LLM 연결이 적합한 경우**
- 호출 자체가 의사결정 (예: "여러 페이지 중 하나를 골라야 함")
- 본문이 맥락에 따라 달라야 함 (예: 사용자가 읽을 자유 텍스트)
- 입력을 해석한 뒤 동적으로 행동
- 코드로 if/else 작성하기 너무 많은 케이스

### 5-5. 한 시뮬레이션 안에서 두 방식이 같이 동작 (검증됨)

`confluence_mcp/demo_run.py`의 5성향 데모 실행에서 Confluence에 두 종류 페이지가 생성됨:

| `CONFLUENCE_WRITE_MODE` | LLM 연결 (Profile) | 코드 연결 (Reflection) |
|---|---|---|
| `"append"` | `Profile_DeepAgent_{성향}_<run_id>` | `Reflection_DeepAgent_{성향}_Day{NNNN}_<run_id>` |
| `"overwrite"` | `Profile_DeepAgent_{성향}` | `Reflection_DeepAgent_{성향}_Day{NNNN}` |

두 모드 다 같은 `_ensure_init()`을 통해 같은 MCP subprocess(우리 서버)를 공유하므로 추가 비용 없이 양쪽을 함께 쓸 수 있다. 저장 정책(append/overwrite)도 한 줄로 동시 통제됨.

---

## 다른 브랜치

- `main` — 시뮬레이션 본체 + 기존 README
- `feature/mcp-confluence-official` — 외부(커뮤니티) MCP 서버(`mcp-atlassian`)로 같은 use case 구현

두 feature 브랜치 비교:

| | 공식 브랜치 (외부 MCP) | 커스텀 브랜치 (직접 만든 MCP) |
|---|---|---|
| 서버 작성 부담 | 0 (설치만) | 본 프로젝트가 작성·유지 |
| 노출 도구 | 24개 일반 CRUD | 3개 도메인 도구 |
| 클라이언트 코드량 | 많음 (도메인 변환 책임) | 적음 (서버가 도메인 통제) |
| 도구 시그니처 변경 위험 | mcp-atlassian 업데이트에 종속 | 본 프로젝트 통제 |
| 사용 가능 도구 범위 | 24개 다 즉시 활용 가능 | 우리가 정의한 것만 (필요 시 추가) |
| 인증·운영 | 외부 패키지에 위임 | 본 프로젝트 책임 |

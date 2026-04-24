# 외부 MCP 서버로 Confluence 연결하기

---

## 목차

1. [외부 MCP 서버](#1-외부-mcp-서버)
2. [사전 준비](#2-사전-준비)
3. [서비스 흐름과 MCP 추가 지점](#3-서비스-흐름과-mcp-추가-지점)
4. [연결에 필요한 코드](#4-연결에-필요한-코드)
5. [부가: code-driven vs LLM-driven 비교](#5-부가-code-driven-vs-llm-driven-비교)
6. [저장 정책 변경 비용: 외부 MCP vs 직접 만든 MCP](#6-저장-정책-변경-비용-외부-mcp-vs-직접-만든-mcp)

---

## 1. 외부 MCP 서버

### 1-1. 사용 패키지: `mcp-atlassian` 커뮤니티

- 패키지: [sooperset/mcp-atlassian](https://github.com/sooperset/mcp-atlassian) — Python으로 작성된 커뮤니티 MCP 서버
- 설치: `pip install mcp-atlassian`
- 인증: Atlassian **API Token** (사용자 계정 권한 그대로 위임)
- 동작: 우리 프로세스가 `mcp-atlassian`을 **subprocess(stdio transport)**로 띄움 → 같은 프로세스 안에서 통신

### 1-2. 왜 "공식"이 아닌 "커뮤니티" 버전인가

Atlassian이 운영하는 **공식 Remote MCP**(`mcp.atlassian.com/v1/sse`, OAuth 2.1+PKCE)도 존재한다. 그러나 이 프로젝트(Python+LangChain)에서는 직접 못 쓴다:

- LangChain의 MCP 어댑터인 `langchain-mcp-adapters`(Python)가 **OAuth 2.1을 미지원**
- 관련 GitHub 이슈 [#239](https://github.com/langchain-ai/langchain-mcp-adapters/issues/239)가 "not planned"로 close됨

> 차선책으로 같은 Atlassian REST API를 호출해주는 커뮤니티 패키지(`mcp-atlassian`, API Token 인증)를 쓴다. 결과적으로 동일한 작업이 가능하지만, 인증 모델·운영 보장 측면에서 차이가 있다.

### 1-3. `mcp-atlassian`이 노출하는 Confluence 도구 (24개)

본 프로젝트에서는 이 중 `confluence_create_page`, `confluence_get_page_children` 2개만 사용 중.

> 아래 목록은 README 작성 시점 기준. 패키지 업데이트 시 카테고리별 요약 + 상세 스키마를 직접 확인하려면 [confluence_mcp/test_mcp_schema.py](confluence_mcp/test_mcp_schema.py) 실행: `python -m confluence_mcp.test_mcp_schema`

<details>
<summary>전체 도구 목록 펼쳐 보기</summary>

**페이지 조회 (4)**
- `confluence_get_page` — ID 또는 제목+space로 단일 페이지 조회
- `confluence_get_page_children` — 부모 페이지의 자식·폴더 목록 ★
- `confluence_get_space_page_tree` — 스페이스 전체 페이지 트리를 평탄한 리스트로
- `confluence_search` — CQL 또는 자연어 검색

**페이지 생성·수정·삭제·이동 (4)**
- `confluence_create_page` — 새 페이지 생성 ★
- `confluence_update_page` — 기존 페이지 수정
- `confluence_delete_page` — 페이지 삭제
- `confluence_move_page` — 페이지를 다른 부모·스페이스로 이동

**첨부 파일 (6)**
- `confluence_upload_attachment` — 페이지·블로그에 파일 업로드
- `confluence_upload_attachments` — 여러 파일 한 번에 업로드
- `confluence_download_attachment` — 첨부 파일을 임베디드 리소스로 다운로드
- `confluence_download_content_attachments` — 한 페이지의 모든 첨부 한 번에 다운로드
- `confluence_get_attachments` — 페이지·블로그의 첨부 목록 조회
- `confluence_delete_attachment` — 첨부 영구 삭제

**댓글 (3)**
- `confluence_add_comment` — 페이지에 댓글 작성
- `confluence_get_comments` — 페이지의 댓글 조회
- `confluence_reply_to_comment` — 기존 댓글 스레드에 답글

**메타데이터: 라벨·이력·통계 (6)**
- `confluence_add_label` — 페이지·블로그·첨부에 라벨 추가
- `confluence_get_labels` — 라벨 조회
- `confluence_get_page_history` — 특정 버전의 페이지 가져오기
- `confluence_get_page_diff` — 두 버전 간 unified diff
- `confluence_get_page_views` — 페이지 조회수 통계
- `confluence_get_page_images` — 페이지에 첨부된 이미지를 inline content로

**사용자 (1)**
- `confluence_search_user` — Confluence 사용자 검색 (Cloud는 CQL, Server/DC는 group member API)

★ = 본 프로젝트에서 실제 호출 중

</details>

---

## 2. 사전 준비

### 2-1. 의존성

```bash
pip install langchain-mcp-adapters mcp-atlassian python-dotenv deepagents
```

| 패키지 | 역할 |
|---|---|
| `mcp-atlassian` | Atlassian REST API를 MCP 프로토콜로 노출하는 Python 서버 |
| `langchain-mcp-adapters` | MCP 도구를 LangChain `BaseTool`로 변환하는 브릿지 |
| `deepagents` | LangChain 위 Agent 추상화 (LLM-driven에서만 사용) |
| `python-dotenv` | `.env` 로딩 |

### 2-2. 환경변수 (`.env`)

```dotenv
CONFLUENCE_URL=https://atdev-ai.atlassian.net/wiki
CONFLUENCE_USERNAME=<Atlassian 로그인 이메일>
CONFLUENCE_API_TOKEN=<https://id.atlassian.com/manage-profile/security/api-tokens 에서 발급>
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

```

### 3-2. MCP 호출 1회는 어떤 경로를 거치나

도구 1번 호출(예: `save_reflection`) 시 메시지가 거치는 4계층:

```
┌──────────────────────────────────────────┐
│ [A] 애플리케이션 코드 (Python)            │
│     예: tool.ainvoke({"title": ...})     │
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
│ [C] mcp-atlassian subprocess              │
│     MCP 메시지 → Atlassian REST 호출 변환 │
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
| **[C]** mcp-atlassian | MCP ↔ Atlassian REST 변환 서버 (subprocess로 띄움) | sooperset (커뮤니티) |
| **[D]** Confluence | 실제 페이지가 생성되는 곳 | Atlassian |

**핵심 메시지**: 직접 작성한 코드는 [A]뿐이다. [B][C][D]는 모두 설치·가입만 하면 됨. 
즉 "외부 MCP를 끼워 쓰는" 작업의 비용은 **[A]를 작성·유지하는 비용 + [C]가 깔린 환경을 신뢰하는 비용**이다.

### 3-3. MCP 추가로 얻은 것

| 항목 | MCP 추가 전 | MCP 추가 후 |
|---|---|---|
| **데이터 영속성** | 시뮬레이션 결과(에이전트 로그, Reflection 본문 등)가 실행한 머신의 로컬 `logs/` 폴더 안에 `.txt`, `.jsonl` 파일로만 저장된다. 다른 사람과 공유하려면 파일을 직접 전달해야 하고, 머신이 바뀌면 결과도 사라진다. | 같은 결과가 로컬에 저장되는 동시에 Confluence 페이지로도 자동 등록된다. 웹상에 보관되므로 다른 팀원이 브라우저로 즉시 열어볼 수 있고, Confluence 자체 검색 기능으로 과거 결과를 키워드로 찾을 수 있다. |
| **Reflection 컨텍스트** | Reflection이 참고할 수 있는 과거 정보는 같은 시뮬레이션 실행 안에서 누적된 `EpisodicMemory`로 한정된다. 시뮬레이션을 새로 시작하면 메모리가 초기화되어 이전 실행에서 LLM이 만들어낸 처방·통찰을 다음 실행이 이어받을 방법이 없다. | 매 Reflection 직전에 Confluence에 저장된 과거 Reflection 페이지를 `fetch_past_reflections_text()`로 가져와 프롬프트에 주입한다. 이번 실행의 직전 분기뿐 아니라 며칠 전에 돌렸던 별도 실행본의 처방까지 LLM이 읽을 수 있어 분기·실행 단위를 넘어 일관된 전략을 유지할 수 있다. |

---

## 4. 연결에 필요한 코드

### 파일 구성

| 파일 | 역할 |
|---|---|
| [confluence_mcp/confluence_official.py](confluence_mcp/confluence_official.py) | MCP 클라이언트 init + 도구 호출 wrapper |
| [confluence_mcp/llm_personality.py](confluence_mcp/llm_personality.py) | LLM-driven 통합 (5장에서 상세) |
| [main.py](main.py) | 시뮬레이션 본체. 위 모듈 호출 지점만 추가 |

---

### 4-1. `confluence_mcp/confluence_official.py`

#### 〔A〕 MCP 연결 자체에 꼭 필요한 코드 (일반 패턴)


```python
import asyncio, os, threading
from langchain_mcp_adapters.client import MultiServerMCPClient

_local = threading.local()


def _build_subprocess_env() -> dict:
    """MCP subprocess가 필요로 하는 환경변수만 추려서 전달.
    PATH 등 OS 기본 + 우리가 넘기고 싶은 인증 정보."""
    base = {k: v for k, v in os.environ.items()
            if k.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP",
                             "USERPROFILE", "APPDATA", "LOCALAPPDATA"}}
    base.update({
        "CONFLUENCE_URL": os.environ["CONFLUENCE_URL"],
        "CONFLUENCE_USERNAME": os.environ["CONFLUENCE_USERNAME"],
        "CONFLUENCE_API_TOKEN": os.environ["CONFLUENCE_API_TOKEN"],
    })
    return base


def _ensure_init() -> dict:
    """현재 스레드의 MCP 클라이언트가 준비되어 있는지 확인하고 도구 dict를 반환.
    첫 호출 시: subprocess spawn + 도구 메타 로드 (~2-3초). 이후 호출: 캐시 hit."""
    if hasattr(_local, "tools"):
        return _local.tools

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = MultiServerMCPClient({
        "atlassian": {
            "command": "mcp-atlassian",      # PATH의 실행 파일 이름
            "args": [],
            "transport": "stdio",             # subprocess stdin/stdout 통신
            "env": _build_subprocess_env(),
        }
    })
    tool_list = loop.run_until_complete(client.get_tools())

    _local.loop = loop
    _local.client = client
    _local.tools = {t.name: t for t in tool_list}
    return _local.tools
```

**핵심 패턴 3개**

1. **`MultiServerMCPClient`로 subprocess 관리**: `command` + `args` + `transport="stdio"` + `env`만 넘기면 라이브러리가 알아서 띄움
2. **`client.get_tools()`로 도구 동적 로드**: MCP 서버는 자기가 가진 도구를 동적으로 알려줌. 호출 코드는 도구 이름만 알면 됨
3. **스레드별 캐시 (`threading.local`)**: stdio는 thread-safe하지 않으므로 워커 스레드마다 자기 subprocess + asyncio loop를 가져야 함

#### 〔B〕 도구 호출 wrapper 패턴 (일반 패턴)

```python
def _unwrap_text(result) -> str:
    """MCP 응답이 [{type:'text', text:'...'}] 또는 string으로 옴 → string으로 정규화."""
    if isinstance(result, str):
        return result
    if isinstance(result, list):
        return "\n".join(item.get("text", "") if isinstance(item, dict) and item.get("type") == "text"
                         else str(item) for item in result)
    return str(result)


# 도구 호출 패턴 (어떤 도구든 동일):
tools = _ensure_init()
some_tool = tools["confluence_xxx"]
raw = _local.loop.run_until_complete(some_tool.ainvoke({...인자...}))
text = _unwrap_text(raw)
```

- 호출은 항상 **`ainvoke()`** — `langchain-mcp-adapters`가 async만 구현되어 있기 때문.
- 응답 정규화 한 번 거치고 → 이후는 일반 데이터(str/dict) 처리

> "MCP 자체가 sync 불가"가 아니라 **"우리가 쓰는 어댑터가 async-only로 구현되어 있어 우리 코드도 그 전제로 작성됨"**.
어댑터를 바꾸거나 직접 sync wrapper를 만들면 sync 호출도 가능.

---

#### 〔C〕 이 프로젝트에 특화된 부분

**Confluence + 우리 시뮬레이션 도메인**에 맞춰 결정한 값/로직.

##### 상수 설정 (어디에 저장할지)

테스트용 스페이스/페이지 ID. 다른 프로젝트라면 다른 값으로 바꾸면 됨.

```python
PARENT_PAGE_ID = "120520708"   # 모든 결과 페이지를 이 페이지의 자식으로 매단다
SPACE_KEY = "mcptest"
```

##### 사용할 도구 선택 (24개 중 4개)

`mcp-atlassian`이 노출하는 24개 Confluence 도구 중 우리 use case에 필요한 4개:

| 도구 | wrapper 함수 | 우리 도메인 매핑 |
|---|---|---|
| `confluence_create_page` | `save_reflection()` (append) | Reflection 결과를 자식 페이지로 저장 |
| `confluence_get_page_children` | `fetch_past_reflections_text()` | 부모 페이지의 자식들을 가져와 prefix 필터링 |
| `confluence_get_page` | `find_page_id_by_title()` | overwrite 모드에서 같은 제목 페이지가 있는지 확인 |
| `confluence_update_page` | `save_reflection()` (overwrite 분기) | 있으면 본문 덮어쓰기 (버전은 mcp-atlassian이 자동 +1) |

> `confluence_search`는 CQL 인덱싱 지연으로 직후 조회 시 빈 결과를 반환하는 케이스가 있어 `get_page_children`을 선택했다 (디버깅 중 실측). 같은 부모 아래 매다는 구조에서는 자식 조회가 즉시 일관성 보장.

> `CONFLUENCE_WRITE_MODE="overwrite"` 정책 때문에 2개 도구가 추가됐음. **append 모드만 썼을 때는 create 1개로 끝**이었다는 점이 핵심 — 정책 변경이 도구 호출 목록을 바꾼다는 것 자체가 외부 MCP의 특징이다 (6장 참조).

##### 페이지 제목 규약 (우리 도메인)

```
Reflection_{agent_name}_Day{day:04d}[_{run_id}]
예: Reflection_DeepAgent_정치형_Day0090_260423_102135
```

- `Day{day:04d}` 4자리 zero-padding → 문자열 정렬도 시간순 유지
- `run_id`(시뮬레이션 시작 timestamp) suffix → 같은 에이전트로 여러 번 돌려도 제목 충돌 없음
- 조회 시 `Reflection_{agent_name}_Day` prefix만 매칭 → 클라이언트에서 필터링/정렬

##### 저장 함수 (mode 지원)

```python
def save_reflection(agent_name, day, text, quota, run_id=None, mode="append") -> bool:
    tools = _ensure_init()
    title = _build_reflection_title(agent_name, day, run_id, mode)   # append→suffix, overwrite→고정
    body  = build_body(agent_name, day, text, quota)

    # overwrite 모드: 같은 제목 페이지 검색 → 있으면 update, 없으면 create로 fallthrough
    if mode == "overwrite":
        existing_id = find_page_id_by_title(title, tools)   # confluence_get_page 호출
        if existing_id:
            update = tools["confluence_update_page"]
            _local.loop.run_until_complete(update.ainvoke({
                "page_id": existing_id,
                "title": title,
                "content": body,
                "content_format": "markdown",
            }))
            return True

    # append, 또는 overwrite인데 없음 → create
    create = tools["confluence_create_page"]
    _local.loop.run_until_complete(create.ainvoke({
        "space_key": SPACE_KEY, "title": title, "content": body,
        "parent_id": PARENT_PAGE_ID, "content_format": "markdown",
    }))
    return True
```

**mode별 도구 호출 횟수**:
- `append` — 1회 (`create_page`)
- `overwrite` — 최대 2회 (`get_page` → 있으면 `update_page`, 없으면 `create_page`)

`confluence_update_page`에 **version 인자가 없다**는 점이 mcp-atlassian의 편의 — 서버가 알아서 `+1` 처리해준다 (직접 MCP 서버를 만들었다면 우리가 처리해야 했음).

##### 조회 함수 (요지)

```python
def fetch_past_reflections_text(agent_name, limit=3) -> str:
    tools = _ensure_init()
    get_children = tools["confluence_get_page_children"]

    raw = _local.loop.run_until_complete(get_children.ainvoke({
        "parent_id": PARENT_PAGE_ID,
        "limit": 50,
        "include_content": True,
        "convert_to_markdown": True,
    }))
    parsed = json.loads(_unwrap_text(raw))
    children = parsed.get("results", [])

    # 클라이언트 측 필터링 + 정렬 + 본문 추출 (서버는 우리 도메인 모름)
    title_prefix = f"Reflection_{agent_name}_Day"
    matched = []
    for c in children:
        title = c.get("title", "")
        if not title.startswith(title_prefix):
            continue
        day_num = int(title[len(title_prefix):len(title_prefix) + 4])
        body = c.get("content", {}).get("value", "")
        matched.append((day_num, title, body))
    matched.sort(key=lambda x: -x[0])

    return "\n\n---\n\n".join(
        f"[Day {d}] {t}\n{b[:600]}" for d, t, b in matched[:limit]
    )[:3000]
```

서버는 일반 CRUD만 알고 우리 도메인을 모르므로 **prefix 매칭, day 번호 파싱, 정렬, 본문 추출, 길이 제한**을 클라이언트가 다 한다.

---

### 4-2. `main.py` 통합 지점

**(1) import** — 모듈 1개 추가:

```python
from confluence_mcp import confluence_official
```

**(2) 상단 플래그** — on/off + 저장 정책:

```python
USE_CONFLUENCE        = True         # confluence 연결 on/off
USE_LLM_PROFILE       = True         # LLM-driven 프로필 on/off
CONFLUENCE_WRITE_MODE = "overwrite"  # "append" | "overwrite" — 코드/LLM 양쪽 동시 적용
```

**(3) `_run_one()` 안의 Reflection 블록 전후** — 기존 코드에 끼워넣음:

```python
# Reflection 직전: 과거 기록 fetch → 프롬프트 주입
if USE_CONFLUENCE:
    past_text = confluence_official.fetch_past_reflections_text(
        agent_name, limit=PAST_REFLECT_LIMIT,
    )
    if past_text:
        past_reflections_section = f"\n[ 과거 Reflection 기록 (Confluence) ]\n{past_text}\n"

reflection_text = reflection_agent.invoke(...)   # 기존 코드

# Reflection 직후: 결과 저장
if USE_CONFLUENCE:
    confluence_official.save_reflection(
        agent_name=agent_name, day=day,
        text=reflection_text, quota=action_quota,
        run_id=timestamp,
        mode=CONFLUENCE_WRITE_MODE,   # ← 한 줄로 정책 통제
    )
```

---

## 5. 부가: code-driven vs LLM-driven 비교

### 5-1. CODE 연결 (code-driven)

`main.py`의 Reflection 블록에서 **코드가 직접 도구를 호출**

기본 제공 도구를 감싸서 함수 생성
- fetch_past_reflections_text : confluence_get_page_children
- save_reflection : confluence_create_page

```python
# 코드가 시점·인자를 결정 → tool.ainvoke()로 직접 호출
past_text = confluence_official.fetch_past_reflections_text(agent_name, limit=3)
# ... LLM이 reflection 생성 (LLM은 Confluence 모름)
confluence_official.save_reflection(agent_name, day, text, quota, run_id)
```

### 5-2. LLM 연결 (LLM-driven)

`confluence_mcp/llm_personality.py`에서 **MCP 도구를 Deep Agent에 넘기고 호출은 LLM에 위임**. mode 분기는 코드가 책임지고(외부 MCP는 도메인 도구가 없어서), LLM에는 **선택된 도구 1개만** 노출.

```python
PROFILE_TIMEOUT_SEC = 90   # OpenAI Responses API stall 방어

def create_personality_profile(personality, agent_name, run_id, model, mode="append") -> bool:
    tools = _ensure_init()
    title = f"Profile_{agent_name}_{run_id}" if mode == "append" else f"Profile_{agent_name}"

    # overwrite 모드면 코드가 먼저 검색 → 결과에 따라 update 도구만 / create 도구만 노출
    existing_id = find_page_id_by_title(title, tools) if mode == "overwrite" else None

    if existing_id:
        exposed_tool = tools["confluence_update_page"]
        tool_instruction = (f'confluence_update_page를 1번 호출. '
                            f'page_id="{existing_id}", title="{title}", content_format="markdown".')
    else:
        exposed_tool = tools["confluence_create_page"]
        tool_instruction = (f'confluence_create_page를 1번 호출. '
                            f'space_key="{SPACE_KEY}", parent_id="{PARENT_PAGE_ID}", '
                            f'title="{title}", content_format="markdown".')

    profile_agent = create_deep_agent(
        model=f"openai:{model}",
        tools=[exposed_tool],                         # ← LLM은 모드 분기를 모름
        system_prompt=f"""당신은 {personality.name} 성향의 에이전트입니다.
            {tool_instruction}
            본문은 마크다운으로 자유 작성.""",
    )

    # langchain-mcp-adapters가 async-only → ainvoke + 90초 timeout (응답 stall 방어)
    _local.loop.run_until_complete(asyncio.wait_for(
        profile_agent.ainvoke({
            "messages": [{"role": "user", "content": "프로필 페이지를 작성하세요."}]
        }),
        timeout=PROFILE_TIMEOUT_SEC,
    ))
    return True
```

두 가지 주의할 점:

1. **mode 분기를 코드가 가져간 이유** — LLM에게 "update 도구와 create 도구를 다 주고, overwrite 모드면 먼저 get_page로 찾고 있으면 update, 없으면 create" 같은 절차를 지시할 수도 있지만, 실수 위험이 커진다. 외부 MCP는 도메인 도구가 없어서 **정책 분기를 어디든 누가 책임져야** 하고, 코드가 가져가면 LLM은 1개 도구만 보므로 실수 표면이 줄어든다.
2. **`asyncio.wait_for(timeout=90)`** — deepagents는 `"openai:"` prefix 시 Responses API를 사용하는데, SSE 스트림이 stall되면 openai SDK 디폴트(read 600s × retry 2회)로 최대 30분 무응답. 90초에 포기하고 본체 시뮬만 계속.

### 5-3. 비교표

| | **코드 연결** (code-driven) | **LLM 연결** (LLM-driven) |
|---|---|---|
| 누가 도구 호출? | Python `if` 분기 | LLM 추론 |
| 호출 인자값 | 코드가 f-string으로 조립 | LLM이 시스템 프롬프트의 규약을 보고 생성 |
| 호출 시점 | 코드의 정해진 자리 | LLM이 매 추론마다 판단 |
| 본문 결정 | 코드가 정형으로 (f-string) | LLM이 자유 작성 |
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
- 입력을 해석한 뒤 동적으로 행동 (예: 사용자 채팅에 반응)
- 코드로 if/else 작성하기 너무 많은 케이스

---

## 6. 저장 정책 변경 비용: 외부 MCP vs 직접 만든 MCP

이 브랜치와 직접 만든 MCP 서버 브랜치([`feature/mcp-confluence-custom`](https://github.com/LXXDJ/2603PJ_AIsimulation/tree/feature/mcp-confluence-custom))는 같은 use case(Reflection 저장/조회) + 같은 `CONFLUENCE_WRITE_MODE="overwrite"` 정책을 구현한다. **정책을 추가했을 때 코드가 어디가 얼마나 바뀌는가**가 두 브랜치의 본질적 차이를 가장 잘 드러낸다.

### 6-1. 같은 정책, 다른 위치

`mode="overwrite"`(같은 제목이면 덮어쓰기) 정책을 추가하려면 "같은 제목 페이지를 찾고, 있으면 update, 없으면 create"라는 분기가 필요하다. 이 분기를 **어디에 둘 수 있는가**가 다르다.

| | 이 브랜치 (외부 MCP) | 직접 만든 MCP |
|---|---|---|
| 분기 위치 | **클라이언트 wrapper** (찾아야 할 도구가 분리됨) | **서버 내부 `_upsert()` 헬퍼** |
| 이유 | mcp-atlassian이 일반 CRUD만 노출 → 도메인 도구 없음 → 조합 책임을 클라이언트가 짐 | 우리 서버에 `save_reflection(mode=...)` 도메인 도구 있음 → 서버가 분기 |
| 클라이언트가 호출하는 MCP 도구 | mode에 따라 **1~2개** (`get_page` → `update_page` 또는 `create_page`) | 항상 1개 (`save_reflection`) |

### 6-2. 코드 연결(code-driven) 변경 비교

- **이 브랜치**: `save_reflection()` wrapper에 `if mode == "overwrite": get_page → existing_id 있으면 update_page, 없으면 create_page`. 호출 측 분기와 도구 2~3개 조합 필요.
- **직접 만든 MCP**: `save_reflection(mode="overwrite")` 호출 한 줄. 분기는 서버의 `_upsert`가 처리.

**결과**: 이 브랜치는 클라이언트 wrapper 코드량이 늘어남 + MCP 호출 횟수 늘어남(overwrite 모드 1건 저장당 최대 2회). 직접 만든 MCP는 클라이언트 변경 0, 호출 횟수 1.

### 6-3. LLM 연결(LLM-driven) 변경 비교

이쪽이 차이가 더 크다.

- **이 브랜치**: LLM에게 도구 2개(create/update)를 주고 "overwrite면 먼저 찾아보고..."라고 지시할 수도 있지만 **LLM 실수 위험**이 커진다. 안전한 설계는 **코드가 먼저 `find_page_id_by_title()`로 검색 → 결과에 따라 update 또는 create 도구만 LLM에 노출**하는 것. 즉 외부 MCP에서는 **LLM-driven이라도 코드가 정책 분기를 책임**지게 된다.
- **직접 만든 MCP**: LLM에게 도메인 도구 `save_personality_profile`만 노출하고 mode 인자를 프롬프트에 박으면 끝. 분기는 서버 내부에서 처리되므로 LLM은 모드 존재 자체를 몰라도 됨.

**결과**: 이 브랜치는 LLM 연결이라 해도 "LLM의 자율성"이 현실적으로 제한됨 (분기를 코드가 가져가야 안전). 직접 만든 MCP는 LLM이 실제로 도메인 인자만 채우고 서버가 나머지를 처리하는, 이상적 형태에 가까움.

### 6-4. 한 줄 요약

> 외부 MCP는 정책을 "도구 호출 시퀀스"로 번역해 클라이언트가 실행한다.
> 직접 만든 MCP는 정책을 "서버 함수 인자 1개"로 표현한다.
>
> 정책이 몇 개 안 되고 안정적일 때는 외부 MCP의 비용이 작다. 정책이 늘어나거나 자주 바뀌면 직접 만든 MCP의 "서버가 도메인을 안다"는 장점이 복리로 커진다.


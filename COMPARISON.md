# MCP 외부 사용 vs 직접 구현 — 통합 비교 가이드

---

## 1차. 기획자 관점 — 외부 MCP vs 직접 구현

### 1-1. 한 줄 요약

> 호출자에 **LLM이 있거나** 여러 클라이언트·언어가 **같은 도메인을 공유**해야 함 → **직접 구현**.
> 둘 다 부재 → **외부 MCP**.

|  | 외부 MCP | 직접 구현 |
|---|---|---|
| 시작까지 시간 | **설치 즉시** | 서버 설계·작성 |
| 누가 도메인 변환을 하나 | 호출 측 코드 (매번) | 서버 안 **(한 번 정의)** |
| 외부 변경에 대한 노출 | 도구 시그니처 변경에 종속 | 본 프로젝트가 통제 |
| 운영 책임 | 외부 패키지에 위임 | 본 프로젝트 |

> **도메인 변환** : 본 프로젝트의 도메인 언어와 Confluence의 일반 저장소 언어가 달라, 서로 소통하기 위한 번역 과정

### 1-2. 외부 MCP를 쓸 때

#### 장점

- **즉시 시작.** `pip install` 한 번이면 도구가 다 준비됨. 본 프로젝트의 [`mcp-atlassian`](https://github.com/sooperset/mcp-atlassian)은 24개 Confluence/Jira 도구를 즉시 노출.
- **도구 풀이 넓음.** 당장 안 쓰는 도구도 나중에 use case가 생기면 그대로 활용 가능.
- **외부 시스템 API 변경에 직접 대응 불필요.** Atlassian REST API가 변해도 mcp-atlassian 메인테이너가 따라감. (우리는 패키지 업데이트만 제때 하면 됨)
- **인증·운영 위임.** 환경변수 전달 규약만 맞추면 끝.

#### 단점

- **도메인 변환을 호출 측이 떠안음.** 외부 MCP는 일반 CRUD만 안다. 프로젝트의 특성은 모름 (ex. Reflection이 뭔지, 이 프로젝트의 페이지 제목 규약이 뭔지) → 호출할 때마다 변환 필요
- **외부 도구 시그니처 변경 위험.** 패키지 업데이트로 인자 이름이 바뀌면 우리 호출 코드가 깨짐.
- **외부 MCP 대응 지연 시 우리도 막힘.** Atlassian API가 변경됐는데 mcp-atlassian이 빨리 따라가지 않으면 우리 호출 코드도 깨진 채로 기다려야 함. (외부 메인테이너 일정에 우리 일정 종속)
- **응답 형식이 도구마다 일관되지 않음.** mcp-atlassian의 24개 도구가 응답을 plain text / JSON 문자열 / 리스트 등 서로 다른 모양으로 반환 → 도구마다 파싱 코드가 따로 필요.
- **LLM에 노출 시 프롬프트 비대화.** LLM에게 일반 `confluence_create_page`를 주려면 시스템 프롬프트로 `space_key`, `parent_id`, 제목 prefix 규약 등을 다 가르쳐야 함. LLM이 헷갈릴 여지가 늘어남.

#### 쓸 수 있는 전제

- 신뢰할 수 있는 외부 패키지가 존재하고 활발히 유지되고 있어야 함.
- 그 패키지가 우리 use case의 80% 이상을 커버해야 함.
- 호출자가 코드뿐이어야 함 (LLM이 호출자면 LLM은 Python helper를 못 봄 → 직접 MCP 필요).
- 단일 프로젝트 안에서만 호출하면 됨 (다른 언어·팀이 같은 도메인으로 호출해야 하면 직접 MCP가 표준 인터페이스 역할).

### 1-3. 직접 구현할 때

#### 장점

- **LLM 호출자에게 도메인 도구를 그대로 노출 가능.** Python helper는 코드 호출자에게만 보이고 LLM은 MCP 도구만 봄. 직접 구현하면 LLM도 도메인 인자(`agent_name`, `day`)만 다루면 되고 `space_key`/`parent_id` 같은 인프라 인자를 LLM에 가르칠 필요 없음.
- **호출 측 코드가 짧음.** 변환·필터링·정렬이 다 서버 안에 구현.
- **도구 시그니처를 본 프로젝트가 통제.** 외부 변경에 흔들리지 않음. 시그니처를 우리 도메인 진화에 맞춰 고칠 수 있음.
- **LLM에 안전하게 노출.** 도메인 도구는 LLM이 채울 인자가 적어 실수 가능성이 낮음.
- **불필요한 도구가 LLM 컨텍스트에 안 노출됨.** 외부 MCP는 24개를 모두 알려야 하는 경우가 많고, LLM이 잘못된 도구를 고를 위험. 직접 구현은 use case에 필요한 도구만.
- **저장 정책 같은 횡단 관심사를 서버에 응집할 수 있음.** 본 프로젝트에서 `CONFLUENCE_WRITE_MODE` 같은 정책이 도구 1개의 인자 1개로 통제됨. 외부 MCP에선 정책 분기를 호출 측이 매번 작성해야 했음.

#### 단점

- **초기 작성 비용.** 본 프로젝트의 경우 MCP 서버 약 300줄(서버 본체 + REST 클라이언트). 단순한 use case에는 과한 투자일 수 있음.
- **외부 시스템 API 변경에 직접 대응 필요.** Atlassian REST API가 변경되면 우리 코드도 직접 수정·테스트·배포해야 함 (외부 MCP 사용 시엔 mcp-atlassian이 대신 처리).
- **새 use case 생기면 서버에 도구 추가 필요.** 외부 MCP는 24개 중 골라 쓰지만, 직접 구현은 만든 것만 있다.
- **인증·운영 직접 책임.** 환경변수, 토큰 갱신, 에러 처리, 재시도 정책 모두 우리가.

#### 쓸 수 있는 전제

- 호출자 중에 LLM이 있고 도메인 도구로 안전하게 노출하고 싶을 때.
- 또는 여러 언어·팀이 같은 도메인 인터페이스를 공유해야 할 때.
- 호출 빈도가 높거나, 같은 도메인 도구가 여러 지점에서 쓰여야 서버 작성 비용 회수.

### 1-4. 어떤 케이스에 무엇이 적합한가

> **흔한 오해**: "도메인이 복잡하면 직접 구현해야 한다"
> 아니다. 복잡함은 Python helper에 응집해도 해결됨. 직접 MCP 서버가 필요한 결정 조건은 **LLM 호출자** / **다중 클라이언트·언어 공유** 두 가지뿐.
> 현실에서는 **외부 MCP + Python helper** 조합이 더 흔함 — Slack, Notion, GitHub, Atlassian 등 주요 SaaS는 이미 외부 MCP 서버가 존재.

#### 시나리오 A — 외부 MCP가 명확히 유리

> **"사내 위키에 가끔 페이지 만들기"** 같은 PoC

- 호출 지점 1~2곳, 도메인 규약 약함, 빨리 보여주는 게 목적
- 직접 구현하면 서버 작성 시간 > 절약되는 호출 측 코드
- → **외부 MCP**

> **여러 외부 시스템 1번씩 통합 (Slack 알림 + Jira 코멘트 + GitHub 이슈)**

- 시스템마다 직접 만들면 서버 N개 작성·유지
- 각 시스템마다 호출 1~2회면 도메인 변환 비용 작음
- → **외부 MCP들 조합**

#### 시나리오 B — 직접 구현이 명확히 유리

> **호출자에 LLM이 포함됨**

- LLM은 Python helper를 못 보고 MCP 도구만 봄 → 도메인 도구로 노출하려면 직접 MCP 서버 필요.
- 일반 도구(`confluence_create_page`)를 LLM에 주면 인자 빠뜨림·잘못된 값 입력 위험. 도메인 도구는 LLM이 채울 표면적이 작아 실수 가능성 낮음.
- 본 프로젝트의 LLM-driven Profile 작성이 이 케이스 — 성향 5개가 시뮬 시작마다 자기 프로필을 작성. 코드 호출자(Reflection 저장)도 같은 MCP 서버를 공유해 **코드+LLM 양쪽이 같은 도메인 규약 위에서 일관**.
- → **직접 구현**

> **여러 클라이언트·언어·팀이 같은 도메인 인터페이스를 공유해야 함**

- Python helper는 Python 프로젝트 한정 — TypeScript 서비스, 다른 팀 스크립트, 별도 LLM 에이전트는 못 씀.
- 직접 MCP 서버는 표준 프로토콜 → 언어·프로젝트 무관하게 같은 도메인 도구 호출.
- 사내 표준 도메인 어댑터를 한 곳에서 관리하고 싶을 때.
- → **직접 구현**

#### 시나리오 C — 케이스에 따라 갈림

> **외부 패키지가 있긴 한데 핵심 기능 일부가 빠져있음**

- 빠진 기능이 단순 → **외부 사용 + wrapper에서 우회** (도구 여러 개를 조합하거나 호출 전후로 로직 추가)
- 빠진 기능이 핵심 흐름이거나 우회 코드가 50줄 이상 / 여러 곳에서 반복 → **직접 구현**

> **외부 패키지가 활발하지 않음 (마지막 커밋 1년 전)**

- 우리 use case가 안정적이라면 → **외부 사용** (변경 위험 자체가 낮음)
- 외부 시스템 API가 자주 바뀐다면 → **직접 구현** (외부 패키지 멈춤이 우리 멈춤이 됨)

---

## 2차. 개발자 관점 — 코드 레벨에서의 차이

### 2-1. 외부 MCP를 쓰는 경우

#### 설치할 의존성

```bash
pip install mcp-atlassian langchain-mcp-adapters python-dotenv deepagents
```

| 패키지 | 역할 | 필수 여부 |
|---|---|---|
| `mcp-atlassian` | Atlassian REST를 MCP로 노출하는 외부 패키지 (24개 도구) | 필수 |
| `langchain-mcp-adapters` | MCP 도구를 LangChain `BaseTool`로 래핑 | LangChain(deepagents) 기반이라 필수. OpenAI SDK 직접 쓴다면 불필요 |
| `deepagents` | LLM-driven 패턴에서만 필요 | code-driven만 한다면 생략 가능 |
| `python-dotenv` | `.env` 로딩 | 보통 필수 |

#### 작성해야 하는 파일 (본 프로젝트 official 브랜치 기준)

| 파일 | 줄 수 | 역할 |
|---|---|---|
| `confluence_mcp/confluence_official.py` | **261** | wrapper — init + 도메인 변환 + 도구 호출 |
| `confluence_mcp/llm_personality.py` | 126 | LLM-driven Profile 통합 |
| `main.py` 변경분 | ~10 | flag + import + 호출 지점 2곳 |
| **합계 (직접 작성)** | **~400줄** | 서버 코드는 0줄 (외부 패키지에 위임) |

#### 사전 준비

- Atlassian API Token 발급 ([id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens))
- 환경변수 3개: `CONFLUENCE_URL`, `CONFLUENCE_USERNAME`, `CONFLUENCE_API_TOKEN`
- Confluence space + 부모 페이지 미리 생성 → `space_key`, `parent_page_id` 코드 상수에 박음

#### 알아야 할 것

1. **응답 형식이 도구마다 다름.** plain string / JSON 문자열 / list 등 혼재. `_unwrap_text` 같은 정규화 함수가 사실상 필수.
2. **응답 안에 또 JSON 문자열.** `confluence_get_page` 같은 도구는 `text` 필드 안에 JSON 문자열을 넣어 반환 → `json.loads` 한 번 더.
3. **`confluence_search`는 신뢰성 낮음.** CQL 인덱싱 지연으로 직후 조회 시 빈 결과 가능. 부모-자식 관계 만들고 `confluence_get_page_children` 사용이 안전.
4. **`confluence_update_page`가 version 자동 처리.** Atlassian REST의 낙관적 락(`version+1`)을 mcp-atlassian이 내부에서 처리. 호출 측은 신경 쓸 필요 없음. (직접 구현 시엔 우리가 처리)
5. **24개 도구 중 어떤 걸 쓸지는 사람이 결정.** `client.get_tools()`로 dynamic하게 받지만 선택은 직접. 본 프로젝트는 4개만 사용 (`create_page`, `update_page`, `get_page`, `get_page_children`).

---

### 2-2. 직접 만드는 경우

#### 설치할 의존성

```bash
pip install fastmcp httpx langchain-mcp-adapters python-dotenv deepagents
```

| 패키지 | 역할 |
|---|---|
| `fastmcp` | MCP 서버 작성 프레임워크 (데코레이터 기반) |
| `httpx` | 서버 안에서 Atlassian REST 직접 호출 |
| `langchain-mcp-adapters` | (외부 MCP와 동일) |
| `deepagents` | (외부 MCP와 동일) |
| `python-dotenv` | (외부 MCP와 동일) |

→ `mcp-atlassian`이 빠지고 `fastmcp + httpx`로 대체. 나머지는 동일.

<details>
<summary><strong>📦 MCP 서버 프레임워크 선택지 (Python 기준)</strong></summary>

본 프로젝트는 FastMCP를 골랐지만, 그 외 선택지도 있다.

| 프레임워크 | 패키지 | 특징 | 적합한 경우 |
|---|---|---|---|
| **FastMCP (별도 패키지)** ⭐ | `pip install fastmcp` | jlowin이 만든 가장 인기 있는 Python 프레임워크. FastAPI 스타일 데코레이터 (`@mcp.tool`). **본 프로젝트 사용**. 2.x에서 client/server 통합, OpenAPI 변환 등 풍부한 기능 | 빠르게 작성, 기능 풍부 우선 |
| **공식 SDK 내장 FastMCP** | `pip install mcp` → `from mcp.server.fastmcp import FastMCP` | 같은 API지만 **Anthropic 공식 SDK에 흡수된 버전**. 안정성·호환성 우선 | 외부 의존성 줄이고 공식만 쓰고 싶을 때 |
| **공식 SDK low-level** | `pip install mcp` → `from mcp.server import Server` | 데코레이터 없이 핸들러 클래스 직접 등록. JSON-RPC 라우팅·request 처리 모두 우리가. **가장 verbose하지만 가장 자유롭다** | 표준에서 벗어난 커스터마이징 많을 때 |

> 셋 다 같은 MCP 프로토콜이라 클라이언트(`langchain-mcp-adapters` 등) 입장에서는 **구분 불가**. 작성 편의 차이만.

##### 같은 도구 등록을 세 방식으로

```python
# FastMCP / 공식 내장 FastMCP — 동일
@mcp.tool()
def save_reflection(agent_name: str, day: int, text: str) -> dict:
    return {...}

# 공식 SDK low-level
class MyServer(Server):
    @list_tools()
    async def list_tools(self):
        return [Tool(name="save_reflection", inputSchema={...})]
    @call_tool()
    async def call_tool(self, name, arguments):
        if name == "save_reflection":
            return [TextContent(type="text", text=...)]
```

본 프로젝트가 FastMCP를 고른 이유: 도구 3개만 있어 데코레이터 한 줄이 가장 깔끔.

##### 다른 언어 (참고)

| 언어 | 주요 옵션 | 특징 |
|---|---|---|
| TypeScript / Node.js | `@modelcontextprotocol/sdk` (공식) | 가장 활발한 또 다른 생태계 |
| Java | 공식 SDK + Spring AI MCP | 엔터프라이즈, Spring 프로젝트라면 자연스러움 |
| C# | 공식 .NET SDK | Microsoft 적극 지원, Semantic Kernel 통합 |
| Kotlin | 공식 SDK | JetBrains·안드로이드 |
| Go / Rust | 커뮤니티 (`mcp-go`, `rmcp` 등) | 공식 없음 |

##### 보너스 — 디버깅·운영 도구

| 도구 | 용도 |
|---|---|
| `mcp-inspector` | 만든 MCP 서버를 GUI로 디버깅 — 도구 호출 테스트 |
| `mcp-proxy` | stdio ↔ SSE/HTTP 프로토콜 변환 |
| Smithery | MCP 서버 레지스트리 + 설치 CLI (npm 같은 역할) |

</details>

<details>
<summary><strong>🔌 어댑터(langchain-mcp-adapters)의 역할</strong></summary>

본 프로젝트가 LangChain 기반(deepagents)이기 때문에 필요한 다리(bridge). MCP 자체 요구사항은 아니다 — OpenAI SDK나 직접 구현이라면 어댑터 없이도 가능.

##### 하는 일 2가지

| 단계 | 무엇 | 기술적으로 |
|---|---|---|
| ① **생성 (도구 발견)** | MCP 서버에 `tools/list` 요청 → 각 도구를 LangChain `BaseTool` 인스턴스로 래핑 | JSON Schema → Pydantic 모델 자동 변환. `client.get_tools()` 한 번이면 dict로 받음 |
| ② **호출 (도구 실행)** | LangChain의 `tool.ainvoke({...})` → MCP `tools/call` JSON-RPC 메시지로 직렬화 → 서버 전송 → 응답 파싱 | async-only — sync 호출 안 됨 |

##### 외부 MCP / 직접 구현 양쪽에서 동일하게 동작

서버를 직접 만들든 외부 패키지(`mcp-atlassian`)를 쓰든 MCP 프로토콜은 같음. 어댑터는 **같은 것 하나로 양쪽 모두에 사용 가능**.

```python
# 외부 MCP 서버 등록
client = MultiServerMCPClient({"atlassian": {
    "command": "mcp-atlassian", "args": [],
    "transport": "stdio", "env": {...},
}})

# 직접 만든 MCP 서버 등록 — command만 다름
client = MultiServerMCPClient({"confluence_custom": {
    "command": sys.executable,
    "args": ["-m", "confluence_mcp_server.server"],
    "transport": "stdio", "env": {...},
}})

# 이후 사용법은 완전 동일
tools = await client.get_tools()
result = await tools["save_reflection"].ainvoke({...})
```

##### 어댑터를 안 쓰는 경우

- **OpenAI SDK + tool calling 직접 구현**: MCP 서버에 직접 JSON-RPC 메시지를 보내고 OpenAI tool schema로 변환하는 코드를 직접 작성
- **MCP 클라이언트 라이브러리 (예: 공식 `mcp` 클라이언트)**: LangChain을 안 쓰면 더 가벼운 클라이언트 사용 가능

LangChain/deepagents 생태계 안에 있다면 어댑터가 가장 단순한 길.

</details>

#### 작성해야 하는 파일 (본 프로젝트 custom 브랜치 기준)

| 파일 | 줄 수 | 역할 |
|---|---|---|
| **서버 측** | | |
| `confluence_mcp_server/server.py` | 198 | FastMCP 서버 + 도메인 도구 3개 정의 |
| `confluence_mcp_server/confluence_client.py` | 105 | Atlassian REST `httpx` wrapper |
| **클라이언트 측** | | |
| `confluence_mcp/confluence_custom.py` | **148** | 우리 서버를 subprocess로 띄우는 wrapper (얇음) |
| `confluence_mcp/llm_personality.py` | 93 | LLM-driven Profile 통합 |
| `main.py` 변경분 | ~10 | flag + import + 호출 지점 2곳 |
| **합계 (직접 작성)** | **~554줄** | 외부 MCP 대비 **+150줄** (서버 보일러플레이트) |

#### 사전 준비

- Atlassian API Token 발급 (외부 MCP와 동일)
- 환경변수 3개 (외부 MCP와 동일)
- `space_key`, `parent_page_id`를 **서버 상수에 박음** → 호출 측에선 보이지 않음 (도메인 통제권 서버로)

#### 알아야 할 것

1. **FastMCP 데코레이터.** `@mcp.tool()`만 붙이면 함수 시그니처가 MCP 도구 스펙으로 자동 노출. 인자 타입 힌트 → JSON Schema 변환.
2. **stdio transport.** `mcp.run()`이 stdin/stdout으로 MCP 메시지 listen → 클라이언트가 `subprocess`로 띄움. HTTP 서버 띄울 필요 없음.
3. **REST 호출은 직접 구현.** Atlassian의 낙관적 락(`version+1`), 응답 구조 변환, 에러 처리 모두 우리 책임. (외부 MCP는 mcp-atlassian이 다 처리)
4. **응답 모양은 우리가 결정.** 도메인 dict 그대로 return → 클라이언트 wrapper의 unwrap이 단순해짐.
5. **호출 측 wrapper가 얇아짐.** 외부 MCP 261줄 → custom 148줄. 도메인 로직이 서버로 이동했기 때문.

---

### 2-3. 어디에 얼마나 — 한눈에 비교

```
┌───────────────────────── 외부 MCP ─────────────────────────┐
│                                                            │
│  [클라이언트 측 — 261줄]                                      │
│   confluence_official.py                                   │
│     ├─ _ensure_init             (subprocess + 도구 캐시)    │
│     ├─ _build_subprocess_env    (인증 환경변수)              │
│     ├─ _unwrap_text             (응답 정규화 — 도구마다 다름) │
│     ├─ _build_reflection_title  (도메인: 제목 규약)          │
│     ├─ find_page_id_by_title    (도메인: 검색)              │
│     ├─ save_reflection          (도메인: 저장 + mode 분기)   │
│     └─ fetch_past_reflections_text (도메인: 필터/정렬)      │
│                                                            │
│  [서버 측 — 0줄] ← 외부 패키지에 위임                          │
│                                                            │
└────────────────────────────────────────────────────────────┘

┌──────────────────────── 직접 구현 ─────────────────────────┐
│                                                            │
│  [클라이언트 측 — 148줄]                                      │
│   confluence_custom.py                                     │
│     ├─ _ensure_init             (subprocess + 도구 캐시)    │
│     ├─ _build_subprocess_env    (인증 환경변수)              │
│     ├─ _unwrap_text             (응답 정규화 — 단순)         │
│     ├─ save_reflection wrapper  (서버에 도메인 인자만 위임)   │
│     └─ fetch_past_reflections_text wrapper                 │
│                                                            │
│  [서버 측 — 303줄]                                           │
│   server.py                                                │
│     ├─ @mcp.tool save_reflection         (도메인 + _upsert) │
│     ├─ @mcp.tool fetch_past_reflections  (도메인)           │
│     ├─ @mcp.tool save_personality_profile (LLM-driven용)   │
│     └─ _build_reflection_title, _upsert  (도메인 헬퍼)      │
│   confluence_client.py                                     │
│     ├─ _request                 (httpx 공통 래퍼)           │
│     ├─ create_page              (POST /content)            │
│     ├─ update_page              (PUT — version+1 처리)     │
│     └─ find_page_by_title       (GET /content?title=...)   │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

**한눈에 보이는 차이**: 같은 도메인 로직(`_build_reflection_title`, `find_page_*`, mode 분기 등)이 외부 MCP에선 클라이언트에, 직접 구현에선 서버에 살고 있다. **위치만 다르고 양은 비슷** — 사실 직접 구현이 +150줄 더 많음 (서버 boilerplate). 단순 코드량으로는 외부 MCP가 유리한데, 1차에서 정리한 결정 조건(LLM 호출자 / 다중 공유)이 그 +150줄을 정당화한다.

---

### 2-4. 양쪽의 공통 / 고유 항목

#### 2-4-1. 양쪽 공통으로 들어가는 것 (MCP 보일러플레이트)

이 보일러플레이트가 양쪽 wrapper의 절반 가까이를 차지함 — **MCP 자체의 비용**이지 두 방식 간 차이는 아님.

| 구성 | 무엇 | 왜 필요한가 |
|---|---|---|
| `MultiServerMCPClient` | subprocess spawn + 도구 등록 | langchain-mcp-adapters가 제공하는 표준 client |
| `client.get_tools()` | 도구 메타데이터 동적 로드 | 서버가 어떤 도구를 가졌는지 모를 수도 있음 (런타임 확인) |
| `tool.ainvoke({...})` | 도구 호출 (async only) | 어댑터가 async-only |
| `threading.local()` 캐시 | 워커 스레드마다 자기 subprocess + loop | stdio는 thread-safe 아님 |
| `asyncio.new_event_loop()` | 스레드별 새 loop | async 호출용 |
| `_unwrap_text` 정규화 | `[{type:'text', text:'...'}]` → string | MCP 프로토콜 표준 wrapper |
| `_build_subprocess_env` | 환경변수 명시 전달 | subprocess는 부모 env 자동 상속 안 함 |
| `python-dotenv` | `.env` 로딩 | 양쪽 다 Atlassian API Token 사용 |

#### 2-4-2. 각 방식 고유의 것

같은 use case라도 한쪽에만 존재하거나, 모양이 본질적으로 다른 항목들.

| 항목 | 외부 MCP 전용 | 직접 구현 전용 |
|---|---|---|
| 추가 의존 패키지 | `mcp-atlassian` | `fastmcp` + `httpx` |
| 작성 위치 | 클라이언트만 (~400줄) | 클라이언트 + 서버 (~554줄) |
| 도메인 변환 코드 | 클라이언트 wrapper 안에 흩어짐 | 서버 `@mcp.tool` + 헬퍼에 응집 |
| `mode="overwrite"` 분기 | wrapper에서 `find_page` → `update`/`create` 명시 | 서버 `_upsert` 헬퍼 한 곳에서 처리 |
| Atlassian REST 디테일 | mcp-atlassian이 처리 (`version+1`, 인증 등) | `confluence_client.py`에서 직접 처리 |
| 응답 파싱 복잡도 | 높음 — 도구마다 형식(string/JSON/list) 다름 | 낮음 — 우리가 dict 모양 결정 |
| 도구 시그니처 통제권 | 외부 (mcp-atlassian 업데이트 위험) | 본 프로젝트 통제 |
| LLM에 노출되는 도구 | 일반 CRUD (`confluence_create_page`) — 인프라 인자 가르쳐야 | 도메인 도구 (`save_reflection`) — 인자 5개로 끝 |
| 새 도구 추가 비용 | mcp-atlassian이 이미 가졌으면 0, 없으면 우회 작성 | 서버 코드에 `@mcp.tool` 함수 추가 |

---

<details>
<summary><strong>⚠️ 부록: 양쪽 다 빠지기 쉬운 운영 함정 — 펼쳐 보기</strong></summary>

비교의 본질에서는 벗어나지만, 두 방식 다 마주칠 가능성이 높은 운영 디테일.

#### ① async-only

`langchain-mcp-adapters`가 async-only. sync 호출 안 됨. → 워커 스레드마다 `asyncio.new_event_loop()` 만들어 `loop.run_until_complete()`로 감싸 호출.

#### ② stdio는 thread-safe하지 않음

MCP subprocess는 stdin/stdout 1쌍 → 멀티 스레드에서 같은 subprocess를 공유하면 메시지 인터리빙. `threading.local()`로 스레드별 격리 필수.

#### ③ subprocess 환경변수 누락

`load_dotenv()`로 환경변수 로드해도 spawn된 subprocess에 자동 들어가지 않음. `env={"PATH":..., "CONFLUENCE_URL":..., ...}`로 명시 전달. **PATH도 빼먹으면 안 됨** — Windows에서 `mcp-atlassian` 실행파일 검색 실패.

#### ④ 응답 형식 가정 금지

같은 MCP 서버 안에서도 도구마다 응답 모양이 다를 수 있음 (외부 MCP는 더 심함). `_unwrap_text` + `try/except json.loads`로 방어.

#### ⑤ OpenAI Responses API stall (LLM-driven 한정)

deepagents가 `"openai:"` prefix 시 Responses API(SSE 스트림) 사용. 스트림이 stall되면 OpenAI SDK 디폴트 timeout이 600초 × 재시도 2회 → 최악 30분 무응답. → 클라이언트 측에 `asyncio.wait_for(coro, timeout=N)` 안전망 필수. 본 프로젝트는 90초로 설정 ([confluence_mcp/llm_personality.py](confluence_mcp/llm_personality.py)).

#### ⑥ 첫 init이 느림 (~2~3초)

`_ensure_init`이 subprocess spawn + 도구 메타데이터 로드 수행. 워커 스레드별 첫 호출에서만 발생 → 캐시 히트 후엔 빠름. **벤치마크 시 이 첫 호출 비용 분리**.

#### ⑦ 인증 정보 누락 시 init은 성공, 호출에서 실패

환경변수 빠뜨려도 subprocess는 일단 뜸 (도구 메타데이터까지는 인증 불필요). 실제 도구 호출 단계에서 401/403. → wrapper에 `try/except`로 감싸고 fail-soft (시뮬은 계속 진행).

</details>

---

> 다음: 3차 — 코드 한 줄씩 해설 (양쪽의 같은 use case 핵심 함수 비교)

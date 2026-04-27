# MCP 서버 외부vs구현

**목차**

1. [MCP란 무엇인가](#1-mcp란-무엇인가)
2. [세 가지 연동 방식 — 개념과 책임 위치](#2-세-가지-연동-방식--개념과-책임-위치)
3. [각 방식의 특징과 장단점](#3-각-방식의-특징과-장단점)
4. [어떻게 선택할 것인가](#4-어떻게-선택할-것인가)
5. [코드로 보는 차이](#5-코드로-보는-차이)
6. [부록](#부록)
    - [A. Confluence(`mcp-atlassian`) 사용 시 알아야 할 것](#a-confluencemcp-atlassian-사용-시-알아야-할-것)
    - [B. 양쪽 다 빠지기 쉬운 운영 함정](#b-양쪽-다-빠지기-쉬운-운영-함정)
    - [C. MCP 서버 프레임워크 선택지](#c-mcp-서버-프레임워크-선택지)

# 1. MCP란 무엇인가

## 1.1 MCP 개념: LLM과 외부 시스템을 잇는 표준 프로토콜

<aside>
💡

MCP(Model Context Protocol)는 Anthropic이 2024년 11월에 공개한 오픈 표준 프로토콜

**LLM(또는 AI 에이전트)이 외부 도구·데이터에 접근하는 방식을 표준화한 규격**

</aside>

### 무엇을 표준화하는가

MCP가 정의하는 핵심은 세 가지다

1. **도구(Tool) :** LLM이 호출할 수 있는 함수 — 이름·인자·반환값을 JSON Schema로 명시
2. **리소스(Resource) :** LLM이 읽을 수 있는 데이터 — 파일, DB 레코드, API 응답 등
3. **프롬프트(Prompt) :** 재사용 가능한 프롬프트 템플릿

## 1.2 핵심 구성요소: 클라이언트 / 어댑터 / 서버

MCP 통신은 **클라이언트**, **어댑터, 서버** 세 컴포넌트로 구성된다.

```
┌──────────────┐         ┌─────────────────┐         ┌─────────────┐
│  AI 호스트    │ ──────> │  MCP 클라이언트  │ ──────> │  MCP 서버   │
│  (LLM/코드)  │         │  (+ 어댑터)      │         │  (도구 정의) │
└──────────────┘         └─────────────────┘         └─────────────┘
                            ↑                            ↑
                            stdio / HTTP / SSE 등
                            (전송 계층)
```

### MCP 클라이언트

도구를 **호출하는 쪽** (외부 MCP와 거의 동일, `command`만 다름)

- 서버 프로세스를 띄우고
- 도구 목록을 받아오고
- 실제 호출 수행

```python
client = MultiServerMCPClient({
    "atlassian": {
        "command": "mcp-atlassian",   # 외부 MCP의 경우
        "transport": "stdio",
        ...
    }
})
tools = await client.get_tools()
```

### 어댑터

MCP 도구를 특정 프레임워크가 이해하는 형태로 **변환**하는 다리

어댑터가 하는 일 (번역하는 역할)

1. **생성**: 서버에 도구 목록 요청 → 받은 메타데이터를 LangChain 도구로 래핑
2. **호출**: `tool.ainvoke({...})` → MCP `tools/call` JSON-RPC 메시지로 직렬화해 서버 전송
- 전송 계층 (참고)
    
    MCP는 공식적으로 2가지 전송 방식을 지원한다.  이 차이는 운영 환경 설계 시 별도로 고려해야 한다.
    
    - **stdio**: 클라이언트가 서버를 자식 프로세스로 띄우고 stdin/stdout으로 통신. 가장 단순.
    - **HTTP/SSE**: 원격 MCP 서버 호출. 엔터프라이즈 환경에서 흔함.
    
    | 상황 | 권장 |
    | --- | --- |
    | 로컬 개발, PoC | **stdio** |
    | Claude Desktop 같은 데스크톱 앱에서 MCP 사용 | **stdio** (사실상 표준) |
    | 같은 프로세스가 MCP 서버를 띄워 쓰는 단일 머신 환경 | **stdio** |
    | 회사 내 여러 팀·여러 LLM이 공유하는 MCP 서버 | **HTTP/SSE** |
    | 외부 SaaS의 공식 MCP 엔드포인트 사용 | **HTTP/SSE** (선택의 여지 없음) |
    | 거버넌스·감사·인증 통합 필요 | **HTTP/SSE** |

### MCP 서버

도구를 **정의하고 실행하는 쪽**. 

도구 목록을 노출하고, 호출이 들어오면 실제 작업(외부 API 요청, DB 쿼리 등)을 수행한다. FastMCP, 공식 SDK 같은 프레임워크로 작성하며, 일반적으로 stdin/stdout으로 통신하는 별도 프로세스다.

```python
# 직접 구현 예시 (FastMCP)
@mcp.tool()
def save_reflection(agent_name: str, day: int, text: str) -> dict:
    return {...}
```

## 1.3 왜 "연동 방식" 선택이 중요한가 — 책임을 어디에 둘 것인가의 문제

> **"MCP 서버를 외부 패키지로 끌어올 것인가, 직접 만들 것인가?"**
> 

이 선택은 단순한 "개발 비용 vs 통제권" 트레이드오프로 보일 수 있지만, 본질은 더 깊다. 
**도구의 시그니처를 누가 정의하느냐**의 문제이며, 그 결과 **도메인 변환 책임이 어디에 놓이느냐**가 결정된다.

### 도메인 변환이란

LLM 또는 호출 코드가 쓰는 도메인 언어와, 외부 시스템의 일반 언어 사이에는 **항상 갭**이 있다.

- 우리 도메인: `save_reflection(agent_name="Alice", day=3, text="...")`
- Confluence 일반 CRUD: `create_page(space_key="...", parent_id="...", title="Reflection - Alice - Day 3", content="...")`

같은 일을 두 가지 언어로 표현하는 것이고, 사이엔 **변환**이 필요하다.
ex. 제목 prefix를 어떻게 만들지, 부모 페이지 ID를 어디서 가져올지, 본문을 어떻게 조립할지.

- 어댑터 번역 vs 도메인 변환
    
    <aside>
    💡
    
    **어댑터 번역 :** 기계가 하는 문서 형식 변환 - 어디서 하든 똑같음
    **도메인 변환 :** 사람이 정의하는 의미 변환 - 어디에 두느냐가 외부 vs 직접 구현을 가르는 핵심
    
    </aside>
    
    **어댑터 번역**은 문서 형식 변환
    
    - 같은 한국어 문서를 .docx에서 .pdf로 바꾸는 것
    - 내용은 똑같고 컨테이너만 다름
    - 자동화 가능
    
    **도메인 변환**은 언어 번역
    
    - "오늘 회고 저장" (한국어) → "Confluence 페이지 생성: 제목 규약 X, 부모 Y" (영어)
    - 문화적 맥락·도메인 지식이 필요
    - 사람이 규칙을 정해줘야 함

### 이 변환을 누가 하느냐가 핵심

**외부 MCP** : 외부 서버는 일반 CRUD만 안다. → 변환은 클라이언트가 떠안음. (호출자가 매번 변환 작성)

```python
# 외부 MCP — 호출자가 매번 변환 작성
def save_reflection(agent_name, day, text):
    title = f"Reflection - {agent_name} - Day {day}"   # 변환 ①
    body = f"**Agent**: {agent_name}\n..."             # 변환 ②
    confluence_create_page(
        space_key=SPACE_KEY,                           # 인프라 인자
        parent_id=PARENT_PAGE_ID,                      # 인프라 인자
        title=title, content=body,
    )
```

**직접 구현** : 우리가 도메인 시그니처를 정의. → 변환은 서버 안에 응집. (호출자는 도메인 인자만 넘기면 끝)

```python
# 직접 구현 — 서버 안에서 변환
@mcp.tool()
def save_reflection(agent_name: str, day: int, text: str):
    title = _build_title(agent_name, day)              # 서버 안 변환
    return _upsert(SPACE_KEY, title, ...)              # 인프라 인자는 서버 상수
```

### 이 차이가 미치는 영향

책임 위치 하나로 인해 다음이 모두 결정된다:

| 영향 | 외부 MCP | 직접 구현 |
| --- | --- | --- |
| LLM이 봐야 할 인자 | 일반 CRUD 인자 모두 (`space_key`, `parent_id` 등) | 도메인 인자만 (`agent_name`, `day`) |
| 클라이언트 코드량 | 많음 (매번 변환) | 적음 (위임만) |
| 서버 코드 작성 비용 | X (외부에 위임) | O (직접 작성) |
| 외부 API 변경 대응 | 외부 | 우리 |
| 도구 시그니처 통제 | 외부 | 우리 |

# 2. 세 가지 연동 방식 — 개념과 책임 위치

**MCP 서버를 누가 만드느냐**에 따라 도메인 변환의 책임 위치가 달라진다. 
이 책임을 어디에 둘지에 따라 실무에서는 세 가지 방식이 가능하다.

```
┌─────────────────────────────────────────────────────────────┐
│  외부 MCP        클라이언트 ━━ 도메인 변환 ━━ 외부 서버         │
│  직접 구현       클라이언트 ━━━━━━━━━━━━━ 직접 서버 ┃ 변환    │
│  하이브리드      클라이언트 ━ helper ━━━━━ 외부 서버 ┃ 변환    │
└─────────────────────────────────────────────────────────────┘
              도메인 변환 위치만 다를 뿐, 통신 구조는 동일
```

## 2.1 외부 MCP 서버 사용

이미 누군가 만들어둔 MCP 서버 패키지를 그대로 가져다 쓰는 방식. 

```
[내 코드]                    [외부 패키지]              [외부 시스템]
┌──────────┐                ┌──────────────┐          ┌─────────────┐
│ wrapper  │ ──── 호출 ───→ │ mcp-atlassian │ ──API──→ │ Confluence │
│ + 도메인  │                │  (24개 도구)  │          │             │
│  변환    │                └──────────────┘          └─────────────┘
└──────────┘
   ↑
   여기에 도메인 변환 위치
```

<aside>
💡

도메인 변환 : 클라이언트 wrapper

</aside>

### 구조 특징

- **서버 코드 작성 0줄.** `pip install mcp-atlassian` 한 번이면 24개 Confluence/Jira 도구가 즉시 노출.
- **호출자(LLM 또는 코드)가 외부 시스템의 일반 CRUD 인자를 모두 알아야 함.** 
`space_key`, `parent_id`, 제목 prefix 규약 등 인프라 인자가 매번 호출 코드에 등장.
- **외부 패키지 메인테이너에 종속.** Atlassian REST API가 바뀌면 패키지가 따라가야 우리도 동작.

- 실무에서는!
    
    호출 코드의 도메인 변환을 별도의 Python helper 함수로 추출해 응집하는 것이 일반적
    하지만 이 방법은 code-driven 방식에서만 유효
    
    LLM-driven 방식의 경우, 프롬프트에 별도의 규약을 만들어 주입을 해주어야 하며, 응답 보장 불가
    

## 2.2 직접 구현 MCP 서버

우리 use case에 맞는 도메인 도구를 가진 MCP 서버를 직접 작성하는 방식. 
본 가이드의 `confluence_mcp_server`가 그 예.

```
[내 코드]               [내가 만든 서버]                [외부 시스템]
┌──────────┐           ┌─────────────────┐           ┌─────────────┐
│ wrapper  │ ─ 호출 →  │ @mcp.tool        │ ── API ──→ │ Confluence │
│ (얇음)   │           │ save_reflection  │           │             │
└──────────┘           │ + 도메인 변환    │           └─────────────┘
                       │ + REST 호출      │
                       └─────────────────┘
                              ↑
                       여기로 도메인 변환 이동
```

<aside>
💡

도메인 변환 : 서버 내, 도구 정의

</aside>

*호출자는 도메인 인자(`agent_name`, `day`)만 넘기면 끝. 인프라 인자는 서버 상수로 숨김.

### 구조 특징

- **서버 코드 직접 작성.** FastMCP 같은 프레임워크로 도메인 도구를 `@mcp.tool` 데코레이터로 정의.
- **호출자가 도메인 언어로만 통신.** `save_reflection(agent_name, day, text)` — 인프라 디테일은 서버가 흡수.
- **외부 시스템 API 디테일을 우리가 직접 처리.** Atlassian의 낙관적 락(`version+1`), 응답 형식 변환, 에러 처리 모두 우리 책임.

- 인프라 디테일?
    
    **(A) 우리 프로젝트 고유의 정책**
    
    - `space_key="DOC"`, `parent_page_id="12345"` ← 이건 *우리가 정한* 저장 위치
    - 제목 prefix `"Reflection - "` ← 우리 프로젝트 규약
    
    **(B) Confluence/Atlassian 시스템 자체의 요구사항**
    
    - `version+1` 낙관적 락 ← 우리가 정한 게 아니라 *Atlassian이 요구*
    - `content_format="markdown"` ← Confluence가 받는 포맷
    - 인증 토큰 ← 어느 시스템이든 필요

### 2.3 하이브리드

도구마다 어느 방식을 쓸지 다르게 결정하는 방식. 
**핵심 도메인 도구는 직접 구현**하고, **주변·범용 도구는 외부 MCP를 그대로 사용.**
→ 각 도구의 성격에 맞게 책임 위치를 다르게 선택

```
                  Confluence
                      ▲
                      │
       ┌──────────────┴──────────────┐
       │                              │
  직접 구현 서버                  외부 MCP 서버
   (도메인 도구)                   (범용 도구)
   - save_reflection             - 페이지 코멘트 조회
   - fetch_past_reflections      - 사용자 검색
                                  - 일반 CRUD
       │                              │
       └──────────────┬──────────────┘
                      │
                    호출자
                (LLM 또는 코드)
```

<aside>
💡

핵심 도구에만 직접 구현 비용을 투자하고, 나머지는 외부에 위임
(책임의 무게중심을 적절히 분산하는 전략)

</aside>

### 구조 특징

- **도메인 규약이 강한 도구만 직접 구현.** 본 가이드 사례라면 `save_reflection`, `fetch_past_reflections` — 제목 prefix 규약, 본문 포맷, mode 분기 등 우리만의 규칙이 들어가므로 서버에 응집할 가치가 있음. LLM에 도메인 인자만 노출해 안전하게 호출.
- **범용·단발 도구는 외부 MCP 그대로.** 같은 Confluence라도 페이지 코멘트 조회, 사용자 검색처럼 도메인 규약 없이 일반 CRUD만 필요한 도구는 외부 MCP를 그대로 사용. 자체 구현 가치 없음.
- **서버에 추가하는 도구 수를 최소화.** 24개 외부 도구를 모두 다시 만들지 않고, 도메인 가치가 있는 3~5개만 직접 구현 → 작성 비용 회수 가능한 범위에 집중.

### 언제 필요한가

- **핵심 도메인 도구를 LLM으로 호출** → 외부 MCP에 맡기면 인자 누락·실수 위험. 도메인 규약을 프롬프트로만 강제해야 하므로 신뢰성 낮음. (직접 구현이 정당화되는 영역)
- **코드로만 호출하는 도구가 도메인 규약 없음** → 직접 구현해도 서버 코드만 늘고 가치 없음. (외부 MCP 그대로가 적합한 영역)

- 여러 서비스를 연결할 때
    
    ```
    직접 구현 서버                       ┓
         (Confluence 핵심 도메인 도구)       ┃
                                            ┃
       외부 MCP — Atlassian                 ┣━━ 호출자
         (Confluence 범용 도구, Jira)       ┃   (LLM 또는 코드)
                                            ┃
       외부 MCP — Slack                     ┃
         (알림 발송)                        ┃
                                            ┃
       외부 MCP — GitHub                    ┃
         (이슈 관리)                        ┛
    ```
    
    - **도메인 가치가 있는 서비스만 직접 구현**, 나머지는 각 서비스의 외부 MCP를 그대로 사용.
    - 서비스마다 직접 만들면 N개 서버 작성·유지가 부담 → 외부 MCP가 합리적.
    - 대기업이 사내 MCP 게이트웨이 뒤에 자체 서버 + 외부 서버를 함께 두는 패턴이 이쪽.
    
    > 핵심은 단일/다중 서비스 모두 동일하다.
    **도메인 규약이 들어가는 부분만 우리가 통제하고, 그 외는 외부에 위임.**
    > 

# 3. 각 방식의 특징과 장단점

| 항목 | 외부 MCP | 직접 구현 | 하이브리드 |
| --- | --- | --- | --- |
| **시작 비용** | 즉시 (`pip install`) | 서버 작성 (~300줄) | 핵심 도구만 작성 |
| **도메인 변환 위치** | 클라이언트 wrapper | 서버 도구 정의 | 도구별로 다름 |
| **LLM-driven** | 어려움 (인프라 인자 가르쳐야) | 쉬움 (도메인 인자만) | 핵심 도구만 가능 |
| **외부 API 변경 대응** | 외부 | 우리 | 도구별로 다름 |
| **도구 시그니처 통제** | 외부 | 우리 | 도구별로 다름 |
| **시스템 디테일 처리**
(`version+1` 등) | 외부 | 우리 | 도구별로 다름 |
| **새 도구 추가** | 외부 | 우리 | 도구별로 다름 |
| **여러 언어·팀 공유** | Python helper로는 한계 | MCP 표준으로 가능 | 핵심만 가능 |
| **추적·디버깅** | 단순 | 단순 | 복잡 |

## **3.1 외부 MCP 서버 사용**

### **장점**

- **즉시 시작.** `pip install mcp-atlassian` 한 번이면 24개 Confluence/Jira 도구가 즉시 노출. 서버 작성 시간 0.
- **도구 풀이 넓음.** 당장 안 쓰는 도구도 나중에 use case가 생기면 그대로 활용 가능.
- **외부 시스템 API 변경 대응 위임.** Atlassian REST API가 바뀌어도 패키지 메인테이너가 따라감. 우리는 패키지 업데이트만 제때 하면 됨.
- **인증·운영 위임.** 환경변수 전달 규약만 맞추면 끝. 토큰 갱신·재시도 정책 등을 패키지가 흡수.
- **시스템 디테일 처리도 위임.** Atlassian의 낙관적 락(`version+1`) 같은 REST 디테일을 패키지가 내부 처리.

### **단점**

- **도메인 변환을 호출 측이 떠안음.** 외부 MCP는 일반 CRUD만 안다. 우리 프로젝트의 특성(Reflection이 뭔지, 제목 규약이 뭔지)은 모름 → 호출할 때마다 변환 필요.
- **외부 도구 시그니처 변경 위험.** 패키지 업데이트로 인자 이름이 바뀌면 우리 호출 코드가 깨짐.
- **외부 패키지 대응 지연 시 우리도 막힘.** 외부 시스템 API가 변경됐는데 패키지가 빨리 따라가지 않으면 우리 호출 코드도 깨진 채로 기다려야 함. **외부 메인테이너 일정에 우리 일정 종속.**
- **응답 형식이 도구마다 일관되지 않음.** 24개 도구가 plain text / JSON 문자열 / 리스트 등 서로 다른 모양으로 반환 → 도구마다 파싱 코드가 따로 필요.
- **LLM에 노출 시 프롬프트 비대화.** LLM에게 일반 `confluence_create_page`를 주려면 시스템 프롬프트로 인프라 인자(`space_key`, `parent_id`)와 도메인 규약을 다 가르쳐야 함. 도구 24개를 모두 노출하면 LLM이 잘못된 도구를 고를 위험도 증가.

### **전제**

- 신뢰할 수 있는 외부 패키지가 존재하고 활발히 유지됨.
- 그 패키지가 우리 use case의 80% 이상을 커버.
- **호출자가 코드뿐**(LLM이 호출자면 일반 도구를 안전하게 노출하기 어려움 → 직접 구현 또는 하이브리드 필요).
- 단일 프로젝트 안에서만 호출(다른 언어·팀이 같은 도메인으로 호출해야 하면 표준 인터페이스 필요).

### **적합한 상황**

- **PoC·단발 통합.** "사내 위키에 가끔 페이지 만들기" 같은 케이스. 호출 지점 1~2곳, 도메인 규약 약함, 빨리 보여주는 게 목적.
- **여러 외부 시스템을 한 번씩 통합.** Slack 알림 + Jira 코멘트 + GitHub 이슈처럼 시스템마다 호출 1~2회면 도메인 변환 비용이 작음 → 시스템마다 직접 만들면 서버 N개 작성·유지가 부담.
- **호출자가 전부 코드인 환경.** 도메인 변환을 helper 함수로 응집할 수 있어 단점이 완화됨.

## 3.2 직접 구현 MCP 서버

### 장점

- **LLM 호출자에게 도메인 도구로 안전하게 노출.**
    - 일반 도구의 인프라 인자(`space_key`, `parent_id`)를 프롬프트로 가르치지 않아도 됨.
    - LLM이 채울 인자 표면적이 작아 실수 가능성 낮음.
    - use case에 필요한 도구만 노출 → 24개 중 잘못된 도구 고를 위험 없음.
- **호출 측 코드가 짧음.** 변환·필터링·정렬이 다 서버 안에 구현. wrapper는 인자만 위임.
- **도구 시그니처를 우리가 통제.** 외부 변경에 흔들리지 않음. 시그니처를 우리 도메인 진화에 맞춰 고칠 수 있음.
- **저장 정책 같은 횡단 관심사를 서버에 응집 가능.** 본 가이드 사례에선 `CONFLUENCE_WRITE_MODE` 같은 정책이 도구 1개의 인자 1개로 통제됨. 외부 MCP에선 정책 분기를 호출 측이 매번 작성해야 함.

### 단점

- **초기 작성 비용.** 본 가이드 사례 기준 MCP 서버 약 300줄(서버 본체 + REST 클라이언트). 단순한 use case에는 과한 투자일 수 있음.
- **외부 시스템 API 변경에 직접 대응 필요.** Atlassian REST API가 바뀌면 우리 코드도 직접 수정·테스트·배포해야 함.
- **새 use case 생기면 서버에 도구 추가 필요.** 외부 MCP는 24개 중 골라 쓰지만, 직접 구현은 만든 것만 있다.
- **인증·운영 직접 책임.** 환경변수, 토큰 갱신, 에러 처리, 재시도 정책 모두 우리가.
- **시스템 디테일도 직접 처리.** Atlassian 낙관적 락(`version+1`), 응답 구조 변환 등 외부 패키지가 흡수하던 디테일이 다시 우리 책임.

### 전제

- 호출자 중에 LLM이 있고 도메인 도구로 안전하게 노출하고 싶을 때.
- 호출 빈도가 높거나, 같은 도메인 도구가 여러 지점에서 쓰여야 서버 작성 비용 회수.
- 여러 언어·팀이 같은 도메인 인터페이스를 공유해야 할 때.

### 적합한 상황

- **호출자에 LLM이 포함되는 환경.** 도메인 도구를 LLM에 안전하게 노출. 인자 누락·잘못된 값 입력 위험 최소화.
- **여러 클라이언트·언어가 같은 도메인을 공유.** Python helper로는 못 풀리는 영역 — TypeScript 서비스, 다른 팀 스크립트, 별도 LLM 에이전트가 같은 도메인 도구를 호출.
- **사내 표준 도메인 어댑터를 한 곳에서 관리하고 싶을 때.** 도메인 규약 변경 시 한 곳만 고치면 됨.
- **외부 패키지가 부족한 영역.** 활성도 낮음·커버리지 낮음·자주 깨짐.

## 3.3 하이브리드

### 장점

- **책임의 무게중심 분산.** 모든 도구를 직접 구현하면 작성·유지·외부 API 대응이 우리에게 집중됨. 하이브리드는 핵심 도구에만 직접 구현 비용을 투자하고 나머지는 외부에 위임.
- **핵심 도메인 도구는 안전하게 LLM에 노출.** 도메인 규약이 들어가는 도구만 직접 구현해 도메인 인자로만 노출.
- **범용 도구는 외부 MCP 활용.** 자체 구현 가치 없는 일반 CRUD나 단발 조회는 외부 패키지 그대로 → 서버 코드 최소화.
- **현실의 가장 흔한 패턴.** Slack, Notion, GitHub, Atlassian 등 주요 SaaS는 이미 외부 MCP가 존재 → 모든 통합을 직접 만드는 건 비현실적.

### 단점

- **도구가 두 곳에 분산 → 인지 부담.** 어느 도구가 어디에 있는지 추적이 필요. 명확한 분리 기준이 없으면 혼란.
- **두 방식의 단점을 일부씩 모두 가짐.** 외부 MCP의 패키지 종속 + 직접 구현의 작성·유지 비용을 동시에 짊어짐 (단, 각각 부담의 영역은 분리됨).
- **분리 기준 정립이 의사결정 비용.** *"이 도구는 어디로 가야 하나"*를 도구마다 판단해야 함. 처음에는 기준이 흔들릴 수 있음.
- **테스트·배포 복잡도 증가.** 외부 MCP 업데이트와 자체 서버 배포가 둘 다 영향을 미침.

### 전제

- **핵심 도메인 도구와 범용 도구를 분리할 수 있는 명확한 기준이 있을 것.** 분리 기준이 모호하면 안티패턴이 됨.
- 핵심 도메인 도구의 수가 작성 비용을 회수할 정도(보통 3~5개 이상).
- 외부 MCP 패키지가 범용 도구 영역을 잘 커버.

### 적합한 상황

- 한 서비스 안에서도 도구별 성격이 갈릴 때 — 핵심 워크플로우(직접 구현)와 주변 조회(외부 MCP)가 공존.
- LLM이 호출하는 핵심 도구는 도메인 인자로 안전하게 노출하고, 코드에서만 부르는 보조 도구는 외부 MCP의 일반 인자로 충분한 경우.
- 직접 구현의 작성 비용을 핵심 도구로만 한정하고 싶을 때.
- 단일 서비스가 아니라 **여러 서비스를 동시에 다뤄야 할 때** — 도메인 가치가 있는 서비스만 직접 구현, 나머지는 각 서비스의 외부 MCP를 그대로 사용.

# 4. 어떻게 선택할 것인가

## 4.1 핵심 결정 조건

세 가지 방식 중 무엇을 고를지는 두 가지 질문으로 결정된다.

1.  **호출자에 LLM이 포함되는가**
LLM은 Python helper를 못 본다. MCP 도구만 본다.
→ LLM이 호출자라면 도메인 도구를 안전하게 노출하기 위해 직접 구현이 필요.
→ 호출자가 코드뿐이면 helper로 충분 → 외부 MCP 또는 하이브리드.
2. **다중 클라이언트·언어가 같은 도메인을 공유하는가**
Python helper는 Python 한정. TypeScript·다른 팀·별도 LLM 에이전트는 못 씀.
→ 여러 언어·팀이 공유해야 하면 직접 구현된 MCP 서버가 표준 인터페이스.
→ 단일 프로젝트 안에서만 호출하면 외부 MCP 또는 하이브리드로 충분.

보조 변수 (두 조건이 모호할 때)

| 변수 | 직접 구현 쪽으로 기우는 신호 |
| --- | --- |
| 외부 패키지 활성도 | 마지막 커밋 1년 전 + API 자주 변경 |
| 외부 패키지 커버리지 | 우리 use case의 80% 미만 커버 |

## 4.2 시나리오별 권고

| 시나리오 | 권고 |
| --- | --- |
| PoC, 단발 통합, 호출자 모두 코드 | 외부 MCP |
| LLM 호출자 + 핵심 도메인 도구 | 직접 구현 |
| 여러 언어·팀이 같은 도메인 공유 | 직접 구현 |
| 외부 패키지가 부족·불안정 | 직접 구현 |
| 핵심 도구는 LLM 호출 + 주변은 코드 호출 | 하이브리드 |
| 여러 SaaS를 동시에 통합 | 하이브리드 |

# **5. 코드로 보는 차이**

## **5-1. 공통 보일러플레이트 — MCP 자체의 비용**

| **보일러플레이트 항목** | **역할** |
| --- | --- |
| `MultiServerMCPClient` + `client.get_tools()` | MCP 서버 연결, 도구 메타데이터 로드 |
| `threading.local()` | 워커 스레드별 subprocess 격리 (stdio 1쌍 공유 금지) |
| `asyncio.new_event_loop()` + `loop.run_until_complete()` | langchain-mcp-adapters는 async-only — sync 우회 |
| `_build_subprocess_env` (PATH + Confluence 인증 추림) | spawn된 subprocess는 부모 환경변수 자동 상속 X |
| `_unwrap_text` / `_unwrap_response` | MCP 응답 `[{type:'text', text:...}]` 풀기 |
| `tool.ainvoke({...})` 호출 패턴 | 도구 호출 표준 인터페이스 |
| `python-dotenv` `.env` 로드 | 인증 정보 환경변수화 |

## **5-2. init: 거의 같음 — `command` 한 줄만 다름**

`_ensure_init` 본체(threading.local 캐시 → loop 생성 → MCP 클라이언트 구성 → `get_tools()`)는 **양쪽이 동일**. 차이는 어떤 프로세스를 띄우느냐 한 줄.

```python
# 외부 MCP — confluence_mcp/confluence_official.py
client = MultiServerMCPClient({
    "atlassian": {
        "command": "mcp-atlassian",                          # ← PATH의 외부 패키지 실행파일
        "args": [],
        "transport": "stdio",
        "env": _build_subprocess_env(),
    }
})
```

```python
# 직접 구현 — confluence_mcp/confluence_custom.py
client = MultiServerMCPClient({
    "confluence_custom": {
        "command": sys.executable,                           # ← 같은 Python 인터프리터
        "args": ["-m", "confluence_mcp_server.server"],      # ← 우리 서버 모듈 실행
        "transport": "stdio",
        "env": _build_subprocess_env(),
    }
})
```

## **5-3. save_reflection: 결정적으로 다름 ⭐**

같은 일(Reflection 1건을 Confluence에 저장)을 하는 코드인데, **책임이 어디 놓이느냐**가 정반대.

### **외부 MCP — wrapper에 모든 책임 응집 (~60줄)**

도메인 변환(①②), mode 분기(③), 인프라 인자(④) 전부 **클라이언트 한 함수 안에 응집**. 
mcp-atlassian은 일반 CRUD만 알기 때문에 이 변환을 호출 측이 떠안을 수밖에 없다.

[confluence_mcp/confluence_official.py](https://file+.vscode-resource.vscode-cdn.net/c:/Users/jack1/OneDrive/Documents/code/2603PJ_AIsimulation/confluence_mcp/confluence_official.py)

```python
def save_reflection(agent_name, day, text, quota,
                    run_id=None, mode="append") -> bool:
    tools = _ensure_init()

    # ① 도메인 → Confluence 번역: 제목 prefix
    title = _build_reflection_title(agent_name, day, run_id, mode)

    # ② 도메인 → Confluence 번역: markdown 본문
    quota_line = json.dumps(quota, ensure_ascii=False) if quota else "(파싱 실패)"
    body = (
        f"**Agent**: {agent_name}\n\n**Day**: {day}\n\n"
        f"**Quota**: `{quota_line}`\n\n---\n\n{text}\n"
    )

    # ③ mode 분기: overwrite면 find → update, 아니면 create
    if mode == "overwrite":
        existing_id = find_page_id_by_title(title, tools)        # MCP 호출 1
        if existing_id:
            update = tools["confluence_update_page"]
            _local.loop.run_until_complete(update.ainvoke({
                "page_id": existing_id, "title": title,
                "content": body, "content_format": "markdown",
            }))                                                  # MCP 호출 2
            return True

    # ④ 인프라 인자 매번 명시 (space_key, parent_id, content_format)
    create = tools["confluence_create_page"]
    _local.loop.run_until_complete(create.ainvoke({
        "space_key": SPACE_KEY, "title": title, "content": body,
        "parent_id": PARENT_PAGE_ID, "content_format": "markdown",
    }))
    return True
```

### **직접 구현 — 클라이언트는 위임만 (~15줄), 서버 안에서 변환 (~30줄)**

**[1] 클라이언트 wrapper** — [confluence_mcp/confluence_custom.py](https://file+.vscode-resource.vscode-cdn.net/c:/Users/jack1/OneDrive/Documents/code/2603PJ_AIsimulation/confluence_mcp/confluence_custom.py)

도메인 인자만 받아서 그대로 전달. **변환·분기 0줄.**

```python
def save_reflection(agent_name, day, text, quota,
                    run_id=None, mode="append") -> bool:
    tools = _ensure_init()
    save_tool = tools["save_reflection"]

    _local.loop.run_until_complete(save_tool.ainvoke({
        "agent_name": agent_name, "day": day,
        "text": text, "quota": quota,
        "run_id": run_id, "mode": mode,        # ← 도메인 인자 그대로 위임
    }))
    return True
```

**[2] 서버의 도메인 도구** — [confluence_mcp_server/server.py](https://file+.vscode-resource.vscode-cdn.net/c:/Users/jack1/OneDrive/Documents/code/2603PJ_AIsimulation/confluence_mcp_server/server.py)

외부 MCP의 ①②가 여기로 이동. **서버 안이라 LLM/다른 클라이언트가 호출해도 같이 적용됨.**

```python
@mcp.tool()
def save_reflection(agent_name, day, text, quota=None,
                    run_id=None, mode="append") -> dict:
    title = _build_reflection_title(agent_name, day, run_id, mode)  # ① 변환
    html  = _build_html_body(agent_name, day, text, quota)          # ② 변환
    return _upsert(SPACE_KEY, title, html, PARENT_PAGE_ID, mode)    # ③ 분기 위임
```

**[3] 서버의 `_upsert` 헬퍼** — mode 분기 한 곳에 응집

외부 MCP에서 wrapper에 있던 ③ 분기가 여기로 이동. **호출 측은 mode 문자열 하나만 넘기면 끝.**

```python
def _upsert(space_key, title, html_body, parent_id, mode) -> dict:
    if mode == "overwrite":
        existing = find_page_by_title(space_key, title)
        if existing:
            return update_page(
                page_id=existing["id"], title=title,
                html_body=html_body,
                current_version=existing["version"],   # ← version+1은 update_page 안에서
            )
    return create_page(space_key=space_key, title=title,
                       html_body=html_body, parent_id=parent_id)
```

**[4] REST 호출 — Atlassian 디테일은 우리 책임** — [confluence_mcp_server/confluence_client.py](https://file+.vscode-resource.vscode-cdn.net/c:/Users/jack1/OneDrive/Documents/code/2603PJ_AIsimulation/confluence_mcp_server/confluence_client.py)

외부 MCP에선 보이지 않는 부분. 핵심은 `version+1`(낙관적 락)

`mcp-atlassian이 알아서 처리해주던` 부분을 직접 구현은 우리가 책임. `find_page_by_title`이 `expand=version`을 미리 받아두는 이유도 이 +1 때문.

```python
def update_page(page_id, title, html_body, current_version) -> dict:
    body = {
        "type": "page", "title": title,
        "version": {"number": current_version + 1},     # ← 낙관적 락 +1 ⭐
        "body": {"storage": {"value": html_body, "representation": "storage"}},
    }
    raw = _request("PUT", f"content/{page_id}", json_body=body)
    return {"id": raw["id"], "title": raw["title"]}
```

### **같은 일, 다른 위치 — 한눈에**

<aside>
💡

외부 ~60줄 vs 직접 ~15(클라) + ~30(서버)줄. 
**총량은 비슷**한데 클라이언트만 보면 직접 구현이 1/4. 책임을 서버로 옮긴 결과.

</aside>

| **같은 일** | **외부 MCP 위치** | **직접 구현 위치** |
| --- | --- | --- |
| 제목 prefix 조립 | wrapper `save_reflection` | 서버 `_build_reflection_title` |
| 본문 markdown/HTML 조립 | wrapper `save_reflection` | 서버 `_build_html_body` |
| mode 분기 (find→update/create) | wrapper `save_reflection` | 서버 `_upsert` |
| 인프라 인자 (`space_key`, `parent_id`) | wrapper가 매번 명시 | 서버 상수 |
| Atlassian `version+1` | 외부 패키지가 처리 (안 보임) | `confluence_client.update_page` |

## **5-4. 다른 도구도 같은 패턴**

다른 도구에서도 그대로 반복

| **도구** | **외부 MCP 위치** | **직접 구현 위치** |
| --- | --- | --- |
| **`fetch_past_reflections_text`** (코드 호출) | wrapper에서 `confluence_get_page_children` 호출 → JSON unwrap → 제목 prefix 필터링 → day 4자리 파싱 → 정렬 → 본문 trim. 약 50줄 | wrapper는 호출·포맷팅만(~25줄). 서버 `fetch_past_reflections`가 prefix 필터·day 파싱·정렬·HTML→text 추출 모두 처리 |
| **`save_personality_profile`** (LLM 호출) | LLM에 `confluence_create_page` 노출 → `space_key`/`parent_id`/제목 prefix를 시스템 프롬프트로 LLM에 주입(~12줄). mode 분기는 코드가 미리 도구 1개로 좁혀줌 (LLM은 분기 모름) | LLM에 `save_personality_profile` 도메인 도구 1개 노출 → 시스템 프롬프트에는 도메인 인자 4개만 명시(~6줄). 인프라 인자·mode 분기 모두 서버 |
| **`find_page_id_by_title`** (overwrite 사전 조회) | wrapper에 직접 구현 — `confluence_get_page` 호출 → `_unwrap_text` → `json.loads` → id 추출(~30줄) | 클라이언트엔 없음. 서버 `_upsert` 안에서 `find_page_by_title` 호출 (REST 직접) |

## **5-5. 정량 비교 — 전체 코드량·파일 구성**

```
외부 MCP 브랜치 (feature/mcp-confluence-official)
└─ confluence_mcp/
   ├─ confluence_official.py   261 줄  ← wrapper (init + 도메인 변환 + 도구 호출)
   └─ llm_personality.py       126 줄  ← LLM-driven Profile (시스템 프롬프트 길다)
                              ─────
                              387 줄

직접 구현 브랜치 (feature/mcp-confluence-custom)
├─ confluence_mcp/
│  ├─ confluence_custom.py     148 줄  ← wrapper (인자 위임만)
│  └─ llm_personality.py        93 줄  ← LLM-driven Profile (시스템 프롬프트 짧다)
└─ confluence_mcp_server/
   ├─ server.py                198 줄  ← FastMCP 서버 + 도메인 도구 정의
   └─ confluence_client.py     105 줄  ← Atlassian REST httpx wrapper
                              ─────
                              544 줄
```

| **측면** | **외부 MCP** | **직접 구현** | **차이** |
| --- | --- | --- | --- |
| 클라이언트 측 코드 | **387 줄** | **241 줄** | −146 |
| 서버 측 코드 | 0 (외부 패키지) | 303 줄 | +303 |
| **합계** | **387 줄** | **544 줄** | **+157** |

**해석**:

- **합계**: 직접 구현이 +157줄 더 많음 = 새로 짊어진 서버 본체 비용.
- **클라이언트만 보면**: 직접 구현이 −146줄(약 38% 감소). 도메인 변환을 서버로 옮긴 결과.
- LLM-driven 파일도 같은 방향: 외부 126줄 vs 직접 93줄(−33줄). 시스템 프롬프트가 짧아졌다 = LLM에 인프라 인자를 안 가르쳐도 된다는 뜻.

# **부록**

## **A. Confluence(`mcp-atlassian`) 사용 시 알아야 할 것**

### **A.1 검색이 신뢰할 수 없음 (CQL 인덱싱 지연)**

`confluence_search` 도구는 Confluence의 CQL(Confluence Query Language)을 사용. 그런데 페이지 생성 직후 바로 검색하면 **빈 결과가 나오는 경우가 있음** — Confluence의 검색 인덱스가 갱신되는 데 시간이 걸리기 때문.
**우회 방법**: 부모-자식 관계를 만들고 `confluence_get_page_children`을 사용. 인덱싱과 무관하게 즉시 조회 가능.

```python
# ❌ 검색 — 직후 호출 시 빈 결과 가능
results = confluence_search(cql=f'title="{title}" AND space="{SPACE_KEY}"')

# ✅ 부모 페이지 자식 조회 — 즉시 신뢰 가능
children = confluence_get_page_children(parent_id=PARENT_PAGE_ID)
```

### A.2 응답 형식이 도구마다 일관되지 않음

24개 도구가 응답을 **plain string / JSON 문자열 / 리스트** 등 서로 다른 모양으로 반환. 도구마다 파싱 코드가 따로 필요함.

**대응**: `_unwrap_text` 같은 정규화 함수를 wrapper에 만들어 응답을 일관된 형태로 변환. 본 가이드의 `confluence_official.py`에서 이 함수가 사실상 필수 보일러플레이트.

### A.3 응답 안에 또 JSON 문자열이 들어 있음

`confluence_get_page` 같은 도구는 `text` 필드 안에 JSON 문자열을 다시 넣어 반환. `json.loads`를 한 번 더 해야 실제 데이터가 나옴.

```python
result = await tools["confluence_get_page"].ainvoke({"page_id": "12345"})
# result = [{"type": "text", "text": '{"id": "12345", "title": "...", ...}'}]
#                                    ↑ 이 안에 또 JSON 문자열

text = result[0]["text"]           # 1차 unwrap
data = json.loads(text)            # 2차 파싱 필요
```

### A.4 `update_page`의 version 자동 처리 (장점 사례)

Confluence는 동시 수정 충돌을 막기 위해 **낙관적 락**을 사용. 페이지 갱신 시 현재 version을 받아서 +1해 보내야 함. `mcp-atlassian`은 이걸 **내부에서 자동 처리** — 호출자는 신경 쓸 필요 없음.

```python
# 외부 MCP — version 자동 처리됨
await tools["confluence_update_page"].ainvoke({
    "page_id": "12345",
    "title": "새 제목",
    "content": "새 본문",
    # version 인자 없음 — 패키지가 알아서
})
```

### A.5 24개 도구 중 use case에 맞게 선택

`mcp-atlassian`은 24개 도구를 모두 노출하지만, 실제로 우리 use case에 필요한 건 보통 4~6개. **사람이 직접 골라서 사용**해야 함.

본 가이드 사례는 4개만 사용:

- `confluence_create_page`
- `confluence_update_page`
- `confluence_get_page`
- `confluence_get_page_children`

```python
# 도구 풀 받기
tools = await client.get_tools()

# 필요한 것만 dict로 추려 사용
tools_to_use = {
    "create": tools["confluence_create_page"],
    "update": tools["confluence_update_page"],
    "get": tools["confluence_get_page"],
    "children": tools["confluence_get_page_children"],
}
```

> **LLM에 24개를 모두 노출하면 잘못된 도구를 고를 위험이 큼.** 코드 호출자는 명시적으로 4개만 쓰면 되지만, LLM이 호출자라면 시스템 프롬프트에서 사용 가능한 도구를 명시적으로 제한하거나, 차라리 직접 구현으로 도메인 도구만 노출하는 게 안전.
> 

## B. 양쪽 다 빠지기 쉬운 운영 함정

### B.1 어댑터는 async-only

`langchain-mcp-adapters`는 **sync 호출을 지원하지 않음**. 모든 도구 호출은 `await`이 필요.

**대응**: 워커 스레드마다 `asyncio.new_event_loop()`를 만들어 `loop.run_until_complete()`로 감싸 호출.

```python
# 동기 함수 안에서 비동기 도구 호출
loop = asyncio.new_event_loop()
result = loop.run_until_complete(tool.ainvoke({...}))
```

### B.2 stdio는 thread-safe 하지 않음

MCP subprocess는 stdin/stdout이 1쌍 → **여러 스레드가 같은 subprocess를 공유하면 메시지가 인터리빙(섞임)** 됨.

**대응**: `threading.local()`로 스레드별 격리. 각 스레드가 자기만의 subprocess + event loop를 가짐.

```python
_local = threading.local()

def _ensure_init():
    if not hasattr(_local, "tools"):
        _local.loop = asyncio.new_event_loop()
        _local.tools = _local.loop.run_until_complete(_init_client())
    return _local.tools
```

### B.3 Subprocess 환경변수 누락

`load_dotenv()`로 환경변수를 로드해도 **spawn된 subprocess에는 자동으로 들어가지 않음**. 명시적으로 `env=` 인자로 전달해야 함.

```python
def _build_subprocess_env():
    return {
        "PATH": os.environ["PATH"],            # ← 빼먹기 쉬움. Windows에서 실행파일 검색 실패
        "CONFLUENCE_URL": os.environ["CONFLUENCE_URL"],
        "CONFLUENCE_USERNAME": os.environ["CONFLUENCE_USERNAME"],
        "CONFLUENCE_API_TOKEN": os.environ["CONFLUENCE_API_TOKEN"],
    }
```

> **`PATH`를 빼먹는 게 흔한 실수.** Windows에서 `mcp-atlassian` 실행파일을 못 찾음.
> 

### B.4 응답 형식 가정 금지

같은 MCP 서버 안에서도 도구마다 응답 모양이 다를 수 있음(외부 MCP는 더 심함). 단순히 `result["text"]` 같은 가정은 위험.

**대응**: `_unwrap_text` + `try/except json.loads`로 방어.

### B.5 첫 init은 느림 (~2~3초)

`_ensure_init`이 subprocess spawn + 도구 메타데이터 로드를 수행. **워커 스레드별 첫 호출에서만 발생** → 캐시 히트 후엔 빠름.

> **벤치마크 시 이 첫 호출 비용을 분리**해서 측정할 것. 평균에 섞이면 도구 호출 자체가 느린 것처럼 보임.
> 

### B.6 인증 정보 누락 시 init은 성공, 호출에서 실패

환경변수를 빠뜨려도 subprocess는 일단 뜸 (도구 메타데이터까지는 인증 불필요). **실제 도구 호출 단계에서 401/403 에러** 발생.

**대응**: wrapper에 `try/except`로 감싸고 fail-soft (시뮬레이션은 계속 진행).

### B.7 OpenAI Responses API stall (LLM-driven 한정)

`deepagents`가 모델명에 `"openai:"` prefix를 쓸 때 OpenAI Responses API(SSE 스트림)를 사용. **스트림이 stall되면 OpenAI SDK 디폴트 timeout이 600초 × 재시도 2회 → 최악 30분 무응답**.

**대응**: 클라이언트 측에 `asyncio.wait_for(coro, timeout=N)` 안전망 필수. 본 가이드는 90초로 설정 (`confluence_mcp/llm_personality.py`).

```python
result = await asyncio.wait_for(
    agent.ainvoke({...}),
    timeout=90,  # ← 안전망
)
```

## C. MCP 서버 프레임워크 선택지

직접 구현 시 어떤 프레임워크를 쓸지에 대한 선택지. 본 가이드는 FastMCP를 사용했지만, 다른 옵션도 있음.

### C.1 Python 옵션

| 프레임워크 | 패키지 | 특징 | 적합한 경우 |
| --- | --- | --- | --- |
| **FastMCP (별도 패키지)** ⭐ | `pip install fastmcp` | jlowin이 만든 가장 인기 있는 Python 프레임워크. FastAPI 스타일 데코레이터 (`@mcp.tool`). 본 가이드 사용. 기능 풍부 | 빠른 작성, 풍부한 기능 |
| **공식 SDK 내장 FastMCP** | `pip install mcp` → `from mcp.server.fastmcp import FastMCP` | 같은 API지만 Anthropic 공식 SDK에 흡수된 버전 | 외부 의존성 줄이고 공식만 쓰고 싶을 때 |
| **공식 SDK low-level** | `pip install mcp` → `from mcp.server import Server` | 데코레이터 없이 핸들러 클래스 직접 등록. 가장 verbose하지만 가장 자유롭다 | 표준에서 벗어난 커스터마이징 |

> 셋 다 같은 MCP 프로토콜이라 클라이언트 입장에서는 **구분 불가**. 작성 편의 차이만 있음.
> 

### 같은 도구를 세 방식으로 등록

본 가이드가 FastMCP를 고른 이유: 도구 3개만 있어 데코레이터 한 줄이 가장 깔끔.

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

### C.2 다른 언어

| 언어 | 주요 옵션 | 특징 |
| --- | --- | --- |
| TypeScript / Node.js | `@modelcontextprotocol/sdk` (공식) | 가장 활발한 생태계 중 하나 |
| Java | 공식 SDK + Spring AI MCP | 엔터프라이즈, Spring 프로젝트라면 자연스러움 |
| C# | 공식 .NET SDK | Microsoft 적극 지원, Semantic Kernel 통합 |
| Kotlin | 공식 SDK | JetBrains·안드로이드 |
| Go / Rust | 커뮤니티 (`mcp-go`, `rmcp` 등) | 공식 없음 |

### C.3 디버깅·운영 도구

| 도구 | 용도 |
| --- | --- |
| `mcp-inspector` | 만든 MCP 서버를 GUI로 디버깅 — 도구 호출 테스트 |
| `mcp-proxy` | stdio ↔ SSE/HTTP 프로토콜 변환 |
| Smithery | MCP 서버 레지스트리 + 설치 CLI (npm 같은 역할) |

💡 단순 코드량은 외부 MCP가 유리. 그 +157줄을 정당화하는 건 1차의 결정 조건 — **호출자에 LLM이 있거나, 여러 클라이언트·언어가 같은 도메인을 공유**해야 함. 둘 다 아니면 외부 MCP가 거의 항상 정답이라는 1차 결론의 코드 레벨 실증.
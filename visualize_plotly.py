"""
Plotly 기반 인터랙티브 HTML 시각화
사용법: python visualize_plotly.py logs/ReAct_성과형_240101_120000.jsonl
        python visualize_plotly.py          (← logs/ 폴더의 가장 최신 파일 자동 선택)
"""
import json
import sys
from datetime import datetime as _dt
from pathlib import Path

import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ── 상수 ──────────────────────────────────────────────────────────────────────
_POSITIVE_EVENTS = {"우수사원 선정", "연봉 협상 성공", "프로젝트 성공", "헤드헌터 연락", "상사 칭찬", "회식"}

STAT_LINES = [
    ("performance",     "성과",        "#1565C0", True),
    ("boss_favor",      "상사 호감도", "#F57F17", True),
    ("skill",           "업무능력",    "#5c4033", True),
    ("peer_relation",   "동료 관계",   "#2E7D32", False),
    ("reputation",      "평판",        "#6A1B9A", False),
    ("stress",          "스트레스",    "#E53935", True),
    ("energy",          "체력",        "#00ACC1", True),
]

AGENT_PALETTE = [
    "#1565C0", "#E53935", "#2E7D32", "#F57F17",
    "#6A1B9A", "#00838F", "#AD1457", "#4E342E",
]

ACTION_COLORS = {
    # 평일 행동
    "야근한다":            "#E53935",  # 빨강
    "프로젝트에 집중한다":  "#FF7043",  # 주황-빨강
    "상사와 점심을 먹는다": "#FDD835",  # 노랑
    "자기계발을 한다":      "#00897B",  # 청록
    "동료를 도와준다":      "#43A047",  # 초록
    "정치적으로 행동한다":  "#8E24AA",  # 보라
    "이직 준비를 한다":     "#546E7A",  # 회색-파랑
    "휴가를 쓴다":          "#29B6F6",  # 하늘
    # 주말 활동
    "휴식":                "#BDBDBD",  # 연회색
    "자기계발":             "#26A69A",  # 민트
    "사교":                "#66BB6A",  # 연초록
    "인맥관리":             "#AB47BC",  # 연보라
    "여행":                "#FFCA28",  # 금색
}

# 주말 행동 식별자 (평일 행동과 구분)
_WEEKEND_ACTIONS = {"휴식", "자기계발", "사교", "인맥관리", "여행"}


def _display_name(name: str) -> str:
    """에이전트 이름에서 접두사(ReAct_ 등) 제거."""
    for prefix in ("ReAct_", "Batch_", "Chain_", "React_"):
        if name.startswith(prefix):
            return name[len(prefix):]
    return name


def _day_to_label(day: int) -> str:
    """일수를 '1년', '6개월' 등 사람이 읽기 쉬운 레이블로 변환."""
    total_months = round(day / 30)
    years  = total_months // 12
    months = total_months % 12
    if years == 0:
        return f"{total_months}개월"
    if months == 0:
        return f"{years}년"
    return f"{years}년 {months}개월"


def _make_time_ticks(max_day: int) -> tuple[list[int], list[str]]:
    """x축 tick 위치와 레이블 생성 (분기/반기/연 단위)."""
    tickvals, ticktext = [], []
    # 연 단위
    for y in range(1, max_day // 365 + 2):
        d = y * 365
        if d <= max_day + 60:
            tickvals.append(d)
            ticktext.append(f"{y}년")
    # 반기 단위 (연 경계와 겹치지 않는 것만)
    for h in range(1, max_day // 182 + 2):
        d = h * 182
        if d <= max_day + 60 and not any(abs(d - v) < 60 for v in tickvals):
            tickvals.append(d)
            ticktext.append(_day_to_label(d))
    # 분기 단위 (필요 시 — max_day 짧을 때)
    if max_day <= 400:
        for q in range(1, max_day // 90 + 2):
            d = q * 90
            if d <= max_day + 30 and not any(abs(d - v) < 45 for v in tickvals):
                tickvals.append(d)
                ticktext.append(_day_to_label(d))
    # 정렬
    pairs = sorted(zip(tickvals, ticktext))
    return [p[0] for p in pairs], [p[1] for p in pairs]


# ── 로그 로딩 ─────────────────────────────────────────────────────────────────

def load_log(path: Path) -> tuple[dict, list[dict]]:
    result, steps = {}, []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            t = obj.get("type")
            if t == "result":
                result = {k: v for k, v in obj.items() if k != "type"}
            elif t == "step":
                steps.append({k: v for k, v in obj.items() if k != "type"})
    return result, steps


# ── 한 줄 요약 (rule-based) ───────────────────────────────────────────────────

def _one_line_summary(s: dict) -> str:
    perf      = s.get("performance", 0)
    boss      = s.get("boss_favor", 0)
    stress    = s.get("stress", 0)
    energy    = s.get("energy", 0)
    peer      = s.get("peer_relation", 0)
    rep       = s.get("reputation", 0)

    if perf < 25 and boss < 20:
        return "성과도 없고 상사 눈 밖에도 났다 — 짤릴 위기"
    if perf < 25:
        return "성과 부족 — 조만간 면담 각"
    if boss < 20:
        return "상사가 못 마땅히 여기는 게 느껴진다"
    if stress >= 85 and energy <= 25:
        return "스트레스 폭발 직전 + 체력도 바닥"
    if stress >= 85:
        return "스트레스 폭발 직전 — 휴가가 절실하다"
    if stress >= 70:
        return "스트레스가 슬슬 쌓이고 있다"
    if energy <= 10:
        return "몸이 한계 신호를 보내고 있다"
    if energy <= 25:
        return "체력이 위험하다 — 좀 쉬어야 할 것 같다"
    if stress < 35 and energy >= 75 and perf >= 75:
        return "승승장구 중 — 회사원이 천직인듯"
    if perf >= 80:
        return "이 기세면 진급도 문제없다"
    if boss >= 80:
        return "상사한테 완전 낙점됐다"
    if peer >= 80:
        return "사내 인싸 등극 — 동료들 사이 인기 최고"
    if stress < 40 and energy >= 60:
        return "회사생활 이상무!"
    return "그럭저럭 버티는 중"


def _hover_text(s: dict, personality: str = "") -> str:
    events_str = ", ".join(s.get("events", [])) or "없음"
    summary = s.get("comment") or _one_line_summary(s)
    job_changes = s.get("job_changes", 0)
    job_str = f"  |  이직: {job_changes}회" if job_changes > 0 else ""
    personality_str = f"  |  성향: {personality}" if personality else ""
    return (
        f"<b>Day {s['day']}</b>  {s['position']}{job_str}{personality_str}<br>"
        f"행동: {s['action']}<br>"
        f"─────────────────<br>"
        f"성과: {s.get('performance', 0):.0f}  |  "
        f"상사 호감: {s.get('boss_favor', 0):.0f}  |  "
        f"업무능력: {s.get('skill', 0):.0f}<br>"
        f"동료 관계: {s.get('peer_relation', 0):.0f}  |  "
        f"평판: {s.get('reputation', 0):.0f}  |  "
        f"정치력: {s.get('political_skill', 0):.0f}<br>"
        f"스트레스: {s.get('stress', 0):.0f}  |  "
        f"체력: {s.get('energy', 0):.0f}<br>"
        f"연봉: {s['salary']:,}원<br>"
        f"이벤트: {events_str}<br>"
        f"─────────────────<br>"
        f"<i>{summary}</i>"
    )


# ── 단일 실행 인터랙티브 차트 ─────────────────────────────────────────────────

def draw_interactive_html(log_path: Path, show: bool = False) -> Path:
    """
    단일 시뮬레이션 로그 → 인터랙티브 HTML 차트
    - 상단: 핵심 스탯 라인 (마우스 올리면 상태값 + 한 줄 요약)
    - 중단: 연봉 추이
    - 하단: 이벤트 마커 (긍정=초록, 부정=빨강)
    """
    result, steps = load_log(log_path)
    if not steps:
        print(f"[경고] 스텝 데이터가 없습니다: {log_path}")
        return log_path

    days     = [s["day"] for s in steps]
    hovers   = [_hover_text(s) for s in steps]

    # 승진 감지
    promotions = []
    prev_pos = steps[0]["position"]
    for s in steps[1:]:
        if s["position"] != prev_pos:
            promotions.append({"day": s["day"], "from": prev_pos, "to": s["position"]})
            prev_pos = s["position"]

    # 이직 감지
    job_changes_list = []
    prev_jc = steps[0].get("job_changes", 0)
    for s in steps[1:]:
        cur_jc = s.get("job_changes", 0)
        if cur_jc > prev_jc:
            job_changes_list.append({"day": s["day"], "count": cur_jc})
            prev_jc = cur_jc

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.55, 0.25, 0.20],
        subplot_titles=["핵심 스탯 추이", "연봉 추이 (원)", "이벤트"],
        vertical_spacing=0.07,
    )

    # ── Row 1: 스탯 라인 ─────────────────────────────────────────────
    for key, label, color, visible in STAT_LINES:
        values = [s.get(key, 0) for s in steps]
        fig.add_trace(go.Scatter(
            x=days, y=values,
            mode="lines",
            name=label,
            line=dict(color=color, width=1.8),
            visible=True if visible else "legendonly",
            hovertext=hovers,
            hovertemplate="%{hovertext}<extra></extra>",
        ), row=1, col=1)

    # 해고 위험선
    fig.add_hline(y=20, line_dash="dot", line_color="#E53935", line_width=1,
                  opacity=0.5, row=1, col=1,
                  annotation_text="성과 해고 기준", annotation_font_size=9)

    # ── Row 2: 연봉 ──────────────────────────────────────────────────
    salaries = [s["salary"] for s in steps]
    sal_hovers = [
        f"<b>Day {s['day']}</b><br>연봉: {s['salary']:,}원<br>직급: {s['position']}<extra></extra>"
        for s in steps
    ]
    fig.add_trace(go.Scatter(
        x=days, y=salaries,
        mode="lines",
        name="연봉",
        line=dict(color="#1565C0", width=2),
        fill="tozeroy",
        fillcolor="rgba(21,101,192,0.12)",
        hovertemplate="%{text}<extra></extra>",
        text=[f"Day {s['day']}<br>{s['salary']:,}원<br>{s['position']}" for s in steps],
        showlegend=True,
    ), row=2, col=1)

    # ── Row 3: 이벤트 마커 ───────────────────────────────────────────
    evt_days_pos, evt_days_neg = [], []
    evt_text_pos, evt_text_neg = [], []
    for s in steps:
        for evt in s.get("events", []):
            if evt in _POSITIVE_EVENTS:
                evt_days_pos.append(s["day"])
                evt_text_pos.append(f"Day {s['day']}: {evt}")
            else:
                evt_days_neg.append(s["day"])
                evt_text_neg.append(f"Day {s['day']}: {evt}")

    if evt_days_pos:
        fig.add_trace(go.Scatter(
            x=evt_days_pos, y=[1] * len(evt_days_pos),
            mode="markers",
            marker=dict(color="#43A047", size=9, symbol="circle"),
            name="긍정 이벤트",
            text=evt_text_pos,
            hovertemplate="%{text}<extra></extra>",
        ), row=3, col=1)

    if evt_days_neg:
        fig.add_trace(go.Scatter(
            x=evt_days_neg, y=[0.4] * len(evt_days_neg),
            mode="markers",
            marker=dict(color="#E53935", size=9, symbol="circle"),
            name="부정 이벤트",
            text=evt_text_neg,
            hovertemplate="%{text}<extra></extra>",
        ), row=3, col=1)

    # ── 승진 수직선 ──────────────────────────────────────────────────
    for p in promotions:
        fig.add_vline(
            x=p["day"], line_dash="dash", line_color="#7B1FA2", line_width=1.2,
            opacity=0.7,
            annotation_text=f"★ {p['to']}",
            annotation_font_size=10,
            annotation_font_color="#7B1FA2",
        )

    # ── 이직 수직선 ──────────────────────────────────────────────────
    for jc in job_changes_list:
        fig.add_vline(
            x=jc["day"], line_dash="dot", line_color="#546E7A", line_width=1.5,
            opacity=0.7,
            annotation_text=f"🔄 이직{jc['count']}회",
            annotation_font_size=10,
            annotation_font_color="#546E7A",
        )

    # ── 레이아웃 ─────────────────────────────────────────────────────
    agent_name   = result.get("agent", log_path.stem)
    survived     = result.get("survived_days", "?")
    final_pos    = result.get("final_position", "?")
    final_sal    = result.get("final_salary", 0)
    end_status   = "해고" if result.get("is_fired") else "자진퇴사" if result.get("is_resigned") else "정상 종료"

    fig.update_layout(
        title=dict(
            text=f"[{agent_name}]  {survived}일 생존  |  최종: {final_pos}  |  {final_sal:,}원  |  {end_status}",
            font=dict(size=14),
        ),
        hovermode="x unified",
        height=750,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        template="plotly_white",
        margin=dict(t=100, b=40, l=60, r=40),
    )
    max_day = days[-1] if days else 1
    tickvals, ticktext = _make_time_ticks(max_day)
    fig.update_yaxes(range=[0, 105], row=1, col=1)
    fig.update_yaxes(row=3, col=1, showticklabels=False, range=[0, 1.5])
    for row in (1, 2, 3):
        fig.update_xaxes(tickvals=tickvals, ticktext=ticktext, row=row, col=1)
    fig.update_xaxes(title_text="기간", row=3, col=1)

    out_path = log_path.with_suffix(".html")
    fig.write_html(str(out_path))
    print(f"인터랙티브 차트 저장됨: {out_path}")
    if show:
        fig.show()
    return out_path


# ── 여러 성향 비교 차트 ───────────────────────────────────────────────────────

def _composite_score(s: dict) -> float:
    return (
        s.get("skill", 0)           * 0.20 +
        s.get("performance", 0)     * 0.30 +
        s.get("boss_favor", 0)      * 0.25 +
        s.get("reputation", 0)      * 0.15 +
        s.get("political_skill", 0) * 0.10
    )


def _moving_average(values: list[float], window: int = 30) -> list[float]:
    result = []
    for i in range(len(values)):
        start = max(0, i - window + 1)
        result.append(sum(values[start:i+1]) / (i - start + 1))
    return result


def draw_comparison_html(log_paths: list, show: bool = False) -> Path:
    """
    여러 성향 JSONL 로그 → 비교 HTML 차트
    - Row 1: 종합 점수 비교 선 그래프 (30일 이동평균)
    - Row 2: 성향별 회사(평일) 행동 비율 원그래프
    - Row 3: 성향별 주말 행동 비율 원그래프
    """
    from collections import Counter

    datasets = []
    for p in log_paths:
        result, steps = load_log(Path(p))
        if steps:
            raw_name    = result.get("agent", Path(p).stem)
            display     = _display_name(raw_name)
            datasets.append({"name": raw_name, "display": display,
                             "result": result, "steps": steps})

    if not datasets:
        print("[경고] 유효한 데이터셋이 없습니다.")
        return Path(log_paths[0])

    n = len(datasets)

    # 레이아웃: row1=라인 차트(전체 폭), row2=평일 파이 n개, row3=주말 파이 n개
    specs = [
        [{"colspan": n, "type": "xy"}] + [None] * (n - 1),
        [{"type": "pie"}] * n,
        [{"type": "pie"}] * n,
    ]
    weekday_titles = [f"회사 행동, {d['display']}" for d in datasets]
    weekend_titles = [f"주말 행동, {d['display']}" for d in datasets]

    # 시뮬 기간(일) → 연수 표현
    max_day_all = max((d["steps"][-1]["day"] if d["steps"] else 0) for d in datasets)
    years_str = f"{max_day_all // 365}년" if max_day_all >= 365 else f"{max_day_all}일"
    line_title = f"성향별 회사에서 살아남기 — {years_str}의 직장 일대기"

    fig = make_subplots(
        rows=3, cols=n,
        specs=specs,
        subplot_titles=[line_title] + weekday_titles + weekend_titles,
        row_heights=[0.42, 0.28, 0.26],
        vertical_spacing=0.15,
    )

    max_day = 1
    for d in datasets:
        last = d["steps"][-1]["day"] if d["steps"] else 1
        max_day = max(max_day, last)
    tickvals, ticktext = _make_time_ticks(max_day)

    # ── Row 1: 종합 점수 라인 ─────────────────────────────────────────
    for i, d in enumerate(datasets):
        color  = AGENT_PALETTE[i % len(AGENT_PALETTE)]
        steps  = d["steps"]
        days   = [s["day"] for s in steps]
        scores = [_composite_score(s) for s in steps]
        ma     = _moving_average(scores, window=30)
        hovers = [_hover_text(s, personality=d["display"]) for s in steps]
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)

        # 원시 점수 (흐릿)
        fig.add_trace(go.Scatter(
            x=days, y=scores,
            mode="lines",
            legendgroup=d["display"],
            showlegend=False,
            line=dict(color=color, width=0.7),
            opacity=0.22,
            hoverinfo="skip",
        ), row=1, col=1)

        # 이동평균 (진하게)
        fig.add_trace(go.Scatter(
            x=days, y=ma,
            mode="lines",
            name=d["display"],
            legendgroup=d["display"],
            line=dict(color=color, width=2.5),
            fill="tozeroy",
            fillcolor=f"rgba({r},{g},{b},0.07)",
            hovertext=hovers,
            hovertemplate="%{hovertext}<extra></extra>",
        ), row=1, col=1)

        # 승진 마커 (그래프 위 ★ 점으로 표시, 호버로 상세 확인)
        promo_days, promo_scores, promo_texts = [], [], []
        prev_pos = steps[0]["position"]
        for s in steps[1:]:
            if s["position"] != prev_pos:
                promo_days.append(s["day"])
                promo_scores.append(_composite_score(s))
                promo_texts.append(
                    f"<b>★ 승진!</b><br>{d['display']}: {prev_pos} → {s['position']}<br>"
                    f"Day {s['day']} ({_day_to_label(s['day'])})<br>"
                    f"연봉: {s['salary']:,}원"
                )
                prev_pos = s["position"]
        if promo_days:
            fig.add_trace(go.Scatter(
                x=promo_days, y=promo_scores,
                mode="markers",
                marker=dict(color=color, size=12, symbol="star", line=dict(color="white", width=1)),
                legendgroup=d["display"],
                showlegend=False,
                hovertemplate="%{text}<extra></extra>",
                text=promo_texts,
            ), row=1, col=1)

        # 이직 마커 (그래프 위 🔄 점으로 표시)
        jc_days, jc_scores, jc_texts = [], [], []
        prev_jc = steps[0].get("job_changes", 0)
        for s in steps[1:]:
            cur_jc = s.get("job_changes", 0)
            if cur_jc > prev_jc:
                jc_days.append(s["day"])
                jc_scores.append(_composite_score(s))
                jc_texts.append(
                    f"<b>🔄 이직 {cur_jc}회</b><br>{d['display']}<br>"
                    f"Day {s['day']} ({_day_to_label(s['day'])})<br>"
                    f"연봉: {s['salary']:,}원  |  {s['position']}"
                )
                prev_jc = cur_jc
        if jc_days:
            fig.add_trace(go.Scatter(
                x=jc_days, y=jc_scores,
                mode="markers",
                marker=dict(color=color, size=10, symbol="diamond", line=dict(color="white", width=1)),
                legendgroup=d["display"],
                showlegend=False,
                hovertemplate="%{text}<extra></extra>",
                text=jc_texts,
            ), row=1, col=1)

    fig.update_xaxes(tickvals=tickvals, ticktext=ticktext,
                     title_text="기간", row=1, col=1)
    fig.update_yaxes(range=[0, 100], title_text="종합 점수", row=1, col=1)

    # ── Row 2 & 3: 평일 / 주말 행동 비율 파이 차트 ────────────────────
    all_weekday_actions: list[str] = []
    all_weekend_actions: list[str] = []
    seen_wd: set[str] = set()
    seen_we: set[str] = set()

    for d in datasets:
        for s in d["steps"]:
            a = s["action"]
            if a in _WEEKEND_ACTIONS:
                if a not in seen_we:
                    all_weekend_actions.append(a)
                    seen_we.add(a)
            else:
                if a not in seen_wd:
                    all_weekday_actions.append(a)
                    seen_wd.add(a)

    for i, d in enumerate(datasets):
        weekday_steps = [s for s in d["steps"] if s["action"] not in _WEEKEND_ACTIONS]
        weekend_steps = [s for s in d["steps"] if s["action"] in _WEEKEND_ACTIONS]

        for row_idx, step_subset in [(2, weekday_steps), (3, weekend_steps)]:
            if not step_subset:
                continue
            counts = Counter(s["action"] for s in step_subset)
            labels = list(counts.keys())
            values = list(counts.values())
            colors = [ACTION_COLORS.get(lbl, "#BDBDBD") for lbl in labels]
            total  = sum(values)
            custom = [f"{lbl}<br>{cnt}회 ({cnt/total*100:.1f}%)"
                      for lbl, cnt in zip(labels, values)]

            fig.add_trace(go.Pie(
                labels=labels,
                values=values,
                marker=dict(colors=colors, line=dict(color="#fff", width=1.5)),
                textinfo="percent",
                textposition="inside",
                textfont=dict(size=10),
                hovertemplate="%{customdata}<extra></extra>",
                customdata=custom,
                legendgroup="weekday_actions" if row_idx == 2 else "weekend_actions",
                showlegend=False,
                hole=0.25,
            ), row=row_idx, col=i + 1)

    # 평일 행동 범례 (legend2)
    for action in all_weekday_actions:
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode="markers",
            marker=dict(color=ACTION_COLORS.get(action, "#BDBDBD"), size=10, symbol="square"),
            name=action,
            legend="legend2",
            showlegend=True,
        ), row=1, col=1)

    # 주말 행동 범례 (legend3)
    for action in all_weekend_actions:
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode="markers",
            marker=dict(color=ACTION_COLORS.get(action, "#BDBDBD"), size=10, symbol="square"),
            name=action,
            legend="legend3",
            showlegend=True,
        ), row=1, col=1)

    fig.update_layout(
        title=dict(
            text=line_title,
            font=dict(size=14),
        ),
        hovermode="x unified",
        height=1150,
        # 에이전트명 범례 (선 그래프 상단)
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        # 평일 행동 범례 (회사 행동 파이차트 바로 아래, row2-row3 사이 간격)
        legend2=dict(
            orientation="h", yanchor="top", y=0.345, xanchor="center", x=0.5,
            font=dict(size=11), title=dict(text="회사 행동  ", side="left"),
        ),
        # 주말 행동 범례 (주말 행동 파이차트 바로 아래)
        legend3=dict(
            orientation="h", yanchor="top", y=-0.02, xanchor="center", x=0.5,
            font=dict(size=11), title=dict(text="주말 행동  ", side="left"),
        ),
        template="plotly_white",
        margin=dict(t=100, b=150, l=60, r=40),
    )

    names_tag = "_".join(d["display"] for d in datasets)
    out_path  = Path(log_paths[0]).parent / f"{_dt.now().strftime('%y%m%d_%H%M%S')}_comparison_{names_tag}.html"
    fig.write_html(str(out_path))
    print(f"비교 차트 저장됨: {out_path}")
    if show:
        fig.show()
    return out_path


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) >= 2:
        path = Path(sys.argv[1])
    else:
        logs = sorted(Path("logs").glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not logs:
            print("logs/ 폴더에 .jsonl 파일이 없습니다.")
            sys.exit(1)
        path = logs[-1]
        print(f"최신 로그 파일 사용: {path}")

    if not path.exists():
        print(f"파일을 찾을 수 없습니다: {path}")
        sys.exit(1)

    draw_interactive_html(path, show=True)


if __name__ == "__main__":
    main()

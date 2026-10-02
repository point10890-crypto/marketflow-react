"""Deterministic comparison of published Lotto 6/45 sets and official results.

No credentials, language models, image providers, or publishing are used here.
Draw times and numbering are interpreted in Korea time, independently of the host.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
import re
from typing import Any, Iterator
from urllib.parse import parse_qs, urlparse

import requests


KST = timezone(timedelta(hours=9), "Asia/Seoul")
FIRST_DRAW_DATE = date(2002, 12, 7)
OFFICIAL_RESULT_URL = "https://www.dhlottery.co.kr/lt645/result"
OFFICIAL_API_URL = "https://www.dhlottery.co.kr/lt645/selectPstLt645InfoNew.do"
_NUMBER_TEXT = re.compile(r"\s*\d{1,2}(?:\s*[,·]\s*\d{1,2})+\s*\Z")
_NUMBER_SEQUENCE = re.compile(r"(?<!\d)\d{1,2}(?:\s*[,·]\s*\d{1,2}){2,}(?!\d)")
_RECOMMENDATION_HEADING = re.compile(r"추천\s*(?:번호|조합)|후보\s*조합")


class LottoResultError(ValueError):
    """A source cannot be safely treated as a verified recommendation/result."""


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise LottoResultError(f"{label}: 정수가 아닙니다")
    if isinstance(value, str) and not re.fullmatch(r"[0-9]+", value):
        raise LottoResultError(f"{label}: 정수가 아닙니다")
    return int(value)


def draw_datetime(draw_no: int, hour: int = 20, minute: int = 35) -> datetime:
    """Broadcast cutoff; official current guidance says approximately 20:35 KST."""
    draw_no = _integer(draw_no, "회차")
    if draw_no < 1:
        raise LottoResultError("회차는 양수여야 합니다")
    try:
        day = FIRST_DRAW_DATE + timedelta(weeks=draw_no - 1)
        return datetime(day.year, day.month, day.day, hour, minute, tzinfo=KST)
    except (OverflowError, ValueError) as exc:
        raise LottoResultError("회차 날짜가 유효하지 않습니다") from exc


def _now_kst(now: datetime | None) -> datetime:
    value = now or datetime.now(KST)
    return value.replace(tzinfo=KST) if value.tzinfo is None else value.astimezone(KST)


def recommendation_created_before_draw(created_at: Any, draw_no: int) -> bool:
    """Database timestamps without an offset are UTC, as in Post.created_at."""
    try:
        value = created_at if isinstance(created_at, datetime) else datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value < draw_datetime(draw_no)
    except (ValueError, TypeError, LottoResultError):
        return False


def _validate_numbers(numbers: Any) -> list[int]:
    if not isinstance(numbers, (tuple, list)) or len(numbers) != 6:
        raise LottoResultError("추천 번호는 정확히 6개여야 합니다")
    validated = [_integer(number, "번호") for number in numbers]
    if len(set(validated)) != 6 or any(number < 1 or number > 45 for number in validated):
        raise LottoResultError("번호는 중복 없이 1~45 범위여야 합니다")
    return validated


def get_numbers(draw: dict) -> list[int]:
    try:
        return _validate_numbers([draw[f"drwtNo{i}"] for i in range(1, 7)])
    except (KeyError, TypeError) as exc:
        raise LottoResultError("당첨 번호 필드가 누락됐습니다") from exc


def validate_draw(draw: dict, expected_draw_no: int | None = None, now: datetime | None = None) -> dict:
    try:
        number = _integer(draw["drwNo"], "회차")
        expected_date = draw_datetime(number, 21, 0)
        if expected_draw_no is not None and number != _integer(expected_draw_no, "요청 회차"):
            raise LottoResultError("공식 결과 회차가 요청 회차와 다릅니다")
        actual_date = date.fromisoformat(str(draw["drwNoDate"]))
        if actual_date != expected_date.date():
            raise LottoResultError("회차와 추첨일이 일치하지 않습니다")
        if _now_kst(now) < expected_date:
            raise LottoResultError("추첨 결과 확정 대기 중입니다")
        numbers = get_numbers(draw)
        bonus = _integer(draw["bnusNo"], "보너스")
        if bonus < 1 or bonus > 45 or bonus in numbers:
            raise LottoResultError("보너스 번호가 유효하지 않습니다")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, LottoResultError):
            raise
        raise LottoResultError("추첨 데이터가 유효하지 않습니다") from exc
    return dict(draw, drwNo=number, drwNoDate=actual_date.isoformat(), bnusNo=bonus,
                **{f"drwtNo{i}": value for i, value in enumerate(numbers, 1)})


def validate_official_draw(draw: dict, expected_draw_no: int | None = None, now: datetime | None = None) -> dict:
    """Shared prerequisite for both compared results and comparison-pending posts."""
    moment = _now_kst(now)
    draw = validate_draw(draw, expected_draw_no=expected_draw_no, now=moment)
    parsed_source = urlparse(str(draw.get("source_url") or ""))
    if (draw.get("source") != "dhlottery_official" or parsed_source.scheme != "https"
            or parsed_source.netloc != "www.dhlottery.co.kr"
            or parsed_source.path != "/lt645/selectPstLt645InfoNew.do"
            or parse_qs(parsed_source.query).get("srchLtEpsd") != [str(draw["drwNo"])]):
        raise LottoResultError("공식 회차 재조회 출처를 확인할 수 없습니다")
    try:
        fetched_at = datetime.fromisoformat(str(draw.get("fetched_at") or "").replace("Z", "+00:00"))
        if fetched_at.tzinfo is None or fetched_at < draw_datetime(draw["drwNo"], 21, 0) or fetched_at > moment:
            raise ValueError("결과 확정 후 실제 조회 시각 필요")
    except ValueError as exc:
        raise LottoResultError("공식 추첨 결과 확인 시각이 유효하지 않습니다") from exc
    return draw


def fetch_official_draw(draw_no: int, *, now: datetime | None = None, session: Any = None) -> dict | None:
    """Exact draw from the current official API; no unofficial fallback for results."""
    draw_no = _integer(draw_no, "회차")
    moment = _now_kst(now)
    if moment < draw_datetime(draw_no, 21, 0):
        return None
    try:
        response = (session or requests).get(
            OFFICIAL_API_URL,
            params={"srchDir": "center", "srchLtEpsd": draw_no},
            headers={"Referer": OFFICIAL_RESULT_URL, "User-Agent": "Mozilla/5.0"},
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        items = payload["data"]["list"]
        if not isinstance(items, list):
            raise LottoResultError("공식 결과 목록이 유효하지 않습니다")
        matched = [item for item in items if isinstance(item, dict) and _integer(item.get("ltEpsd"), "공식 회차") == draw_no]
        if not matched:
            return None
        if len(matched) != 1:
            raise LottoResultError("동일 공식 회차가 중복돼 있습니다")
        item = matched[0]
        date_text = str(item["ltRflYmd"])
        if not re.fullmatch(r"\d{8}", date_text):
            raise LottoResultError("공식 추첨일 형식이 유효하지 않습니다")
        parsed = {
            "drwNo": item["ltEpsd"],
            "drwNoDate": f"{date_text[:4]}-{date_text[4:6]}-{date_text[6:]}",
            **{f"drwtNo{i}": item[f"tm{i}WnNo"] for i in range(1, 7)},
            "bnusNo": item["bnsWnNo"],
            "source": "dhlottery_official",
            "source_url": f"{OFFICIAL_API_URL}?srchDir=center&srchLtEpsd={draw_no}",
            "fetched_at": moment.astimezone(timezone.utc).isoformat(),
        }
        prizes = {}
        for rank in range(1, 6):
            value = item.get(f"rnk{rank}WnAmt")
            if value is not None:
                prize = _integer(value, "회차 당첨금")
                if prize < 0:
                    raise LottoResultError("공식 당첨금이 음수입니다")
                prizes[str(rank)] = prize
        parsed["prizes"] = prizes
        return validate_official_draw(parsed, expected_draw_no=draw_no, now=moment)
    except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, LottoResultError):
            raise
        raise LottoResultError("공식 추첨 결과 조회 또는 검증에 실패했습니다") from exc


def evaluate_set(numbers: list[int], draw: dict) -> dict:
    numbers = _validate_numbers(numbers)
    winning = get_numbers(draw)
    bonus = _integer(draw.get("bnusNo"), "보너스")
    if bonus < 1 or bonus > 45 or bonus in winning:
        raise LottoResultError("보너스 번호가 유효하지 않습니다")
    matched = sorted(set(numbers) & set(winning))
    count = len(matched)
    bonus_match = bonus in numbers
    rank = 1 if count == 6 else (2 if bonus_match else 3) if count == 5 else 4 if count == 4 else 5 if count == 3 else None
    return {"matched_numbers": matched, "match_count": count, "bonus_match": bonus_match,
            "rank": rank, "label": f"{rank}등" if rank else "미당첨"}


def canonical_recommendation_html(draw_no: int, candidates: dict) -> str:
    draw_no = _integer(draw_no, "회차")
    draw_datetime(draw_no)
    rows = []
    if not isinstance(candidates, dict):
        raise LottoResultError("추천 조합 구조가 유효하지 않습니다")
    for style, data in candidates.items():
        if not isinstance(data, dict) or not isinstance(data.get("sets"), list) or not data["sets"]:
            raise LottoResultError("추천 성향에 조합이 없습니다")
        for index, item in enumerate(data["sets"], 1):
            if not isinstance(item, dict):
                raise LottoResultError("추천 조합 구조가 유효하지 않습니다")
            numbers = _validate_numbers(item.get("numbers"))
            rows.append(f"<tr><td>{escape(str(style))}</td><td>{index}</td><td><strong>{', '.join(map(str, numbers))}</strong></td></tr>")
    if not rows:
        raise LottoResultError("추천 조합이 없습니다")
    return (f'<h2>🎯 추천 번호 전체 조합 (제{draw_no}회)</h2>'
            f'<table data-lotto-recommendations="1" data-draw-no="{draw_no}"><thead><tr><th>성향</th><th>세트</th><th>추천 번호</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


@dataclass
class _Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: Any = None

    def text(self) -> str:
        return "".join(child if isinstance(child, str) else child.text() for child in self.children)

    def nodes(self) -> Iterator[_Node]:
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.nodes()

    def events(self):
        yield "start", self
        for child in self.children:
            if isinstance(child, str):
                yield "text", child
            else:
                yield from child.events()
        yield "end", self


class _TreeParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root")
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), parent=self.current)
        self.current.children.append(node)
        if tag not in {"br", "img", "hr", "input", "meta", "link", "source", "wbr"}:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(_Node(tag, dict(attrs), parent=self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def _numbers_text(text: str) -> list[int] | None:
    if not _NUMBER_TEXT.fullmatch(text):
        return None
    return _validate_numbers([int(value) for value in re.findall(r"\d+", text)])


def _table_rows(table: _Node) -> list[dict]:
    rows = []
    next_index: Counter = Counter()
    for row in table.nodes():
        if row.tag != "tr":
            continue
        cells = [node for node in row.children if isinstance(node, _Node) and node.tag == "td"]
        if not cells:
            continue
        if len(cells) != 3:
            raise LottoResultError("추천 표 열 구성이 유효하지 않습니다")
        style = cells[0].text().strip()
        index = _integer(cells[1].text().strip(), "세트 번호")
        numbers = _numbers_text(cells[2].text().strip())
        next_index[style] += 1
        if not style or numbers is None or index != next_index[style]:
            raise LottoResultError("추천 표의 성향, 세트 또는 번호가 유효하지 않습니다")
        rows.append({"style": style, "set_index": index, "numbers": numbers})
    if not rows:
        raise LottoResultError("추천 표에 조합이 없습니다")
    return rows


def extract_recommendation_sets(content: str, draw_no: int | None = None) -> list[dict]:
    """Only explicit recommendation blocks; never infer sets from hot/draw numbers."""
    if not isinstance(content, str) or not content.strip():
        raise LottoResultError("추천 원문이 없습니다")
    parser = _TreeParser()
    parser.feed(content)
    canonical = [node for node in parser.root.nodes() if node.tag == "table" and node.attrs.get("data-lotto-recommendations") == "1"]
    if canonical:
        if len(canonical) != 1:
            raise LottoResultError("공식 비교 대상 표가 여러 개입니다")
        recorded_draw = _integer(canonical[0].attrs.get("data-draw-no"), "추천 회차")
        if draw_no is not None and recorded_draw != _integer(draw_no, "요청 회차"):
            raise LottoResultError("추천 원문 회차가 다릅니다")
        return _table_rows(canonical[0])
    rows = []
    active_level = None
    style = "추천"
    counts: Counter = Counter()
    blocks = 0
    visible_recommendations = []
    for event, node in parser.root.events():
        if event == "text":
            if active_level is not None:
                visible_recommendations.append(node)
            continue
        if event == "end":
            if active_level is not None and node.tag in {"li", "p", "div", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}:
                visible_recommendations.append("\n")
            continue
        if node.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(node.tag[1])
            heading = node.text().strip()
            if _RECOMMENDATION_HEADING.search(heading):
                found_draw = re.search(r"제\s*(\d+)\s*회", heading)
                if draw_no is not None and found_draw and int(found_draw.group(1)) != _integer(draw_no, "요청 회차"):
                    raise LottoResultError("추천 원문 회차가 다릅니다")
                blocks += 1
                active_level = level
                style = "추천"
            elif active_level is not None and level <= active_level:
                active_level = None
            elif active_level is not None:
                style = re.split(r"\s+[—–-]\s+|\s*[:：]\s*", heading, maxsplit=1)[0].strip()
        elif active_level is not None and node.tag == "strong":
            numbers = _numbers_text(node.text().strip())
            if numbers is not None:
                counts[style] += 1
                parent = node.parent
                while parent and parent.tag not in {"li", "p", "root"}:
                    parent = parent.parent
                if parent:
                    explicit_index = re.search(r"세트\s*(\d+)", parent.text())
                    if explicit_index and int(explicit_index.group(1)) != counts[style]:
                        raise LottoResultError("추천 세트가 누락됐거나 순서가 모호합니다")
                rows.append({"style": style, "set_index": counts[style], "numbers": numbers})
    if not rows or blocks != 1:
        raise LottoResultError("추천 원문 조합을 확실하게 복원할 수 없습니다")
    visible_text = "".join(visible_recommendations)
    sequences = _NUMBER_SEQUENCE.findall(visible_text)
    labels = re.findall(r"세트\s*\d+|\d+\s*세트", visible_text)
    if (len(sequences) != len(rows) or len(labels) > len(rows)
            or any(len(re.findall(r"\d+", sequence)) != 6 for sequence in sequences)):
        raise LottoResultError("다른 서식의 미해석 추천 세트가 있어 전체 대조를 보류합니다")
    return rows


def build_result_report(draw: dict, recommendations: list[dict], source_post: dict) -> dict:
    draw = validate_official_draw(draw)
    source_url = str(draw.get("source_url") or "")
    if not recommendations or not isinstance(source_post, dict):
        raise LottoResultError("원문 추천 조합 확인이 필요합니다")
    if not recommendation_created_before_draw(source_post.get("created_at"), draw["drwNo"]):
        raise LottoResultError("추첨 전 추천 게시 시각을 확인할 수 없습니다")
    post_id = _integer(source_post.get("post_id"), "원문 게시글")
    if post_id < 1:
        raise LottoResultError("추천 원문 게시글이 유효하지 않습니다")
    rows, table_rows = [], []
    rank_counts: Counter = Counter()
    seen = set()
    for recommendation in recommendations:
        style = str(recommendation.get("style") or "").strip()
        index = _integer(recommendation.get("set_index"), "세트 번호")
        if not style or index < 1 or (style, index) in seen:
            raise LottoResultError("추천 조합 식별자가 중복되거나 유효하지 않습니다")
        seen.add((style, index))
        numbers = _validate_numbers(recommendation.get("numbers"))
        result = evaluate_set(numbers, draw)
        row = {"style": style, "set_index": index, "numbers": numbers, **result}
        rows.append(row)
        rank_counts[str(result["rank"] or "none")] += 1
        matched = ", ".join(map(str, result["matched_numbers"])) or "없음"
        table_rows.append(f"<tr><td>{escape(style)} {index}세트</td><td>{', '.join(map(str, numbers))}</td>"
                          f"<td>{matched} ({result['match_count']}개)</td><td>{'일치' if result['bonus_match'] else '불일치'}</td><td>{result['label']}</td></tr>")
    winning = sum(rank_counts[str(rank)] for rank in range(1, 6))
    summary = {"total_sets": len(rows), "winning_sets": winning, "non_winning_sets": rank_counts["none"],
               "rank_counts": {str(rank): rank_counts[str(rank)] for rank in range(1, 6)},
               "max_match_count": max(row["match_count"] for row in rows)}
    legacy = source_post.get("recovery_kind") not in {"snapshot", "published_snapshot", "ledger"}
    recovery_note = ("기존 게시글 현재 본문에서 추천 조합을 복원했습니다. 추첨 전 고정 스냅샷이 없어 사후 편집 여부까지 증명하는 기록은 아닙니다."
                     if legacy else "추첨 전에 게시한 추천 조합의 저장 기록을 기준으로 대조했습니다.")
    original_url = f"https://bit-man.net/dashboard/community/post/{post_id}"
    source_time = escape(str(draw["fetched_at"]))
    rank_text = " · ".join(f"{rank}등 {rank_counts[str(rank)]}조합" for rank in range(1, 6))
    title = f"제{draw['drwNo']}회 로또 추천 번호 결과 — 전체 조합 대조"
    content = (f"<h2>지난 추천 번호 · 공식 추첨 결과</h2><p>제{draw['drwNo']}회 ({draw['drwNoDate']}) 본번호: "
               f"<strong>{', '.join(map(str, get_numbers(draw)))}</strong> / 보너스: <strong>{draw['bnusNo']}</strong></p>"
               f'<p><a href="{original_url}">지난 추천 원문 #{post_id}</a> · 게시 시각: {escape(str(source_post.get("created_at")))}</p>'
               f'<p><a href="{escape(source_url, quote=True)}">동행복권 공식 추첨 결과</a> · 확인 시각: {source_time}</p>'
               f"<p>{recovery_note}</p><h2>전체 {len(rows)}조합 대조</h2>"
               f"<p>{rank_text} · 미당첨 {summary['non_winning_sets']}조합. 성공 조합과 미당첨 조합을 모두 공개합니다.</p>"
               f"<table><thead><tr><th>성향 · 세트</th><th>게시한 추천 번호</th><th>본번호 일치</th><th>보너스</th><th>대조 등수</th></tr></thead><tbody>{''.join(table_rows)}</tbody></table>"
               "<p>보너스 번호는 본번호 5개가 일치할 때에만 2등 판정에 사용합니다. 본번호 3개 미만은 미당첨입니다.</p>"
               "<p>위 등수는 추천 번호의 대조 결과입니다. 실제 구매 여부나 당첨금 수령을 확인한 결과가 아닙니다. "
               "로또는 무작위 추첨이며 과거 통계와 추천 점수는 미래 당첨 가능성을 높인다는 증거가 아닙니다. 재미와 참고 범위에서 이용해 주세요.</p>")
    return {"title": title, "content": content, "rows": rows, "summary": summary,
            "draw_no": draw["drwNo"], "source_post": dict(source_post), "official_draw": draw}

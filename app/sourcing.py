"""AI소싱기 / 아이템 스카우트 - 도매 상품 후보를 규칙 기반으로 스코어링/랭킹.

실제 딥러닝 모델이 아니라 "마진율 + 수요(검색량) + 경쟁강도"를 조합한
투명한 통계 기반 스코어링이다. 원본 광고의 "AI소싱기"라는 표현을 그대로
쓰지 않고, 사용자에게 어떤 기준으로 점수가 매겨지는지 명확히 보여준다.
"""

import csv
import io
import math

REQUIRED_COLUMNS = ["상품명", "도매가", "예상판매가"]
OPTIONAL_COLUMNS = ["카테고리", "월간검색량", "경쟁상품수"]


def parse_candidates_csv(file_bytes):
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = [dict(r) for r in reader]
    return reader.fieldnames or [], rows


def _to_float(v, default=0.0):
    try:
        if v is None or v == "":
            return default
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return default


def score_candidates(rows, weight_margin=0.6, weight_demand=0.25, weight_competition=0.15):
    parsed = []
    for row in rows:
        cost = _to_float(row.get("도매가"))
        price = _to_float(row.get("예상판매가"))
        search_vol = _to_float(row.get("월간검색량"), default=None) if row.get("월간검색량") not in (None, "") else None
        competitors = _to_float(row.get("경쟁상품수"), default=None) if row.get("경쟁상품수") not in (None, "") else None

        margin_amount = price - cost
        margin_pct = (margin_amount / price * 100) if price else 0.0

        parsed.append({
            "name": row.get("상품명") or "",
            "category": row.get("카테고리") or "",
            "cost": cost,
            "price": price,
            "margin_amount": round(margin_amount, 2),
            "margin_pct": round(margin_pct, 2),
            "search_vol": search_vol,
            "competitors": competitors,
        })

    max_search = max([p["search_vol"] for p in parsed if p["search_vol"] is not None], default=None)
    max_competitors = max([p["competitors"] for p in parsed if p["competitors"] is not None], default=None)

    has_demand = max_search is not None and max_search > 0
    has_competition = max_competitors is not None and max_competitors > 0

    # 제공된 항목이 적으면 남은 가중치를 마진 점수에 몰아준다.
    w_margin, w_demand, w_comp = weight_margin, weight_demand, weight_competition
    if not has_demand:
        w_margin += w_demand
        w_demand = 0
    if not has_competition:
        w_margin += w_comp
        w_comp = 0

    for p in parsed:
        margin_score = max(0.0, min(100.0, p["margin_pct"]))

        demand_score = 0.0
        if has_demand and p["search_vol"] is not None and max_search:
            demand_score = 100 * math.log1p(p["search_vol"]) / math.log1p(max_search)

        competition_score = 0.0
        if has_competition and p["competitors"] is not None and max_competitors:
            competition_score = 100 * (1 - (p["competitors"] / max_competitors))

        total = (
            margin_score * w_margin
            + demand_score * w_demand
            + competition_score * w_comp
        )
        p["margin_score"] = round(margin_score, 1)
        p["demand_score"] = round(demand_score, 1)
        p["competition_score"] = round(competition_score, 1)
        p["score"] = round(total, 1)

    parsed.sort(key=lambda x: x["score"], reverse=True)
    return parsed


def to_csv_bytes(parsed_rows):
    buf = io.StringIO()
    fieldnames = [
        "name", "category", "cost", "price", "margin_amount", "margin_pct",
        "search_vol", "competitors", "score",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(parsed_rows)
    return buf.getvalue().encode("utf-8-sig")

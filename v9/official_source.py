"""Read completed Mark Six results directly from the HKJC GraphQL endpoint.

The query text is the allowlisted query used by the public HKJC results page.
No third-party result is allowed to become a verified draw in this subsystem.
"""
from __future__ import annotations

import calendar
import gzip
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date

ENDPOINT = "https://info.cld.hkjc.com/graphql/base/"
SOURCE_URL = "https://bet.hkjc.com/en/mark"
QUERY = (
    "\n        fragment lotteryDrawsFragment on LotteryDraw {\n    id\n    year\n    no\n"
    "    openDate\n    closeDate\n    drawDate\n    status\n    snowballCode\n"
    "    snowballName_en\n    snowballName_ch\n    lotteryPool {\n      sell\n      status\n"
    "      totalInvestment\n      jackpot\n      unitBet\n      estimatedPrize\n"
    "      derivedFirstPrizeDiv\n      lotteryPrizes {\n        type\n        winningUnit\n"
    "        dividend\n      }\n    }\n    drawResult {\n      drawnNo\n      xDrawnNo\n"
    "    }\n  }\n"
    "        query marksixResult($lastNDraw: Int, $startDate: String, $endDate: String, "
    "$drawType: LotteryDrawType) {\n            lotteryDraws(lastNDraw: $lastNDraw, "
    "startDate: $startDate, endDate: $endDate, drawType: $drawType) {\n"
    "              ...lotteryDrawsFragment\n            }\n        }\n    "
)
UPCOMING_QUERY = (
    "\n\tfragment lotteryDrawsFragment on LotteryDraw {\n\t\tid\n\t\tyear\n\t\tno\n"
    "\t\topenDate\n\t\tcloseDate\n\t\tdrawDate\n\t\tstatus\n\t\tsnowballCode\n"
    "\t\tsnowballName_en\n\t\tsnowballName_ch\n\t\tlotteryPool {\n\t\t\tsell\n"
    "\t\t\tstatus\n\t\t\ttotalInvestment\n\t\t\tjackpot\n\t\t\tunitBet\n"
    "\t\t\testimatedPrize\n\t\t\tderivedFirstPrizeDiv\n\t\t\tlotteryPrizes {\n"
    "\t\t\t\ttype\n\t\t\t\twinningUnit\n\t\t\t\tdividend\n\t\t\t}\n\t\t}\n"
    "\t\tdrawResult {\n\t\t\tdrawnNo\n\t\t\txDrawnNo\n\t\t}\n\t}\n\n"
    "\tquery marksixDraw {\n\t\ttimeOffset {\n\t\t\tm6\n\t\t\tts\n\t\t}\n"
    "\t\tlotteryDraws {\n\t\t\t...lotteryDrawsFragment\n\t\t}\n\t}\n"
)
HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0",
    "Origin": "https://bet.hkjc.com",
    "Referer": "https://bet.hkjc.com/",
}


@dataclass(frozen=True)
class OfficialDraw:
    period: str
    draw_date: str
    main: tuple[int, ...]
    special: int
    source_id: str


def _request(variables: dict, *, operation: str = "marksixResult", query: str = QUERY) -> list[dict]:
    body = json.dumps({"operationName": operation, "variables": variables, "query": query}).encode()
    request = urllib.request.Request(ENDPOINT, data=body, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
            break
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    payload = json.loads(raw)
    if payload.get("errors") or not isinstance(payload.get("data", {}).get("lotteryDraws"), list):
        raise RuntimeError(f"HKJC official response invalid: {payload.get('errors')}")
    return payload["data"]["lotteryDraws"]


def fetch_upcoming() -> dict | None:
    """Only an official Defined draw may supply the target date."""
    rows = _request({}, operation="marksixDraw", query=UPCOMING_QUERY)
    completed = [row for row in rows if row.get("status") == "Result"]
    upcoming = [row for row in rows if row.get("status") == "Defined" and row.get("drawDate")]
    if not completed or not upcoming:
        return None
    latest_date = max(str(row["drawDate"])[:10] for row in completed)
    chosen = min(upcoming, key=lambda row: row["drawDate"])
    target_date = str(chosen["drawDate"])[:10]
    if target_date <= latest_date:
        raise ValueError("Official upcoming date is not after latest result")
    return {"date": target_date, "source_id": str(chosen["id"]), "status": "Defined", "source": ENDPOINT}


def _parse(item: dict) -> OfficialDraw | None:
    if item.get("status") != "Result" or not item.get("drawResult"):
        return None
    draw_date = str(item["drawDate"])[:10]
    year, number = int(item["year"]), int(item["no"])
    main = tuple(sorted(map(int, item["drawResult"]["drawnNo"])))
    special = int(item["drawResult"]["xDrawnNo"])
    source_id = str(item["id"])
    source_number = "".join(ch for ch in source_id[4:] if ch.isdigit())
    if not source_id.startswith(str(year)) or not source_number or int(source_number) != number or date.fromisoformat(draw_date).year != year:
        raise ValueError(f"Inconsistent official draw identity: {source_id}")
    if len(main) != 6 or len(set(main)) != 6 or special in main or not all(1 <= n <= 49 for n in (*main, special)):
        raise ValueError(f"Invalid official balls: {source_id}")
    return OfficialDraw(f"{year % 100:02d}/{number:03d}", draw_date, main, special, source_id)


def fetch_recent(n: int = 20) -> list[OfficialDraw]:
    if not 1 <= n <= 100:
        raise ValueError("Recent batch must be 1..100; use monthly windows for history")
    rows = [_parse(item) for item in _request({"lastNDraw": n})]
    return sorted((row for row in rows if row), key=lambda row: row.draw_date)


def fetch_month(year: int, month: int) -> list[OfficialDraw]:
    last = calendar.monthrange(year, month)[1]
    rows = [_parse(item) for item in _request({"startDate": f"{year:04d}{month:02d}01", "endDate": f"{year:04d}{month:02d}{last:02d}"})]
    return sorted((row for row in rows if row), key=lambda row: row.draw_date)


def fetch_months(first: tuple[int, int], last: tuple[int, int], workers: int = 4) -> list[OfficialDraw]:
    months = []
    year, month = first
    while (year, month) <= last:
        months.append((year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    by_date: dict[str, OfficialDraw] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_month, year, month): (year, month) for year, month in months}
        for future in as_completed(futures):
            month_draws = future.result()
            for draw in month_draws:
                previous = by_date.get(draw.draw_date)
                if previous and previous != draw:
                    raise ValueError(f"Conflicting official draws: {draw.draw_date}")
                by_date[draw.draw_date] = draw
    draws = sorted(by_date.values(), key=lambda row: row.draw_date)
    if len({row.period for row in draws}) != len(draws):
        raise ValueError("Duplicate official period")
    return draws

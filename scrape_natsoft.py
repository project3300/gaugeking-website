from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).parent
CONFIG_PATH = ROOT / "config.yaml"
OUTPUT_PATH = ROOT / "data" / "results.json"


def load_config() -> dict[str, Any]:
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def unique_headers(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for i, raw in enumerate(headers):
        base = clean(raw) or f"column_{i + 1}"
        count = seen.get(base, 0) + 1
        seen[base] = count
        result.append(base if count == 1 else f"{base}_{count}")
    return result


def extract_fixed_width_rows(html: str) -> list[dict[str, str]]:
    """Parse the legacy Natsoft fixed-width leaderboard into one row per competitor."""
    soup = BeautifulSoup(html, "html.parser")
    text = clean(soup.get_text(" ", strip=True))

    row_pattern = re.compile(
        r"(?:^|\s)(?P<position>\d{1,3})\s+"
        r"(?P<car>\d{2,4})\s+"
        r"(?P<rest>.*?)"
        r"(?=(?:\s+\d{1,3}\s+\d{2,4}\s+[A-Za-z])|(?:\s+Fastest Lap Av\.Speed)|(?:\s+Issue#)|$)",
        re.IGNORECASE,
    )

    tail_pattern = re.compile(
        r"^(?P<identity>.+?)\s+"
        r"(?P<laps>\d+)\s+"
        r"(?P<fastest_lap>\d+)\s+"
        r"(?P<best_time>\d+:\d{2}\.\d+\*?)"
        r"(?:\s+(?P<gap>\d+:\d{2}\.\d+))?$"
    )

    rows: list[dict[str, str]] = []
    for match in row_pattern.finditer(text):
        position = match.group("position")
        car = match.group("car")
        rest = clean(match.group("rest"))

        tail = tail_pattern.match(rest)
        if not tail:
            continue

        rows.append(
            {
                "Position": position,
                "Car": car,
                "Competitor / Vehicle": clean(tail.group("identity")),
                "Laps": tail.group("laps"),
                "Fastest Lap": tail.group("fastest_lap"),
                "Best Time": tail.group("best_time").rstrip("*"),
                "Gap": tail.group("gap") or "",
            }
        )

    return rows


def extract_tables(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    tables: list[dict[str, Any]] = []

    for table_index, table in enumerate(soup.find_all("table"), start=1):
        trs = table.find_all("tr")
        if not trs:
            continue

        first_cells = trs[0].find_all(["th", "td"])
        headers = unique_headers([clean(c.get_text(" ", strip=True)) for c in first_cells])
        rows: list[dict[str, str]] = []

        for tr in trs[1:]:
            cells = [clean(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
            if not cells or not any(cells):
                continue

            if len(cells) > len(headers):
                headers = unique_headers(headers + [f"column_{i + 1}" for i in range(len(headers), len(cells))])

            row = {headers[i] if i < len(headers) else f"column_{i + 1}": value for i, value in enumerate(cells)}
            rows.append(row)

        if rows:
            tables.append({"table_index": table_index, "headers": headers, "rows": rows})

    fixed_rows = extract_fixed_width_rows(html)
    normal_row_count = sum(len(t["rows"]) for t in tables)
    if len(fixed_rows) > normal_row_count:
        return [
            {
                "table_index": 1,
                "headers": list(fixed_rows[0].keys()) if fixed_rows else [],
                "rows": fixed_rows,
            }
        ]

    return tables


def normalize_match_text(text: str) -> str:
    """Normalize names/result text for case- and punctuation-insensitive matching."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return clean(text)


def participant_variants(participant: str) -> list[str]:
    """Return sensible name variants, including aliases in parentheses.

    Example: 'Jonathon (Jon) Harrison' matches both 'Jonathon Harrison'
    and 'Jon Harrison' as Natsoft may publish either form.
    """
    participant = clean(participant)
    if not participant:
        return []

    variants = {normalize_match_text(participant)}
    match = re.match(r"^(.*?)\s*\(([^)]+)\)\s*(.*)$", participant)
    if match:
        before, alias, after = (clean(match.group(i)) for i in range(1, 4))
        if before or after:
            variants.add(normalize_match_text(f"{before} {after}"))
        if alias or after:
            variants.add(normalize_match_text(f"{alias} {after}"))

    return [v for v in variants if v]


def row_matches(row: dict[str, str], vehicle_terms: list[str], participants: list[str]) -> bool:
    haystack = normalize_match_text(" ".join(row.values()))

    participant_hit = any(
        variant in haystack
        for participant in participants
        for variant in participant_variants(participant)
    )
    vehicle_hit = any(
        normalize_match_text(term) in haystack
        for term in vehicle_terms
        if term.strip()
    )
    return participant_hit or vehicle_hit


def comparable(payload: dict[str, Any]) -> dict[str, Any]:
    copy = dict(payload)
    copy.pop("generated_at", None)
    return copy


def scrape() -> dict[str, Any]:
    config = load_config()
    source_url = config["natsoft"]["url"]
    timeout = int(config["natsoft"].get("timeout_seconds", 30))

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; GaugeKingResults/1.0; +https://www.gaugeking.com.au/)"
    }

    response = requests.get(source_url, headers=headers, timeout=timeout, allow_redirects=True)
    response.raise_for_status()

    tables = extract_tables(response.text)
    vehicle_terms = config.get("filters", {}).get("vehicle_terms", [])
    participants = config.get("filters", {}).get("participants", [])

    matched: list[dict[str, Any]] = []
    for table in tables:
        for row in table["rows"]:
            if row_matches(row, vehicle_terms, participants):
                matched.append({"table_index": table["table_index"], "row": row})

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "event": config.get("event", {}),
        "source": {
            "url": source_url,
            "final_url": response.url,
            "status_code": response.status_code,
            "validation_mode": bool(config["natsoft"].get("validation_mode", False)),
        },
        "filters": {
            "vehicle_terms": vehicle_terms,
            "participants": participants,
        },
        "diagnostics": {
            "table_count": len(tables),
            "row_count": sum(len(t["rows"]) for t in tables),
            "matched_row_count": len(matched),
        },
        "results": matched,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    if OUTPUT_PATH.exists():
        try:
            previous = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = None

        if previous and comparable(previous) == comparable(payload):
            print("Natsoft data unchanged; keeping existing snapshot.")
            print(json.dumps(payload["diagnostics"], indent=2))
            return previous

    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Natsoft data changed; snapshot updated.")
    print(json.dumps(payload["diagnostics"], indent=2))
    return payload


if __name__ == "__main__":
    scrape()

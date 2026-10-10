from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
import hashlib
from natsoft_browser import discover_live_result
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
        tail = tail_pattern.match(clean(match.group("rest")))
        if not tail:
            continue
        rows.append({
            "Position": match.group("position"),
            "Car": match.group("car"),
            "Competitor / Vehicle": clean(tail.group("identity")),
            "Laps": tail.group("laps"),
            "Fastest Lap": tail.group("fastest_lap"),
            "Best Time": tail.group("best_time").rstrip("*"),
            "Gap": tail.group("gap") or "",
        })
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
            rows.append({headers[i] if i < len(headers) else f"column_{i + 1}": value for i, value in enumerate(cells)})
        if rows:
            tables.append({"table_index": table_index, "headers": headers, "rows": rows})

    fixed_rows = extract_fixed_width_rows(html)
    normal_row_count = sum(len(t["rows"]) for t in tables)
    if len(fixed_rows) > normal_row_count:
        return [{"table_index": 1, "headers": list(fixed_rows[0].keys()) if fixed_rows else [], "rows": fixed_rows}]
    return tables


def normalize_match_text(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return clean(text)


def participant_variants(participant: str) -> list[str]:
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
    vehicle_hit = any(normalize_match_text(term) in haystack for term in vehicle_terms if term.strip())
    return participant_hit or vehicle_hit


def is_direct_result_url(url: str) -> bool:
    return "/object_" in url.lower() or "/view?" in url.lower()


def discover_result_links(event_url: str, html: str) -> list[dict[str, str]]:
    """Find published Result links on a Natsoft event-level page.

    Natsoft pages commonly expose a Result link and a separate Times link per session.
    We intentionally prefer anchors whose visible text contains 'result' and ignore 'times'.
    If the visible text is generic, object-style links are accepted as a fallback.
    """
    soup = BeautifulSoup(html, "html.parser")
    found: list[dict[str, str]] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = urljoin(event_url, anchor.get("href", ""))
        text = clean(anchor.get_text(" ", strip=True))
        lower_text = text.lower()
        parsed = urlparse(href)
        if parsed.hostname not in {"racing.natsoft.com.au", "www.racing.natsoft.com.au"}:
            continue
        if "times" in lower_text:
            continue
        looks_like_object = "/object_" in parsed.path.lower() or "/view" in parsed.path.lower()
        looks_like_result = "result" in lower_text
        if not (looks_like_object or looks_like_result):
            continue
        if href in seen:
            continue
        seen.add(href)

        tr = anchor.find_parent("tr")
        row_text = clean(tr.get_text(" ", strip=True)) if tr else ""
        label = row_text or text or "Latest Result"
        label = re.sub(r"\bResult\b\s*\d*", "", label, flags=re.IGNORECASE)
        label = re.sub(r"\bTimes\b\s*\d*", "", label, flags=re.IGNORECASE)
        label = clean(label).strip(" -|") or text or "Latest Result"
        found.append({"url": href, "label": label})

    # Preserve page order; Natsoft normally lists sessions chronologically, so the last
    # published Result link is treated as the newest/current session.
    return found



def resolve_index_event(session, index_url: str, timeout: int) -> tuple[str, str]:
    """Resolve a Natsoft /results/#N index selection through published HTML links.

    The URL fragment is not sent to the server. We can only identify the target
    if the fetched index has a real anchor for that selection. Fail closed rather
    than silently scraping another event.
    """
    from urllib.parse import urlsplit
    from urllib.parse import urldefrag
    from urllib.parse import unquote
    parsed = urlsplit(index_url)
    fragment = unquote(parsed.fragment).strip()
    if not fragment.isdigit():
        raise RuntimeError("Natsoft index selection must use # followed by a number.")
    response = session.get(urldefrag(index_url).url, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    candidates = []
    for a in soup.find_all("a", href=True):
        target = urljoin(response.url, a["href"])
        parsed_target = urlsplit(target)
        if parsed_target.hostname not in {"racing.natsoft.com.au", "www.racing.natsoft.com.au"}:
            continue
        if "/results/" in parsed_target.path.rstrip("/") + "/" and not parsed_target.query:
            continue
        if target not in candidates:
            candidates.append(target)
        # A page may expose explicit event anchors matching #4.
        if a.get("id") == fragment or a.get("name") == fragment or a.get("data-id") == fragment:
            return target, clean(a.get_text(" ", strip=True)) or "Selected Event"
    # Do not assume that #4 means fourth HTML link: Natsoft's hash
    # navigation can be populated by JavaScript, not ordinary anchors.
    raise RuntimeError(
        f"Natsoft selection #{fragment} could not be resolved from its server HTML. "
        "The page uses client-side navigation; capture the event link from the "
        "browser Network tab or the event-level page rather than using an unrelated result."
    )


def comparable(payload: dict[str, Any]) -> dict[str, Any]:
    copy = dict(payload)
    copy.pop("generated_at", None)
    return copy


def scrape() -> dict[str, Any]:
    config = load_config()
    natsoft = config.get("natsoft", {})
    event_url = clean(natsoft.get("event_url", ""))
    fallback_url = clean(natsoft.get("url", ""))
    timeout = int(natsoft.get("timeout_seconds", 30))
    headers = {"User-Agent": "Mozilla/5.0 (compatible; GaugeKingResults/1.0; +https://www.gaugeking.com.au/)"}

    session = requests.Session()
    session.headers.update(headers)

    source_mode = "direct"
    source_page_url = event_url or fallback_url
    result_url = source_page_url
    session_label = "Current Result"
    discovered_links: list[dict[str, str]] = []

    if event_url and urlparse(event_url).fragment and urlparse(event_url).path.rstrip("/") == "/results":
        source_mode = "browser-index"
        result_url, session_label, browser_html, browser_headers, browser_status = discover_live_result(event_url, timeout)
        print(f"Discovered browser result: {session_label} => {result_url}")
    elif event_url and not is_direct_result_url(event_url):
        source_mode = "event"
        event_response = session.get(event_url, timeout=timeout, allow_redirects=True)
        event_response.raise_for_status()
        discovered_links = discover_result_links(event_response.url, event_response.text)
        if not discovered_links:
            raise RuntimeError("No published Natsoft Result links found")
        result_url, session_label = discovered_links[-1]["url"], discovered_links[-1]["label"]

    if source_mode == "browser-index":
        from types import SimpleNamespace
        response = SimpleNamespace(url=result_url, text=browser_html, content=browser_html.encode("utf-8"), headers=browser_headers, status_code=browser_status)
        if browser_status >= 400:
            raise RuntimeError(f"Natsoft result returned HTTP {browser_status}")
    else:
        response = session.get(result_url, timeout=timeout, allow_redirects=True)
        response.raise_for_status()

    content_hash = hashlib.sha256(response.content).hexdigest()
    print(f"RESULT_AUDIT url={response.url} sha256={content_hash} status={response.status_code} age={response.headers.get('Age', '')} cache={response.headers.get('X-Cache', '')}")
    tables = extract_tables(response.text)
    if not tables or not any(t["rows"] for t in tables):
        raise RuntimeError("No parseable result rows; refusing stale deployment")
    vehicle_terms = config.get("filters", {}).get("vehicle_terms", [])
    participants = config.get("filters", {}).get("participants", [])

    matched: list[dict[str, Any]] = []
    for table in tables:
        for row in table["rows"]:
            if row_matches(row, vehicle_terms, participants):
                matched.append({"table_index": table["table_index"], "row": row})

    previous = None
    if OUTPUT_PATH.exists():
        try:
            previous = json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = None

    sessions = []
    if previous:
        sessions = list(previous.get("sessions", []))
        # Migrate an older single-result snapshot into session history once.
        if not sessions and previous.get("results"):
            old_source = previous.get("source", {})
            sessions.append({
                "label": old_source.get("session_label", "Previous Result"),
                "url": old_source.get("result_url") or old_source.get("final_url") or old_source.get("url", ""),
                "generated_at": previous.get("generated_at"),
                "results": previous.get("results", []),
            })

    current_session = {
        "label": session_label,
        "url": response.url,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": matched,
    }
    existing_index = next((i for i, item in enumerate(sessions) if item.get("url") == response.url), None)
    if existing_index is None:
        sessions.append(current_session)
    else:
        sessions[existing_index] = current_session

    payload = {
        "generated_at": current_session["generated_at"],
        "event": config.get("event", {}),
        "source": {
            "mode": source_mode,
            "event_url": event_url,
            "url": source_page_url,
            "result_url": response.url,
            "final_url": response.url,
            "content_sha256": content_hash,
            "cache_control": response.headers.get("Cache-Control", ""),
            "session_label": session_label,
            "status_code": response.status_code,
            "validation_mode": bool(natsoft.get("validation_mode", False)),
            "discovered_result_count": len(discovered_links),
        },
        "filters": {"vehicle_terms": vehicle_terms, "participants": participants},
        "diagnostics": {
            "table_count": len(tables),
            "row_count": sum(len(t["rows"]) for t in tables),
            "matched_row_count": len(matched),
        },
        "results": matched,
        "sessions": sessions,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
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

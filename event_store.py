"""Strict event isolation and historical snapshot preservation."""
import json
import re
import shutil
import yaml
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data" / "results.json"
ARCHIVE = ROOT / "data" / "events"
SITE = ROOT / "docs" / "trackresults"

def event_key(event):
    value = "-".join(str(event.get(k, "")).strip().lower() for k in ("date", "venue", "name"))
    return re.sub(r"[^a-z0-9-]+", "-", value).strip("-")[:150] or "unknown-event"

def empty_payload(event):
    return {
        "event": dict(event), "generated_at": None,
        "source": {"status": "awaiting-results", "validation_mode": False},
        "filters": {"participants": [], "vehicle_terms": []},
        "diagnostics": {"table_count": 0, "row_count": 0, "matched_row_count": 0},
        "results": [], "sessions": [],
    }

def switch_event(config):
    """Archive old event before clearing live results. Never blend event sessions."""
    desired = config.get("event", {})
    desired_key = event_key(desired)
    if not DATA.exists():
        DATA.parent.mkdir(parents=True, exist_ok=True)
        DATA.write_text(json.dumps(empty_payload(desired), indent=2), encoding="utf-8")
        return False
    try:
        previous = json.loads(DATA.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise RuntimeError("Existing race results cannot be read; refusing destructive event switch") from exc
    existing_key = event_key(previous.get("event", {}))
    if existing_key == desired_key:
        return False
    archive_dir = ARCHIVE / existing_key
    archive_dir.mkdir(parents=True, exist_ok=True)
    snapshot = archive_dir / "results.json"
    if snapshot.exists():
        # Don't overwrite an existing archived event with potentially mixed legacy data.
        numbered = sorted(archive_dir.glob("results-*.json"))
        snapshot = archive_dir / f"results-{len(numbered)+1}.json"
    snapshot.write_text(json.dumps(previous, indent=2, ensure_ascii=False), encoding="utf-8")
    prior_path = Path('/tmp/gaugeking_previous_event.yaml')
    if prior_path.exists():
        prior_config = yaml.safe_load(prior_path.read_text(encoding='utf-8')) or {}
        if event_key(prior_config.get('event', {})) == existing_key:
            (archive_dir / 'registrations.json').write_text(
                json.dumps(prior_config.get('filters', {}), indent=2, ensure_ascii=False), encoding='utf-8'
            )
    old_page = SITE / "index.html"
    if old_page.exists():
        public_archive = SITE / "archive" / existing_key
        public_archive.mkdir(parents=True, exist_ok=True)
        destination = public_archive / "index.html"
        if not destination.exists():
            html = old_page.read_text(encoding="utf-8")
            html = html.replace('src="assets/', 'src="../../assets/')
            destination.write_text(html, encoding="utf-8")
    DATA.write_text(json.dumps(empty_payload(desired), indent=2), encoding="utf-8")
    print(f"Archived {existing_key}; active event reset to {desired_key}", flush=True)
    return True

def assert_event(data, event):
    if event_key(data.get("event", {})) != event_key(event):
        raise RuntimeError("Stored race result event does not match selected meeting")

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
CONFIG = ROOT / "config.yaml"
DATA = ROOT / "data" / "results.json"
OUT = ROOT / "docs" / "trackresults" / "index.html"


def esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def result_cards(results):
    if not results:
        return '<div class="empty">No tracked competitors found in this session yet.</div>'
    cards = []
    for item in results:
        row = item.get("row", {})
        fields = "".join(
            f'<div class="field"><span>{esc(k)}</span><strong>{esc(v)}</strong></div>'
            for k, v in row.items() if str(v).strip()
        )
        cards.append(f'<article class="result-card"><div class="table-tag">RESULT</div>{fields}</article>')
    return "".join(cards)


def session_sections(data):
    sessions = data.get("sessions") or []
    if not sessions:
        sessions = [{
            "label": data.get("source", {}).get("session_label", "Current Result"),
            "results": data.get("results", []),
            "url": data.get("source", {}).get("result_url", ""),
        }]

    blocks = []
    # Newest first while preserving older sessions below it.
    for index, session in enumerate(reversed(sessions)):
        label = session.get("label") or ("Current Result" if index == 0 else "Previous Result")
        current_badge = '<span class="current-badge">LATEST</span>' if index == 0 else ''
        blocks.append(
            f'<section class="session-block">'
            f'<div class="section-head"><h3>{esc(label)} {current_badge}</h3>'
            f'<div>{len(session.get("results", []))} tracked result(s)</div></div>'
            f'<div class="results">{result_cards(session.get("results", []))}</div>'
            f'</section>'
        )
    return "".join(blocks)


def main():
    config = load_yaml(CONFIG)
    data = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {
        "generated_at": None,
        "source": {"validation_mode": True, "url": config.get("natsoft", {}).get("url", "")},
        "diagnostics": {},
        "results": [],
        "sessions": [],
    }

    event = config.get("event", {})
    site = config.get("site", {})
    generated = data.get("generated_at")
    if generated:
        try:
            generated_label = datetime.fromisoformat(generated.replace("Z", "+00:00")).strftime("%d %b %Y %H:%M UTC")
        except ValueError:
            generated_label = generated
    else:
        generated_label = "Waiting for first scrape"

    validation = bool(data.get("source", {}).get("validation_mode", False))
    source_mode = data.get("source", {}).get("mode", "direct")
    banner = (
        '<div class="validation">VALIDATION MODE — showing data from the test source until the live 2026 event page is supplied.</div>'
        if validation
        else '<div class="live">LIVE EVENT SOURCE — Gauge King automatically discovers the newest published Natsoft result.</div>'
    )
    diag = data.get("diagnostics", {})
    refresh = int(site.get("refresh_seconds", 300))
    session_count = len(data.get("sessions") or []) or 1

    page = f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>{esc(site.get("title", "Gauge King Track Results"))}</title>
<link rel="icon" href="assets/gauge-king-logo.jpg" type="image/jpeg">
<style>
:root{{--bg:#090b0f;--panel:#12161d;--line:#282f39;--text:#f5f7fa;--muted:#9ca6b4;--gold:#d4af37;}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% 0,#1c222c 0,#090b0f 42%);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}.wrap{{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:30px 0 70px}}.brand{{display:flex;align-items:center;gap:18px;margin-bottom:24px;min-height:94px}}.brand-logo{{width:94px;height:94px;object-fit:contain;border-radius:18px}}.brand-copy{{border-left:1px solid var(--line);padding-left:18px}}.brand-copy strong{{display:block;font-size:19px;letter-spacing:.16em}}.brand-copy small{{display:block;color:var(--muted);margin-top:5px;letter-spacing:.12em;font-size:11px}}.hero{{border:1px solid var(--line);background:linear-gradient(135deg,rgba(255,255,255,.055),rgba(255,255,255,.015));border-radius:22px;padding:28px;margin-bottom:18px;box-shadow:0 20px 70px rgba(0,0,0,.28)}}.eyebrow{{color:var(--gold);font-size:12px;font-weight:800;letter-spacing:.16em}}h2{{font-size:clamp(34px,7vw,68px);line-height:.96;margin:12px 0;letter-spacing:-.045em}}.subtitle{{font-size:18px;color:var(--muted)}}.meta{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:24px}}.meta-card{{padding:16px;background:#0e1218;border:1px solid var(--line);border-radius:14px}}.meta-card span{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.12em;margin-bottom:6px}}.meta-card strong{{font-size:15px}}.validation,.live{{padding:13px 16px;border-radius:12px;margin:14px 0 24px;font-size:12px;font-weight:800;letter-spacing:.06em}}.validation{{background:#2a2110;border:1px solid #6f5619;color:#f1cf64}}.live{{background:#10251b;border:1px solid #236943;color:#6ee7a7}}.session-block{{margin-top:28px}}.section-head{{display:flex;justify-content:space-between;gap:20px;align-items:end;margin:0 2px 14px}}.section-head h3{{margin:0;font-size:22px}}.section-head div{{color:var(--muted);font-size:13px}}.current-badge{{display:inline-block;margin-left:8px;padding:4px 7px;border-radius:999px;background:#2a2110;color:#f1cf64;font-size:9px;letter-spacing:.12em;vertical-align:middle}}.results{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}.result-card{{position:relative;background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:18px;overflow:hidden}}.result-card:before{{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--gold)}}.table-tag{{font-size:10px;color:var(--gold);letter-spacing:.14em;font-weight:800;margin-bottom:12px}}.field{{display:flex;justify-content:space-between;gap:20px;padding:8px 0;border-bottom:1px solid rgba(255,255,255,.06)}}.field:last-child{{border-bottom:0}}.field span{{color:var(--muted);font-size:12px}}.field strong{{text-align:right;font-size:13px}}.empty{{grid-column:1/-1;padding:34px;text-align:center;background:var(--panel);border:1px dashed var(--line);border-radius:18px;color:var(--muted)}}footer{{margin-top:28px;color:#6f7987;font-size:11px;text-align:center}}@media(max-width:760px){{.brand{{min-height:76px;gap:13px}}.brand-logo{{width:76px;height:76px}}.meta{{grid-template-columns:repeat(2,1fr)}}.results{{grid-template-columns:1fr}}.section-head{{align-items:start;flex-direction:column}}}}
</style></head><body><main class="wrap">
<div class="brand"><img class="brand-logo" src="assets/gauge-king-logo.jpg" alt="Gauge King"><div class="brand-copy"><strong>TRACK RESULTS</strong><small>LIVE MOTORSPORT TIMING</small></div></div>
<section class="hero"><div class="eyebrow">LIVE MOTORSPORT DATA</div><h2>{esc(event.get("name", "Race Results"))}</h2><div class="subtitle">{esc(site.get("subtitle", "Live race results"))}</div><div class="meta">
<div class="meta-card"><span>Event date</span><strong>{esc(event.get("date", "TBA"))}</strong></div><div class="meta-card"><span>Venue</span><strong>{esc(event.get("venue", "TBA"))}</strong></div><div class="meta-card"><span>Sessions captured</span><strong>{session_count}</strong></div><div class="meta-card"><span>Updated</span><strong>{esc(generated_label)}</strong></div>
</div></section>{banner}
{session_sections(data)}
<footer>Gauge King · Data sourced from Natsoft Racing Results · Natsoft remains authoritative · Source mode: {esc(source_mode)}</footer>
</main></body></html>'''

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"Built {OUT}")


if __name__ == "__main__":
    main()

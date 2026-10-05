from __future__ import annotations

import html
import json
from datetime import datetime, timezone
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


def result_sort_key(item):
    raw = str(item.get("row", {}).get("Position", "9999")).strip()
    try:
        return int(raw)
    except ValueError:
        return 9999


def first_value(row, *keys):
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def leaderboard(results, session_index):
    if not results:
        return '<div class="empty">No tracked competitors found in this session yet.</div>'

    rows_html = []
    for row_index, item in enumerate(sorted(results, key=result_sort_key)):
        row = item.get("row", {})
        position = first_value(row, "Position", "Pos", "Place") or "–"
        car = first_value(row, "Car", "Car No", "Number", "No") or "–"
        competitor = first_value(row, "Competitor / Vehicle", "Competitor", "Driver", "Name") or "Unknown"
        best_time = first_value(row, "Best Time", "Fastest Time", "Lap Time", "Time") or "–"
        gap = first_value(row, "Gap", "Diff", "Difference") or "–"
        detail_id = f"details-{session_index}-{row_index}"

        compact_keys = {
            "Position", "Pos", "Place", "Car", "Car No", "Number", "No",
            "Competitor / Vehicle", "Competitor", "Driver", "Name",
            "Best Time", "Fastest Time", "Lap Time", "Time", "Gap", "Diff", "Difference",
        }
        detail_fields = "".join(
            f'<div class="detail-field"><span>{esc(key)}</span><strong>{esc(value)}</strong></div>'
            for key, value in row.items()
            if str(value).strip() and key not in compact_keys
        ) or '<div class="detail-empty">No additional timing fields are available for this result.</div>'

        rows_html.append(
            f'<tr class="leader-row">'
            f'<td class="pos"><span class="pos-badge">{esc(position)}</span></td>'
            f'<td class="car">{esc(car)}</td>'
            f'<td class="driver">{esc(competitor)}</td>'
            f'<td class="time">{esc(best_time)}</td>'
            f'<td class="gap">{esc(gap)}</td>'
            f'<td class="more"><button type="button" class="details-btn" aria-expanded="false" aria-controls="{detail_id}" onclick="toggleDetails(this,\'{detail_id}\')">MORE DETAILS</button></td>'
            f'</tr>'
            f'<tr class="detail-row" id="{detail_id}" hidden><td colspan="6"><div class="detail-panel">{detail_fields}</div></td></tr>'
        )

    return (
        '<div class="leaderboard-wrap"><table class="leaderboard">'
        '<thead><tr><th>POS</th><th>CAR</th><th>DRIVER / VEHICLE</th><th>BEST TIME</th><th>GAP</th><th></th></tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody></table></div>'
    )


def session_sections(data):
    sessions = data.get("sessions") or [{
        "label": data.get("source", {}).get("session_label", "Current Result"),
        "results": data.get("results", []),
        "url": data.get("source", {}).get("result_url", ""),
    }]

    blocks = []
    for index, session in enumerate(reversed(sessions)):
        label = session.get("label") or ("Current Result" if index == 0 else "Previous Result")
        current_badge = '<span class="current-badge">LATEST</span>' if index == 0 else ''
        blocks.append(
            f'<section class="session-block">'
            f'<div class="section-head"><h3>{esc(label)} {current_badge}</h3>'
            f'<div>{len(session.get("results", []))} tracked result(s)</div></div>'
            f'{leaderboard(session.get("results", []), index)}'
            f'</section>'
        )
    return "".join(blocks)


def main():
    config = load_yaml(CONFIG)
    data = json.loads(DATA.read_text(encoding="utf-8")) if DATA.exists() else {
        "source": {"validation_mode": True, "url": config.get("natsoft", {}).get("url", "")},
        "results": [], "sessions": [],
    }

    event = config.get("event", {})
    site = config.get("site", {})
    checked_label = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")

    validation = bool(data.get("source", {}).get("validation_mode", False))
    source_mode = data.get("source", {}).get("mode", "direct")
    banner = (
        '<div class="validation">VALIDATION MODE — showing data from the test source until the live 2026 event page is supplied.</div>'
        if validation
        else '<div class="live">LIVE EVENT SOURCE — Gauge King automatically discovers the newest published Natsoft result.</div>'
    )
    refresh = int(site.get("refresh_seconds", 300))
    session_count = len(data.get("sessions") or []) or 1

    page = f'''<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{refresh}">
<title>{esc(site.get("title", "Gauge King Track Results"))}</title>
<link rel="icon" href="assets/gauge-king-logo.jpg?v=4" type="image/jpeg">
<style>
:root{{--bg:#090b0f;--panel:#12161d;--line:#282f39;--text:#f5f7fa;--muted:#9ca6b4;--gold:#d4af37;}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% 0,#1c222c 0,#090b0f 42%);color:var(--text);font-family:Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}.wrap{{width:min(1180px,calc(100% - 32px));margin:0 auto;padding:30px 0 70px}}.brand{{display:flex;align-items:center;gap:18px;margin-bottom:24px;min-height:94px}}.brand-logo{{width:94px;height:94px;object-fit:contain;border-radius:18px;display:block}}.brand-copy{{border-left:1px solid var(--line);padding-left:18px}}.brand-copy strong{{display:block;font-size:19px;letter-spacing:.16em}}.brand-copy small{{display:block;color:var(--muted);margin-top:5px;letter-spacing:.12em;font-size:11px}}.hero{{border:1px solid var(--line);background:linear-gradient(135deg,rgba(255,255,255,.055),rgba(255,255,255,.015));border-radius:22px;padding:28px;margin-bottom:18px;box-shadow:0 20px 70px rgba(0,0,0,.28)}}.eyebrow{{color:var(--gold);font-size:12px;font-weight:800;letter-spacing:.16em}}h2{{font-size:clamp(34px,7vw,68px);line-height:.96;margin:12px 0;letter-spacing:-.045em}}.subtitle{{font-size:18px;color:var(--muted)}}.meta{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:24px}}.meta-card{{padding:16px;background:#0e1218;border:1px solid var(--line);border-radius:14px}}.meta-card span{{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.12em;margin-bottom:6px}}.meta-card strong{{font-size:15px}}.validation,.live{{padding:13px 16px;border-radius:12px;margin:14px 0 24px;font-size:12px;font-weight:800;letter-spacing:.06em}}.validation{{background:#2a2110;border:1px solid #6f5619;color:#f1cf64}}.live{{background:#10251b;border:1px solid #236943;color:#6ee7a7}}.session-block{{margin-top:30px}}.section-head{{display:flex;justify-content:space-between;gap:20px;align-items:end;margin:0 2px 14px}}.section-head h3{{margin:0;font-size:22px}}.section-head div{{color:var(--muted);font-size:13px}}.current-badge{{display:inline-block;margin-left:8px;padding:4px 7px;border-radius:999px;background:#2a2110;color:#f1cf64;font-size:9px;letter-spacing:.12em;vertical-align:middle}}.leaderboard-wrap{{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:18px;box-shadow:0 14px 40px rgba(0,0,0,.18)}}.leaderboard{{width:100%;border-collapse:collapse;min-width:760px}}.leaderboard th{{padding:13px 14px;text-align:left;color:#7f8997;font-size:10px;letter-spacing:.12em;border-bottom:1px solid var(--line);background:#0e1218}}.leaderboard td{{padding:14px;border-bottom:1px solid rgba(255,255,255,.06);font-size:13px;vertical-align:middle}}.leader-row:hover{{background:rgba(255,255,255,.025)}}.pos{{width:74px}}.pos-badge{{display:inline-flex;align-items:center;justify-content:center;min-width:38px;height:38px;padding:0 9px;border-radius:11px;background:#191d24;border:1px solid #343b46;font-weight:900;font-size:15px}}.car{{width:80px;color:var(--gold);font-weight:800}}.driver{{font-weight:750;font-size:14px!important}}.time,.gap{{font-variant-numeric:tabular-nums;white-space:nowrap}}.more{{width:132px;text-align:right}}.details-btn{{border:1px solid #4a515c;background:#171c24;color:#f5f7fa;border-radius:9px;padding:8px 10px;font-size:10px;font-weight:850;letter-spacing:.08em;cursor:pointer;white-space:nowrap}}.details-btn:hover{{border-color:var(--gold);color:var(--gold)}}.detail-row td{{padding:0 14px 14px;background:#0d1117}}.detail-panel{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;padding:14px;border:1px solid #252c35;border-radius:12px;background:#10151c}}.detail-field{{padding:10px;background:#0c1016;border-radius:9px}}.detail-field span{{display:block;color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.08em;margin-bottom:5px}}.detail-field strong{{font-size:13px}}.detail-empty{{grid-column:1/-1;color:var(--muted);font-size:12px;padding:4px}}.empty{{padding:34px;text-align:center;background:var(--panel);border:1px dashed var(--line);border-radius:18px;color:var(--muted)}}footer{{margin-top:28px;color:#6f7987;font-size:11px;text-align:center}}@media(max-width:760px){{.brand{{min-height:76px;gap:13px}}.brand-logo{{width:76px;height:76px}}.meta{{grid-template-columns:repeat(2,1fr)}}.section-head{{align-items:start;flex-direction:column}}.leaderboard{{min-width:0}}.leaderboard th:nth-child(2),.leaderboard td:nth-child(2),.leaderboard th:nth-child(5),.leaderboard td:nth-child(5){{display:none}}.leaderboard th,.leaderboard td{{padding:11px 9px}}.pos{{width:55px}}.more{{width:104px}}.details-btn{{padding:7px 8px;font-size:9px}}.detail-row td{{display:table-cell!important;padding:0 9px 12px}}.detail-panel{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main class="wrap">
<div class="brand"><img class="brand-logo" src="assets/gauge-king-logo.jpg?v=4" alt="Gauge King"><div class="brand-copy"><strong>TRACK RESULTS</strong><small>LIVE MOTORSPORT TIMING</small></div></div>
<section class="hero"><div class="eyebrow">LIVE MOTORSPORT DATA</div><h2>{esc(event.get("name", "Race Results"))}</h2><div class="subtitle">{esc(site.get("subtitle", "Live race results"))}</div><div class="meta">
<div class="meta-card"><span>Event date</span><strong>{esc(event.get("date", "TBA"))}</strong></div><div class="meta-card"><span>Venue</span><strong>{esc(event.get("venue", "TBA"))}</strong></div><div class="meta-card"><span>Sessions captured</span><strong>{session_count}</strong></div><div class="meta-card"><span>Last checked</span><strong>{esc(checked_label)}</strong></div>
</div></section>{banner}
{session_sections(data)}
<footer>Gauge King · Data sourced from Natsoft Racing Results · Natsoft remains authoritative · Source mode: {esc(source_mode)}</footer>
</main>
<script>
function toggleDetails(button,id){{
  const row=document.getElementById(id);
  const open=row.hasAttribute('hidden');
  if(open){{row.removeAttribute('hidden');button.textContent='HIDE DETAILS';button.setAttribute('aria-expanded','true');}}
  else{{row.setAttribute('hidden','');button.textContent='MORE DETAILS';button.setAttribute('aria-expanded','false');}}
}}
</script>
</body></html>'''

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"Built {OUT}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import hmac
import hashlib
import time
import json
import os
from urllib.parse import urlparse
from typing import Any
from datetime import datetime

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

GITHUB_REPO = os.getenv("GITHUB_REPO", "project3300/gaugeking-website")
GITHUB_WORKFLOW = os.getenv("GITHUB_WORKFLOW", "update-results.yml")
GITHUB_REF = os.getenv("GITHUB_REF", "main")
GITHUB_TOKEN = os.getenv("GITHUB_RACE_RESULTS_TOKEN", "")
RACE_CONTROL_PIN = os.getenv("RACE_CONTROL_PIN", "")

ALLOWED_ORIGINS = [
    "https://www.gaugeking.com.au",
    "https://gaugeking.com.au",
    "https://project3300.github.io",
]
ALLOWED_NATSOFT_HOSTS = {"racing.natsoft.com.au", "www.racing.natsoft.com.au"}
NATSOFT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GaugeKingRaceControl/1.0; +https://www.gaugeking.com.au/)"
}

app = FastAPI(title="Gauge King Race Control", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


class Registration(BaseModel):
    name: str
    class_name: str = Field(default="", alias="class")
    group: str = ""
    id: str = ""
    username: str = ""

    model_config = {"populate_by_name": True}


class UpdateRequest(BaseModel):
    pin: str
    results_url: str = ""
    participants: list[str] | None = Field(default=None, max_length=250)
    registrations: list[Registration] | None = Field(default=None, max_length=250)
    event_selection: dict[str, Any] | None = None


def validate_natsoft_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in ALLOWED_NATSOFT_HOSTS:
        raise HTTPException(status_code=400, detail="Please provide a valid racing.natsoft.com.au event or results URL.")
    return value


def verify_natsoft_url(value: str) -> None:
    if not value:
        return
    try:
        response = requests.get(value, headers=NATSOFT_HEADERS, timeout=15, allow_redirects=True, stream=True)
    except requests.RequestException:
        return

    try:
        if response.status_code in {404, 410}:
            raise HTTPException(
                status_code=400,
                detail="This Natsoft link is no longer valid. Open the event again in Natsoft and paste the current event-level URL.",
            )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=400,
                detail=f"Natsoft returned HTTP {response.status_code} for that link. Open the event again in Natsoft and paste the current event-level URL.",
            )
        final_host = urlparse(response.url).hostname
        if final_host not in ALLOWED_NATSOFT_HOSTS:
            raise HTTPException(status_code=400, detail="That Natsoft link redirected somewhere unexpected.")
    finally:
        response.close()


def clean_text(value: str, max_length: int = 120) -> str:
    value = " ".join(str(value or "").split()).strip()
    if len(value) > max_length:
        raise HTTPException(status_code=400, detail="An uploaded registration value is too long.")
    return value


def normalise_participants(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        name = clean_text(value)
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            deduped.append(name)
    if not deduped:
        raise HTTPException(status_code=400, detail="The uploaded driver list did not contain any names.")
    return deduped


def normalise_registrations(values: list[Registration] | None) -> list[dict[str, str]] | None:
    if values is None:
        return None
    output: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in values:
        name = clean_text(item.name)
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append({
            "name": name,
            "class": clean_text(item.class_name, 80),
            "group": clean_text(item.group, 120),
            "id": clean_text(item.id, 40),
            "username": clean_text(item.username, 120),
        })
    if not output:
        raise HTTPException(status_code=400, detail="The uploaded registration list did not contain any driver names.")
    return output


def selection_signature(event, issued):
    identity = {k: event.get(k, '') for k in ('name', 'date', 'track', 'id')}
    content = json.dumps({'event': identity, 'issued': issued}, sort_keys=True, separators=(',', ':'))
    return hmac.new(RACE_CONTROL_PIN.encode(), content.encode(), hashlib.sha256).hexdigest()

class DiscoverRequest(BaseModel):
    pin: str
    date: str = '2026-10-18'
    track: str = 'Winton Motor Raceway'
    name_hint: str = ''

@app.post('/api/race-results/discover')
def discover_events(payload: DiscoverRequest):
    if not RACE_CONTROL_PIN or not hmac.compare_digest(payload.pin.strip(), RACE_CONTROL_PIN):
        raise HTTPException(status_code=401, detail='Incorrect Race Control PIN.')
    try:
        datetime.strptime(payload.date, '%Y-%m-%d')
    except ValueError:
        raise HTTPException(status_code=400, detail='Date must be YYYY-MM-DD.')
    track = clean_text(payload.track, 100)
    if not track:
        raise HTTPException(status_code=400, detail='Select a race track.')
    try:
        from natsoft_browser import discover_meetings
        events = discover_meetings(payload.date, track)
    except Exception as exc:
        raise HTTPException(status_code=502, detail='Natsoft discovery unavailable: ' + str(exc)[:180])
    hint = clean_text(payload.name_hint, 100).casefold()
    if hint:
        events.sort(key=lambda e: hint not in e['name'].casefold())
    issued = int(time.time())
    for event in events:
        event['selection_issued'] = issued
        event['selection_signature'] = selection_signature(event, issued)
    return {'events': events, 'count': len(events)}
@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/race-results/update")
def update_race_results(payload: UpdateRequest) -> dict[str, object]:
    if not GITHUB_TOKEN or not RACE_CONTROL_PIN:
        raise HTTPException(status_code=503, detail="Race Control is not configured yet.")
    if not hmac.compare_digest(payload.pin.strip(), RACE_CONTROL_PIN):
        raise HTTPException(status_code=401, detail="Incorrect Race Control PIN.")

    source_url = validate_natsoft_url(payload.results_url)
    chosen_event = None
    if payload.event_selection:
        chosen_event = {k: clean_text(str(payload.event_selection.get(k, '')), 120) for k in ('name', 'date', 'track', 'id')}
        if not all(chosen_event.get(k) for k in ('name', 'date', 'track')):
            raise HTTPException(status_code=400, detail='Select a discovered Natsoft meeting.')
        if source_url:
            raise HTTPException(status_code=400, detail='Choose event discovery or a legacy URL, not both.')
        # Discovery already verified the meeting. Validate a signed, short-lived selection.
        try:
            issued = int(payload.event_selection.get('selection_issued'))
        except (TypeError, ValueError):
            raise HTTPException(status_code=409, detail='Event selection expired. Find events again.')
        if not 0 <= time.time() - issued <= 7200:
            raise HTTPException(status_code=409, detail='Event selection expired. Find events again.')
        signature = str(payload.event_selection.get('selection_signature', ''))
        if not hmac.compare_digest(selection_signature(chosen_event, issued), signature):
            raise HTTPException(status_code=409, detail='Event selection verification failed. Find events again.')
    registrations = normalise_registrations(payload.registrations)
    participants = normalise_participants(payload.participants)

    if registrations is not None:
        participants = [item["name"] for item in registrations]

    if not source_url and not chosen_event and participants is None and registrations is None:
        raise HTTPException(status_code=400, detail="Provide a Natsoft event URL, a registration/driver list, or both.")

    verify_natsoft_url(source_url)

    inputs = {
        "results_url": source_url,
        "event_selection_json": json.dumps(chosen_event) if chosen_event else "",
        "participants_json": json.dumps(participants, ensure_ascii=False) if participants is not None else "",
        "registrations_json": json.dumps(registrations, ensure_ascii=False) if registrations is not None else "",
    }
    endpoint = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{GITHUB_WORKFLOW}/dispatches"
    response = requests.post(
        endpoint,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "GaugeKingRaceControl/1.0",
        },
        json={"ref": GITHUB_REF, "inputs": inputs},
        timeout=20,
    )
    if response.status_code != 204:
        raise HTTPException(status_code=502, detail="GitHub could not start the results update.")

    return {
        "status": "started",
        "message": "Race results update started successfully.",
        "tracked_driver_count": len(participants) if participants is not None else None,
        "class_count": len({r["class"] for r in registrations if r["class"]}) if registrations is not None else None,
        "team_count": len({r["group"] for r in registrations if r["group"]}) if registrations is not None else None,
    }

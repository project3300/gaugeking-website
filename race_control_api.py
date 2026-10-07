from __future__ import annotations

import hmac
import json
import os
from urllib.parse import urlparse

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
    registrations = normalise_registrations(payload.registrations)
    participants = normalise_participants(payload.participants)

    if registrations is not None:
        participants = [item["name"] for item in registrations]

    if not source_url and participants is None and registrations is None:
        raise HTTPException(status_code=400, detail="Provide a Natsoft event URL, a registration/driver list, or both.")

    verify_natsoft_url(source_url)

    inputs = {
        "results_url": source_url,
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

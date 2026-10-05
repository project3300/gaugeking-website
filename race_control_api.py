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


class UpdateRequest(BaseModel):
    pin: str
    results_url: str = ""
    participants: list[str] | None = Field(default=None, max_length=250)


def validate_natsoft_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in ALLOWED_NATSOFT_HOSTS:
        raise HTTPException(status_code=400, detail="Please provide a valid racing.natsoft.com.au results URL.")
    return value


def verify_natsoft_url(value: str) -> None:
    """Check a supplied Natsoft result link before saving it as the live source."""
    if not value:
        return

    try:
        response = requests.get(
            value,
            headers=NATSOFT_HEADERS,
            timeout=15,
            allow_redirects=True,
            stream=True,
        )
    except requests.RequestException:
        raise HTTPException(
            status_code=502,
            detail="Race Control could not verify that Natsoft link. Check your connection and try again.",
        )

    try:
        if response.status_code in {404, 410}:
            raise HTTPException(
                status_code=400,
                detail="This Natsoft result link is no longer valid. Open the result again in Natsoft and paste the new URL.",
            )
        if response.status_code >= 400:
            raise HTTPException(
                status_code=400,
                detail=f"Natsoft returned HTTP {response.status_code} for that result link. Open the result again in Natsoft and paste the current URL.",
            )

        final_host = urlparse(response.url).hostname
        if final_host not in ALLOWED_NATSOFT_HOSTS:
            raise HTTPException(
                status_code=400,
                detail="That Natsoft link redirected somewhere unexpected. Open the result again in Natsoft and paste the current URL.",
            )
    finally:
        response.close()


def normalise_participants(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        name = " ".join(value.split()).strip()
        if len(name) > 120:
            raise HTTPException(status_code=400, detail="A driver name is too long.")
        key = name.casefold()
        if name and key not in seen:
            seen.add(key)
            deduped.append(name)

    if not deduped:
        raise HTTPException(status_code=400, detail="The uploaded driver list did not contain any names.")
    return deduped


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/race-results/update")
def update_race_results(payload: UpdateRequest) -> dict[str, object]:
    if not GITHUB_TOKEN or not RACE_CONTROL_PIN:
        raise HTTPException(status_code=503, detail="Race Control is not configured yet.")

    if not hmac.compare_digest(payload.pin.strip(), RACE_CONTROL_PIN):
        raise HTTPException(status_code=401, detail="Incorrect Race Control PIN.")

    results_url = validate_natsoft_url(payload.results_url)
    participants = normalise_participants(payload.participants)

    if not results_url and participants is None:
        raise HTTPException(status_code=400, detail="Provide a Natsoft URL, a driver list, or both.")

    # Do not save/start polling a newly supplied Natsoft URL until it is confirmed reachable.
    verify_natsoft_url(results_url)

    inputs = {
        "results_url": results_url,
        "participants_json": json.dumps(participants, ensure_ascii=False) if participants is not None else "",
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
    }

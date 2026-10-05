from __future__ import annotations

import hmac
import os
from urllib.parse import urlparse

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
    results_url: str


def validate_natsoft_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in ALLOWED_NATSOFT_HOSTS:
        raise HTTPException(status_code=400, detail="Please provide a valid racing.natsoft.com.au results URL.")
    return value


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/race-results/update")
def update_race_results(payload: UpdateRequest, request: Request) -> dict[str, str]:
    if not GITHUB_TOKEN or not RACE_CONTROL_PIN:
        raise HTTPException(status_code=503, detail="Race Control is not configured yet.")

    if not hmac.compare_digest(payload.pin.strip(), RACE_CONTROL_PIN):
        raise HTTPException(status_code=401, detail="Incorrect Race Control PIN.")

    results_url = validate_natsoft_url(payload.results_url)
    endpoint = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/{GITHUB_WORKFLOW}/dispatches"
    response = requests.post(
        endpoint,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "GaugeKingRaceControl/1.0",
        },
        json={
            "ref": GITHUB_REF,
            "inputs": {"results_url": results_url},
        },
        timeout=20,
    )

    if response.status_code != 204:
        raise HTTPException(status_code=502, detail="GitHub could not start the results update.")

    return {
        "status": "started",
        "message": "Race results update started successfully.",
    }

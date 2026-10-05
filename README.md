# Gauge King Race Results

Static Gauge King race-results site backed by Natsoft data.

## Target

- Event: **2026 OZ RS Nationals**
- Event date: **10 October 2026**
- Public page: `/trackresults/`
- Race Control: `/trackresults/admin/`
- Data source: Natsoft Racing Results
- Refresh: GitHub Actions every 5 minutes during the configured event window
- Filter: Renault / Renault Sport / Clio / Megane competitors

## Race-day flow

A non-technical user can open the Race Control page, enter the shared PIN, paste the live `racing.natsoft.com.au` results URL and press **UPDATE LIVE RESULTS**. The browser calls the small Render-hosted Race Control API, which securely triggers the GitHub Actions workflow with the supplied URL. The GitHub credential is stored only in Render.

The workflow saves the supplied Natsoft URL into `config.yaml`, switches validation mode off, scrapes the results, rebuilds the static page and deploys it. Scheduled runs then keep refreshing that saved URL during the event window.

## Render Race Control service

This repository contains a Render Blueprint in `render.yaml` and the API in `race_control_api.py`.

Deploy the Blueprint/service using this repository and configure these two secret environment variables in Render:

- `GITHUB_RACE_RESULTS_TOKEN` — a fine-grained GitHub token that can trigger Actions for this repository.
- `RACE_CONTROL_PIN` — the PIN given to the trusted person operating Race Control on the day.

The Blueprint creates the `gaugeking-race-control` Python web service and exposes `/health` plus the protected `/api/race-results/update` endpoint.

## Current source

`config.yaml` starts in **validation mode** using the known 2024 Natsoft result URL:

`http://racing.natsoft.com.au/684283107/object_466841.81y/View?1`

When Race Control receives the 2026 event URL, the workflow replaces this URL automatically and sets `natsoft.validation_mode: false`.

## How it works

1. `scrape_natsoft.py` downloads the configured Natsoft page and extracts result table rows.
2. Renault/RS-related rows are selected using the configured vehicle match terms.
3. The structured snapshot is written to `data/results.json`.
4. `build_site.py` builds the static page into `docs/trackresults/`.
5. `.github/workflows/update-results.yml` scrapes, builds and deploys GitHub Pages.

## Local run

```bash
python -m pip install -r requirements.txt
python scrape_natsoft.py
python build_site.py
python -m http.server 8000 --directory docs
```

Open `http://localhost:8000/trackresults/`.

# Gauge King Race Results

Static Gauge King race-results site backed by Natsoft data.

## Target

- Event: **2026 OZ RS Nationals**
- Event date: **10 October 2026**
- Public page: `/trackresults/`
- Data source: Natsoft Racing Results
- Refresh: GitHub Actions every 5 minutes
- Filter: Renault / Renault Sport / Clio / Megane competitors

## Current source

`config.yaml` starts in **validation mode** using the known 2024 Natsoft result URL:

`http://racing.natsoft.com.au/684283107/object_466841.81y/View?1`

When Natsoft publishes the 2026 OZ RS Nationals result URL, change only `natsoft.url` in `config.yaml` and set `natsoft.validation_mode: false`.

## How it works

1. `scrape_natsoft.py` downloads the configured Natsoft page and extracts result table rows.
2. Renault/RS-related rows are selected using the configured vehicle match terms.
3. The structured snapshot is written to `data/results.json`.
4. `build_site.py` builds the static page into `docs/trackresults/`.
5. `.github/workflows/update-results.yml` repeats the process every 5 minutes and deploys GitHub Pages.

## GitHub Pages

In **Settings → Pages**, set **Source** to **GitHub Actions**. Then run the **Update race results** workflow once from the Actions tab.

The repository can first be tested on its GitHub Pages URL. Do not point `www.gaugeking.com.au` at this repository until the existing Gauge King website/domain routing has been considered; the desired final route is `www.gaugeking.com.au/trackresults`.

## Local run

```bash
python -m pip install -r requirements.txt
python scrape_natsoft.py
python build_site.py
python -m http.server 8000 --directory docs
```

Open `http://localhost:8000/trackresults/`.

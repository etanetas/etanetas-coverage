# Etanetas Map Viewer

Standalone dev tool for visually verifying RC address data on a real map.

## Quick start

```bash
cd viewer
uv sync
cp .env.example .env
# Edit .env — set correct DB_PASSWORD in DATABASE_URL
uv run uvicorn viewer.main:app --reload --port 8001
```

Open http://localhost:8001/

## Features

- Address points on real OSM map (blue dots, zoom ≥ 13)
- Locality boundaries (orange outlines)
- Street axes (grey lines, zoom ≥ 14)
- Density heatmap (zoom out for full LT view)
- Toggle between OSM and Esri satellite imagery
- Click any point for popup with house_no, rc_code, postal_code

## Removal

```bash
rm -rf viewer/
```

No traces in the main project.

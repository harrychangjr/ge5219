# SG Rainfall Realtime → CSV (for Mapbox / ArcGIS / Anything)

Fetch the latest rainfall readings from data.gov.sg (v1 API), merge station metadata
(name + lat/lon), and export a clean CSV (optionally GeoJSON). Designed to run
locally or on GitHub Actions every 15 minutes.

- API: https://api.data.gov.sg/v1/environment/rainfall
- Output (default, overwrite latest): outputs/rainfall_latest.csv
- Optional: also export outputs/rainfall_latest.geojson
- Optional: timestamped archive copies, e.g. rainfall_latest_20251102_1545.csv

---

## Repository layout
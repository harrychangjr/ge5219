# ============================================================
# update_rainfall_layer.py  (UTC-safe version)
# Purpose:
#   - Fetch live rainfall from data.gov.sg
#   - Keep timestamp in UTC (avoid double time conversion by ArcGIS Online)
#   - Overwrite an existing hosted feature layer in ArcGIS Online
#   - Designed to run in GitHub Actions (uses env vars)
# ============================================================

import os
import requests
from datetime import datetime
from arcgis.gis import GIS
from arcgis.features import FeatureLayer

# ------------------------------------------------------------
# 1) Read ArcGIS Online credentials from environment
#    (GitHub Actions → Settings → Secrets → ARCGIS_USERNAME / ARCGIS_PASSWORD)
# ------------------------------------------------------------
arcgis_username = os.getenv("ARCGIS_USERNAME")
arcgis_password = os.getenv("ARCGIS_PASSWORD")

if not arcgis_username or not arcgis_password:
    raise RuntimeError(
        "ArcGIS credentials not found. "
        "Please set ARCGIS_USERNAME and ARCGIS_PASSWORD as GitHub Secrets."
    )

# Connect to ArcGIS Online
gis = GIS("https://www.arcgis.com", arcgis_username, arcgis_password)

# ------------------------------------------------------------
# 2) Target hosted feature layer (your rainfall layer)
#    NOTE: must point to the layer (…/FeatureServer/0), not just the service
# ------------------------------------------------------------
layer_url = (
    "https://services5.arcgis.com/KiRa9d9aHfdXiCqt/arcgis/rest/services/"
    "Rainfall_live/FeatureServer/0"
)
layer = FeatureLayer(layer_url)

# ------------------------------------------------------------
# 3) Call data.gov.sg rainfall API
# ------------------------------------------------------------
api_url = "https://api.data.gov.sg/v1/environment/rainfall"
response = requests.get(api_url, timeout=20)
response.raise_for_status()
rain_data = response.json()

# stations metadata → for getting lat/lon, name, etc.
stations_by_id = {s["id"]: s for s in rain_data["metadata"]["stations"]}

# latest readings block
latest_block = rain_data["items"][0]

# 💡 IMPORTANT:
# Keep API timestamp as-is (UTC) to avoid ArcGIS double-converting it.
reading_time_iso = latest_block["timestamp"]  # e.g. "2025-10-30T09:20:00+00:00"

# ------------------------------------------------------------
# 4) Build list of features to push to ArcGIS
# ------------------------------------------------------------
features = []

for reading in latest_block["readings"]:
    station = stations_by_id.get(reading["station_id"])
    if not station:
        # station not found in metadata — skip it
        continue

    lon = float(station["location"]["longitude"])
    lat = float(station["location"]["latitude"])

    feature = {
        "geometry": {
            "x": lon,
            "y": lat,
            "spatialReference": {"wkid": 4326},
        },
        "attributes": {
            "station_id": reading["station_id"],
            "station_name": station["name"],
            "rain_mm": reading.get("value"),
            # store UTC time
            "reading_time": reading_time_iso,
        },
    }
    features.append(feature)

# ------------------------------------------------------------
# 5) Overwrite the hosted layer: delete all → insert new
# ------------------------------------------------------------
try:
    # delete all existing rows
    layer.delete_features(where="1=1")

    # insert latest readings
    edit_result = layer.edit_features(adds=features)

    # log for GitHub Actions
    print(
        f"[{datetime.utcnow().isoformat()}Z] ✅ Updated {len(features)} features "
        f"with reading_time={reading_time_iso}"
    )
    print("ArcGIS response:", edit_result)

except Exception as exc:
    # print to Actions log and fail the job
    print(
        f"[{datetime.utcnow().isoformat()}Z] ❌ Failed to update rainfall layer: {exc}"
    )
    raise

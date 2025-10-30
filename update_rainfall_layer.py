# ============================================================
# update_rainfall_layer.py
# Purpose:
#   1. Fetch live rainfall readings from data.gov.sg
#   2. Convert API timestamp (UTC) → Singapore time (UTC+8)
#   3. Overwrite an existing hosted feature layer in ArcGIS Online
#   4. Designed to run in GitHub Actions (uses env vars)
# ============================================================

import os
import requests
from datetime import datetime, timedelta
from arcgis.gis import GIS
from arcgis.features import FeatureLayer

# ------------------------------------------------------------
# 1) Connect to ArcGIS Online
#    - In GitHub Actions, we read username/password from
#      repository secrets: ARCGIS_USERNAME, ARCGIS_PASSWORD
#    - In local test, you can export them first or hardcode.
# ------------------------------------------------------------
AGO_USERNAME = os.getenv("ARCGIS_USERNAME")
AGO_PASSWORD = os.getenv("ARCGIS_PASSWORD")

if not AGO_USERNAME or not AGO_PASSWORD:
    # Fail fast – this is the most common error in GitHub Actions
    raise RuntimeError(
        "ArcGIS Online credentials not found. "
        "Please set ARCGIS_USERNAME and ARCGIS_PASSWORD in GitHub Secrets."
    )

# Login to ArcGIS Online
gis = GIS("https://www.arcgis.com", AGO_USERNAME, AGO_PASSWORD)

# ------------------------------------------------------------
# 2) Get a handle on the hosted feature layer we want to update
#    NOTE: this must be the *layer URL*, not just the service URL
#    Your layer is:
#    https://services5.arcgis.com/KiRa9d9aHfdXiCqt/arcgis/rest/services/Rainfall_live/FeatureServer/0
# ------------------------------------------------------------
LAYER_URL = (
    "https://services5.arcgis.com/KiRa9d9aHfdXiCqt/arcgis/rest/services/"
    "Rainfall_live/FeatureServer/0"
)
layer = FeatureLayer(LAYER_URL)

# ------------------------------------------------------------
# 3) Call data.gov.sg rainfall API
#    Docs: https://data.gov.sg/dataset/realtime-weather-readings
#    It returns:
#      - metadata: station locations
#      - items[0].timestamp: time in UTC (e.g. 2025-10-30T09:20:00+00:00)
#      - items[0].readings: rainfall per station
# ------------------------------------------------------------
API_URL = "https://api.data.gov.sg/v1/environment/rainfall"
response = requests.get(API_URL, timeout=20)
response.raise_for_status()
rain_data = response.json()

# Build a dict of stations for quick lookup: {station_id: station_obj}
stations_by_id = {s["id"]: s for s in rain_data["metadata"]["stations"]}

# Latest reading block
latest_block = rain_data["items"][0]

# ------------------------------------------------------------
# 4) Convert API timestamp (UTC) → Singapore time (UTC+8)
#    ArcGIS stores dates in UTC, but since you prefer to SEE Singapore
#    time in the table, we shift it here.
# ------------------------------------------------------------
# Example input: "2025-10-30T09:20:00+00:00" or "2025-10-30T09:20:00Z"
raw_ts = latest_block["timestamp"]
# normalize the "Z" form to "+00:00" so datetime can parse it
utc_time = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
# add 8 hours for Singapore
sg_time = utc_time + timedelta(hours=8)
# convert back to ISO string, keep timezone
reading_time_iso = sg_time.isoformat()  # e.g. "2025-10-30T17:20:00+08:00"

# ------------------------------------------------------------
# 5) Build ArcGIS feature list
#    Each feature = geometry (lon/lat) + attributes
# ------------------------------------------------------------
features = []

for reading in latest_block["readings"]:
    station = stations_by_id.get(reading["station_id"])
    if not station:
        # skip if station not found in metadata
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
            # store Singapore time here
            "reading_time": reading_time_iso,
        },
    }
    features.append(feature)

# ------------------------------------------------------------
# 6) Push to ArcGIS Online
#    - First delete old features
#    - Then insert the new batch
# ------------------------------------------------------------
try:
    # wipe existing rows
    layer.delete_features(where="1=1")

    # add new rows
    add_result = layer.edit_features(adds=features)

    # log something human-readable so GitHub Actions shows it
    print(
        f"[{datetime.utcnow().isoformat()}Z] ✅ Updated "
        f"{len(features)} rainfall points at SG time {reading_time_iso}"
    )
    # also print ArcGIS response (good for debugging)
    print("ArcGIS add result:", add_result)

except Exception as exc:
    # print error for Actions log
    print(
        f"[{datetime.utcnow().isoformat()}Z] ❌ Failed to update rainfall layer: {exc}"
    )
    # re-raise so Actions marks the job as failed
    raise

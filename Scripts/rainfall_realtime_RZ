# ============================================================
# update_sg_rainfall_layer.py
# Purpose:
#   Fetch live rainfall readings from data.gov.sg
#   Overwrite (refresh) an existing hosted feature layer in ArcGIS Online
#   ✅ Cloud/GitHub Actions friendly version
# ============================================================

import os
from datetime import datetime
import requests
from arcgis.gis import GIS
from arcgis.features import FeatureLayer

# 1️⃣ Connect to ArcGIS Online using secrets (env vars)
AGO_USERNAME = os.getenv("ARCGIS_USERNAME")
AGO_PASSWORD = os.getenv("ARCGIS_PASSWORD")

if not AGO_USERNAME or not AGO_PASSWORD:
    raise RuntimeError("ArcGIS Online credentials not found. Set ARCGIS_USERNAME and ARCGIS_PASSWORD in GitHub Secrets.")

gis = GIS("https://www.arcgis.com", AGO_USERNAME, AGO_PASSWORD)

# 2️⃣ Hosted layer REST URL (FeatureServer layer 0)
LAYER_URL = "https://services5.arcgis.com/KiRa9d9aHfdXiCqt/arcgis/rest/services/Rainfall_live/FeatureServer/0"
layer = FeatureLayer(LAYER_URL)

# 3️⃣ Fetch rainfall JSON
resp = requests.get("https://api.data.gov.sg/v1/environment/rainfall", timeout=20)
resp.raise_for_status()
data = resp.json()

stations = {s["id"]: s for s in data["metadata"]["stations"]}
latest = data["items"][0]
timestamp = latest["timestamp"]

# 4️⃣ Convert readings → Feature objects
features = []
for rec in latest["readings"]:
    st = stations.get(rec["station_id"])
    if not st:
        continue
    features.append({
        "geometry": {
            "x": float(st["location"]["longitude"]),
            "y": float(st["location"]["latitude"]),
            "spatialReference": {"wkid": 4326}
        },
        "attributes": {
            "station_id": rec["station_id"],
            "station_name": st["name"],
            "rain_mm": rec.get("value"),
            "reading_time": timestamp
        }
    })

# 5️⃣ Delete old records, insert new ones
try:
    layer.delete_features(where="1=1")
    layer.edit_features(adds=features)
    print(f"[{datetime.utcnow().isoformat()}] ✅ Layer refreshed with {len(features)} points at {timestamp}")
except Exception as e:
    print(f"[{datetime.utcnow().isoformat()}] ❌ Failed to update layer: {e}")
    raise

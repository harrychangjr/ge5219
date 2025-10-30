# ============================================================
# update_sg_rainfall_layer.py
# Purpose:
#   1. Fetch 5-min rainfall data from data.gov.sg
#   2. Clear (truncate) an existing ArcGIS Online feature layer
#   3. Insert the latest features
# ============================================================

import requests
from arcgis.gis import GIS
from arcgis.features import FeatureLayer

# ------------------------------------------------------------
# TEMP: hard-coded credentials (move to env/secrets later)
# ------------------------------------------------------------
ARCGIS_USERNAME = "e1025426_gis2025"
ARCGIS_PASSWORD = "Zzr20010910-"

# Your FeatureServer layer 0 URL
LAYER_URL = "https://services5.arcgis.com/KiRa9d9aHfdXiCqt/arcgis/rest/services/Rainfall_live/FeatureServer/0"


def fetch_rainfall_data() -> dict:
    """Fetch the latest rainfall JSON from data.gov.sg."""
    url = "https://api.data.gov.sg/v1/environment/rainfall"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def build_features(api_data: dict) -> tuple[list, str]:
    """Convert data.gov.sg JSON to a list of ArcGIS features."""
    items = api_data.get("items", [])
    if not items:
        raise ValueError("No items in rainfall API response.")

    latest_item = items[0]
    reading_time = latest_item["timestamp"]  # already in +08:00

    readings_by_station = {r["station_id"]: r["value"] for r in latest_item.get("readings", [])}
    stations = api_data["metadata"]["stations"]

    features = []
    for station in stations:
        station_id = station["id"]
        rainfall_mm = readings_by_station.get(station_id, None)

        feature = {
            "attributes": {
                "station_id": station_id,
                "station_name": station.get("name"),
                "rainfall_mm": rainfall_mm,
                "reading_time": reading_time, 
            },
            "geometry": {
                "x": station["location"]["longitude"],
                "y": station["location"]["latitude"],
                "spatialReference": {"wkid": 4326},
            },
        }
        features.append(feature)

    return features, reading_time


def main():
    # 1. Log in
    gis = GIS("https://www.arcgis.com", ARCGIS_USERNAME, ARCGIS_PASSWORD)

    # 2. Bind to the hosted layer
    layer = FeatureLayer(LAYER_URL, gis=gis)

    # 3. Fetch rainfall data
    rainfall_data = fetch_rainfall_data()

    # 4. Convert to features
    features, reading_time = build_features(rainfall_data)

    # 5. Clear all existing records
    layer.manager.truncate()   # or: layer.delete_features(where="1=1")

    # 6. Insert latest data
    layer.edit_features(adds=features)

    print(f"✅ Rainfall layer refreshed at {reading_time} with {len(features)} stations.")


if __name__ == "__main__":
    main()

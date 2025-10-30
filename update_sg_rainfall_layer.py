# ============================================================
# update_sg_rainfall_layer.py
# Fetch 5-min rainfall from data.gov.sg and overwrite an
# ArcGIS Online hosted feature layer.
# TEMP VERSION: username/password are hard-coded.
# ============================================================

import requests
from arcgis.gis import GIS
from arcgis.features import FeatureLayerCollection

# ------------------------------------------------------------
# 1. TEMP credentials (you can move them to env/secrets later)
# ------------------------------------------------------------
ARCGIS_USERNAME = "e1025426_gis2025"
ARCGIS_PASSWORD = "Zzr20010910-"

# This must be your FeatureServer layer 0 URL
# Example:
# LAYER_URL = "https://services5.arcgis.com/xxxx/arcgis/rest/services/sg_rainfall/FeatureServer/0"
LAYER_URL = "https://services5.arcgis.com/XXXX/arcgis/rest/services/sg_rainfall/FeatureServer/0"


def fetch_rainfall_data() -> dict:
    """Download latest rainfall JSON from data.gov.sg."""
    url = "https://api.data.gov.sg/v1/environment/rainfall"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def build_feature_collection(api_data: dict) -> tuple[dict, str]:
    """Convert data.gov.sg JSON to ArcGIS Feature Collection (for overwrite)."""
    items = api_data.get("items", [])
    if not items:
        raise ValueError("No 'items' in rainfall API response.")

    latest_item = items[0]
    obs_time = latest_item["timestamp"]  # already in +08:00

    readings_by_station = {r["station_id"]: r["value"] for r in latest_item.get("readings", [])}
    stations = api_data["metadata"]["stations"]

    features = []
    for station in stations:
        station_id = station["id"]
        feature = {
            "attributes": {
                "station_id": station_id,
                "station_name": station.get("name"),
                "rainfall_mm": readings_by_station.get(station_id, None),
                "obs_time": obs_time,
            },
            "geometry": {
                "x": station["location"]["longitude"],
                "y": station["location"]["latitude"],
                "spatialReference": {"wkid": 4326},
            },
        }
        features.append(feature)

    feature_collection = {
        "layers": [
            {
                "layerDefinition": {
                    "name": "sg_rainfall",
                    "geometryType": "esriGeometryPoint",
                    "fields": [
                        {"name": "station_id", "type": "esriFieldTypeString"},
                        {"name": "station_name", "type": "esriFieldTypeString"},
                        {"name": "rainfall_mm", "type": "esriFieldTypeDouble"},
                        {"name": "obs_time", "type": "esriFieldTypeString"},
                    ],
                },
                "featureSet": {
                    "features": features,
                    "geometryType": "esriGeometryPoint",
                },
            }
        ]
    }

    return feature_collection, obs_time


def overwrite_layer(feature_collection: dict, gis: GIS, layer_url: str) -> None:
    """Overwrite existing hosted feature layer."""
    flc = FeatureLayerCollection.fromurl(layer_url, gis=gis)
    flc.manager.overwrite(feature_collection)


def main():
    # 1. login
    gis = GIS("https://www.arcgis.com", ARCGIS_USERNAME, ARCGIS_PASSWORD)

    # 2. get rainfall
    rainfall_data = fetch_rainfall_data()

    # 3. convert to feature collection
    fc, obs_time = build_feature_collection(rainfall_data)

    # 4. overwrite AGOL layer
    overwrite_layer(fc, gis, LAYER_URL)

    print(f"✅ Rainfall layer overwritten at {obs_time}")


if __name__ == "__main__":
    main()

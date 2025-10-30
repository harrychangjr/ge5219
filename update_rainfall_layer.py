# ============================================================
# update_sg_rainfall_layer.py
# Purpose:
#   1. Fetch latest 5-min rainfall readings from data.gov.sg
#   2. Convert them to ArcGIS features (points)
#   3. OVERWRITE an existing hosted feature layer in ArcGIS Online
# Notes:
#   - This script assumes the target layer already exists in ArcGIS Online.
#   - This script uses the timestamp provided by data.gov.sg directly.
#   - Designed to be run on GitHub Actions (username/password via env vars).
# ============================================================

import os
import requests
from arcgis.gis import GIS
from arcgis.features import FeatureLayerCollection


def get_arcgis_gis() -> GIS:
    """Log in to ArcGIS Online using environment variables."""
    username = os.getenv("ARCGIS_USERNAME")
    password = os.getenv("ARCGIS_PASSWORD")
    if not username or not password:
        raise RuntimeError(
            "ArcGIS credentials not found. Please set ARCGIS_USERNAME and ARCGIS_PASSWORD in secrets."
        )
    return GIS("https://www.arcgis.com", username, password)


def fetch_rainfall_data() -> dict:
    """Fetch the latest rainfall observation from data.gov.sg."""
    url = "https://api.data.gov.sg/v1/environment/rainfall"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json()


def build_feature_collection(api_data: dict) -> dict:
    """
    Convert data.gov.sg rainfall JSON into an ArcGIS Feature Collection dict
    that can be used to overwrite a hosted feature layer.
    """
    # data.gov.sg gives us:
    # - items[0].timestamp  -> observation time (already in +08:00)
    # - items[0].readings[] -> station_id, value
    # - metadata.stations[] -> id, name, location{lat, lon}
    items = api_data.get("items", [])
    if not items:
        raise ValueError("No 'items' found in rainfall API response.")

    latest_item = items[0]
    observation_time = latest_item["timestamp"]  # e.g. 2025-10-30T09:15:00+08:00

    readings_list = latest_item.get("readings", [])
    readings_by_station = {r["station_id"]: r["value"] for r in readings_list}

    stations = api_data["metadata"]["stations"]

    features = []
    for station in stations:
        station_id = station["id"]
        rainfall_value = readings_by_station.get(station_id, None)

        feature = {
            "attributes": {
                "station_id": station_id,
                "station_name": station.get("name"),
                "rainfall_mm": rainfall_value,
                "obs_time": observation_time,
            },
            "geometry": {
                "x": station["location"]["longitude"],
                "y": station["location"]["latitude"],
                "spatialReference": {"wkid": 4326},
            },
        }
        features.append(feature)

    # Build the Feature Collection payload
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

    return feature_collection, observation_time


def overwrite_arcgis_layer(gis: GIS, layer_url: str, feature_collection: dict) -> None:
    """
    Overwrite the existing hosted feature layer with the new feature collection.
    This will replace ALL existing features.
    """
    flc = FeatureLayerCollection.fromurl(layer_url, gis=gis)
    flc.manager.overwrite(feature_collection)


def main():
    # 1. Connect to ArcGIS Online
    gis = get_arcgis_gis()

    # 2. Target layer URL (FeatureServer/0)
    #    IMPORTANT: replace this with your actual layer URL
    layer_url = os.getenv("ARCGIS_LAYER_URL")
    if not layer_url:
        # fallback to hard-coded value if needed
        layer_url = "https://services5.arcgis.com/XXXX/arcgis/rest/services/sg_rainfall/FeatureServer/0"

    # 3. Fetch latest rainfall data
    rainfall_data = fetch_rainfall_data()

    # 4. Convert to feature collection
    feature_collection, obs_time = build_feature_collection(rainfall_data)

    # 5. Overwrite hosted layer
    overwrite_arcgis_layer(gis, layer_url, feature_collection)

    print(f"✅ Rainfall layer overwritten successfully at {obs_time}")


if __name__ == "__main__":
    main()

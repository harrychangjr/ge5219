import requests
from arcgis.gis import GIS
from arcgis.features import FeatureLayer
from datetime import datetime, timezone, timedelta

ARCGIS_USERNAME = "e1553302_gis2025"
ARCGIS_PASSWORD = "Whisperingdeath2@25"

FEATURE_LAYER_URL = "https://services5.arcgis.com/KiRa9d9aHfdXiCqt/arcgis/rest/services/WeatherStations/FeatureServer/0"  

def fetch_weather_data() -> dict:
    """Fetch the latest RH and temperature JSON from data.gov.sg."""
    temp_url = "https://api.data.gov.sg/v1/environment/air-temperature"
    rh_url   = "https://api.data.gov.sg/v1/environment/relative-humidity"

    resp_temp = requests.get(temp_url, timeout=30)
    resp_temp.raise_for_status()

    resp_rh = requests.get(rh_url, timeout=30)
    resp_rh.raise_for_status()

    return {
        "temperature": resp_temp.json(),
        "relative_humidity": resp_rh.json()
    }

# ------------------------------------------------------------
# Build ArcGIS features to upload
# ------------------------------------------------------------
def build_features(api_data: dict):
    temp_json = api_data["temperature"]
    rh_json   = api_data["relative_humidity"]

    temp_items = temp_json["items"][0]["readings"]
    rh_items   = rh_json["items"][0]["readings"]

    temp_by_id = {r["station_id"]: r["value"] for r in temp_items}
    rh_by_id   = {r["station_id"]: r["value"] for r in rh_items}

    stations = temp_json["metadata"]["stations"]
    timestamp = temp_json["items"][0]["timestamp"]
    # Convert timestamp string to a Python datetime (for Date field)
    dt_utc = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    sgt = timezone(timedelta(hours=8))
    reading_time = dt_utc.astimezone(sgt)
    
    features = []
    for s in stations:
        sid = s["id"]
        station_name = s["name"]
        lon = s["location"]["longitude"]
        lat = s["location"]["latitude"]

        T  = temp_by_id.get(sid)
        RH = rh_by_id.get(sid)

        feature = {
            "attributes": {
                "station_id": sid,
                "station_name": station_name,
                "temperature": T,
                "rh": RH,
                "updated_at": reading_time  # matches your Date field
            },
            "geometry": {
                "x": lon,
                "y": lat,
                "spatialReference": {"wkid": 4326}
            }
        }
        features.append(feature)

    return features, reading_time.isoformat()

# ------------------------------------------------------------
# Main update routine
# ------------------------------------------------------------
def main():
    # 1. Log in
    gis = GIS("https://www.arcgis.com", ARCGIS_USERNAME, ARCGIS_PASSWORD)
    layer = FeatureLayer(FEATURE_LAYER_URL, gis=gis)

    # 2. Fetch & build features
    weather_data = fetch_weather_data()
    features, reading_time = build_features(weather_data)

    # 3. Clear layer & insert new points
    print("Clearing existing records...")
    layer.manager.truncate()

    print(f"Adding {len(features)} features...")
    res = layer.edit_features(adds=features)

    print(f"Layer refreshed at {reading_time} with {len(features)} stations.")
    if res and res.get("addResults"):
        failed = [r for r in res["addResults"] if not r.get("success")]
        if failed:
            print("Some features failed to upload:", failed)

if __name__ == "__main__":
    main()
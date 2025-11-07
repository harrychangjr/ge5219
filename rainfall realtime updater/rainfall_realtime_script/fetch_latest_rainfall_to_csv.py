# ============================================================
# fetch_latest_rainfall_to_csv.py
#
# Standalone version:
#   - Fetch latest rainfall from data.gov.sg
#   - Join station metadata (lat/lon, name)
#   - Save clean CSV (+ optional GeoJSON, optional archive)
#   - No external "rainfall_realtime" package dependencies
# ============================================================

import os
import json
import argparse
from datetime import datetime, timezone, timedelta

import pandas as pd
import requests

API_URL = "https://api.data.gov.sg/v1/environment/rainfall"


def log(msg: str) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{now}] {msg}")


def fetch_json(url: str) -> dict:
    """Fetch JSON from given URL with basic error handling."""
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse_latest_item_to_dataframe(payload: dict) -> pd.DataFrame:
    """
    Convert the latest items[0] block into a tidy DataFrame.

    Output columns:
      - Station ID
      - Station Name
      - Rainfall (mm/hr)
      - Reading Time   (ISO string from API)
      - lat
      - lon
    """
    items = payload.get("items", [])
    if not items:
        raise ValueError("No 'items' in rainfall payload.")
    latest = items[0]
    ts = latest.get("timestamp")
    readings = latest.get("readings", [])
    stations = payload.get("metadata", {}).get("stations", [])

    # Index station metadata by id
    station_meta = {s.get("id"): s for s in stations}

    rows = []
    for r in readings:
        sid = r.get("station_id")
        val = r.get("value")
        meta = station_meta.get(sid, {})
        name = meta.get("name", sid)
        loc = meta.get("location", {}) or {}
        lat = loc.get("latitude") or loc.get("lat")
        lon = loc.get("longitude") or loc.get("lon")

        rows.append(
            {
                "Station ID": sid,
                "Station Name": name,
                "Rainfall (mm/hr)": val,
                "Reading Time": ts,
                "lat": lat,
                "lon": lon,
            }
        )

    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Enforce column order
    return df[["Station ID", "Station Name", "Rainfall (mm/hr)", "Reading Time", "lat", "lon"]]


def iso_to_sgt_tag(iso_str: str) -> str:
    """Convert ISO timestamp to compact Singapore-time tag for filenames."""
    if not iso_str:
        return "unknown_time"
    # Ensure we have an offset for fromisoformat
    if iso_str.endswith("Z"):
        iso_str = iso_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(iso_str)
    sgt = dt.astimezone(timezone(timedelta(hours=8)))
    return sgt.strftime("%Y%m%d_%H%M")


def save_outputs(
    df: pd.DataFrame,
    out_dir: str,
    prefix: str,
    latest_iso: str,
    write_geojson: bool,
    archive: bool,
) -> None:
    os.makedirs(out_dir, exist_ok=True)

    # 1️⃣ Fixed CSV (overwrite each run)
    csv_path = os.path.join(out_dir, f"{prefix}.csv")
    df.to_csv(csv_path, index=False)
    log(f"CSV saved → {csv_path}")

    # 2️⃣ Fixed GeoJSON (optional)
    gj_path = None
    if write_geojson:
        features = []
        for _, row in df.iterrows():
            if pd.isna(row["lat"]) or pd.isna(row["lon"]):
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [float(row["lon"]), float(row["lat"])],
                    },
                    "properties": {
                        "station_id": row["Station ID"],
                        "station_name": row["Station Name"],
                        "rainfall_mm_hr": row["Rainfall (mm/hr)"],
                        "reading_time": row["Reading Time"],
                    },
                }
            )
        gj = {"type": "FeatureCollection", "features": features}
        gj_path = os.path.join(out_dir, f"{prefix}.geojson")
        with open(gj_path, "w", encoding="utf-8") as f:
            json.dump(gj, f, ensure_ascii=False, indent=2)
        log(f"GeoJSON saved → {gj_path}")

    # 3️⃣ Optional archive copies with timestamp tag
    if archive:
        tag = iso_to_sgt_tag(latest_iso)

        arch_csv = os.path.join(out_dir, f"{prefix}_{tag}.csv")
        df.to_csv(arch_csv, index=False)
        log(f"Archived CSV → {arch_csv}")

        if write_geojson and gj_path:
            arch_gj = os.path.join(out_dir, f"{prefix}_{tag}.geojson")
            with open(gj_path, "r", encoding="utf-8") as src, open(
                arch_gj, "w", encoding="utf-8"
            ) as dst:
                dst.write(src.read())
            log(f"Archived GeoJSON → {arch_gj}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fetch latest rainfall readings → CSV (and optionally GeoJSON)."
    )
    parser.add_argument(
        "--out_dir",
        required=True,
        help="Directory to write outputs (will be created if it does not exist).",
    )
    parser.add_argument(
        "--prefix",
        default="rainfall_latest",
        help="Base output name (default: rainfall_latest).",
    )
    parser.add_argument(
        "--geojson",
        action="store_true",
        help="Also export a GeoJSON with rainfall station points.",
    )
    parser.add_argument(
        "--archive",
        action="store_true",
        help="Also write timestamped archive copies of CSV/GeoJSON.",
    )

    args = parser.parse_args()

    log("Requesting latest rainfall payload...")
    payload = fetch_json(API_URL)

    log("Parsing payload → tidy DataFrame...")
    df = parse_latest_item_to_dataframe(payload)
    if df.empty:
        raise RuntimeError("No readings found in latest rainfall payload.")
    log(f"Got {len(df)} station readings.")

    latest_iso = payload.get("items", [{}])[0].get("timestamp", "")

    save_outputs(
        df=df,
        out_dir=args.out_dir,
        prefix=args.prefix,
        latest_iso=latest_iso,
        write_geojson=args.geojson,
        archive=args.archive,
    )

    log("Done.")


if __name__ == "__main__":
    main()
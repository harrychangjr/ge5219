from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Tuple

import pandas as pd
import requests
from requests.adapters import HTTPAdapter, Retry


# ========== Logging ==========
def log(msg: str, level: str = "INFO") -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] [{level}] {msg}")


# ========== Resilient HTTP Session ==========
_session: Optional[requests.Session] = None

def _get_session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(
            total=6,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=("GET", "HEAD"),
            raise_on_status=False,
        )
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.mount("http://", HTTPAdapter(max_retries=retry))
        _session = s
    return _session


def fetch_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Any:
    """GET a JSON payload with sensible retries and surfaced errors."""
    log(f"Fetching JSON: {url}")
    r = _get_session().get(url, params=params or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ========== Filesystem helpers ==========
def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M")


# ========== Timestamped save helpers (archive-friendly) ==========
def save_csv(
    df: pd.DataFrame,
    out_dir: str,
    prefix: str,
    index: bool = False,
) -> str:
    """
    Save DataFrame to a timestamped CSV (e.g., <prefix>_YYYYMMDD_HHMM.csv) and return the path.
    """
    _ensure_dir(out_dir)
    path = os.path.join(out_dir, f"{prefix}_{_timestamp()}.csv")
    df.to_csv(path, index=index)
    log(f"Saved CSV → {path}")
    return path


def _df_to_feature_collection(
    df: pd.DataFrame,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    properties: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Convert a DataFrame with lat/lon columns to a GeoJSON FeatureCollection dict."""
    if lat_col not in df.columns or lon_col not in df.columns:
        raise ValueError(f"Expected columns '{lat_col}' and '{lon_col}' in DataFrame.")

    props = list(properties) if properties is not None else [
        c for c in df.columns if c not in (lat_col, lon_col)
    ]

    features = []
    for _, row in df.iterrows():
        try:
            lat = float(row[lat_col])
            lon = float(row[lon_col])
        except Exception:
            # Skip rows with invalid coordinates
            continue

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {k: (None if pd.isna(row[k]) else row[k]) for k in props},
            }
        )

    return {"type": "FeatureCollection", "features": features}


def save_geojson(
    df: pd.DataFrame,
    out_dir: str,
    prefix: str,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    properties: Optional[Iterable[str]] = None,
    ensure_ascii: bool = False,
    indent: int = 2,
) -> str:
    """
    Save a timestamped GeoJSON FeatureCollection (e.g., <prefix>_YYYYMMDD_HHMM.geojson)
    and return the path.
    """
    _ensure_dir(out_dir)
    path = os.path.join(out_dir, f"{prefix}_{_timestamp()}.geojson")
    fc = _df_to_feature_collection(df, lat_col=lat_col, lon_col=lon_col, properties=properties)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=ensure_ascii, indent=indent)
    log(f"Saved GeoJSON → {path}")
    return path


def save_csv_and_geojson(
    df: pd.DataFrame,
    out_dir: str,
    prefix: str,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    properties: Optional[Iterable[str]] = None,
) -> Tuple[str, Optional[str]]:
    """
    Save timestamped CSV and, if lat/lon exist, timestamped GeoJSON.
    Returns (csv_path, geojson_path_or_None).
    """
    csv_path = save_csv(df, out_dir, prefix)
    gj_path = None
    if lat_col in df.columns and lon_col in df.columns:
        try:
            gj_path = save_geojson(
                df, out_dir, prefix, lat_col=lat_col, lon_col=lon_col, properties=properties
            )
        except Exception as e:
            log(f"GeoJSON save skipped: {e}", level="WARNING")
    else:
        log("GeoJSON save skipped: latitude/longitude columns not found", level="WARNING")
    return csv_path, gj_path


# ========== Fixed-name save helpers (for “latest” outputs) ==========
def save_csv_fixed(df: pd.DataFrame, out_dir: str, base_name: str, index: bool = False) -> str:
    """
    Save DataFrame to a *fixed* CSV filename: <out_dir>/<base_name>.csv
    (overwritten each run). Returns the path.
    """
    _ensure_dir(out_dir)
    path = os.path.join(out_dir, f"{base_name}.csv")
    df.to_csv(path, index=index)
    log(f"Saved CSV → {path}")
    return path


def save_geojson_fixed(
    df: pd.DataFrame,
    out_dir: str,
    base_name: str,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    properties: Optional[Iterable[str]] = None,
) -> str:
    """
    Save a *fixed* GeoJSON filename: <out_dir>/<base_name>.geojson
    (overwritten each run). Returns the path.
    """
    _ensure_dir(out_dir)
    path = os.path.join(out_dir, f"{base_name}.geojson")
    fc = _df_to_feature_collection(df, lat_col=lat_col, lon_col=lon_col, properties=properties)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, indent=2)
    log(f"Saved GeoJSON → {path}")
    return path


def save_latest_bundle(
    df: pd.DataFrame,
    out_dir: str,
    base_name: str,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    write_geojson: bool = True,
) -> Tuple[str, Optional[str]]:
    """
    Write the canonical “latest” files that are overwritten each run:
      - <base_name>.csv
      - <base_name>.geojson (optional)
    Returns (csv_path, geojson_path_or_None).
    """
    csv_path = save_csv_fixed(df, out_dir, base_name)
    gj_path = None
    if write_geojson:
        gj_path = save_geojson_fixed(df, out_dir, base_name, lat_col=lat_col, lon_col=lon_col)
    return csv_path, gj_path
 
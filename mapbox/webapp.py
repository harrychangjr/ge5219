import os
import subprocess
from datetime import datetime
import requests
import numpy as np
import geopandas as gpd
from shapely.geometry import Point, mapping
import rasterio
from rasterio.transform import from_origin
from rasterio.mask import mask
from pyproj import CRS

print("✅ Loaded pure-Python GIS stack (IDW version, no ArcPy)")

# --------------------------------------------------------
# CONFIGURATION
# --------------------------------------------------------
mapbox_username = "nw03"
dataset_name = "nea_points"
mapbox_access_token = "sk.eyJ1IjoibncwMyIsImEiOiJjbWhuaDYxdnMwMGhmMmlyenFycXNoM2tzIn0.d0oaGmXCmqMxFiG124kIbA"

script_dir = os.getcwd()
data_folder = os.path.join(script_dir, "Data")
web_folder = os.path.join(data_folder, "web")
os.makedirs(web_folder, exist_ok=True)

boundary_shp = os.path.join(
    data_folder, "planning_area_boundary", "planning_area_boundary.shp"
)
if not os.path.exists(boundary_shp):
    raise FileNotFoundError(f"Singapore boundary not found at {boundary_shp}")
else:
    print("Found Singapore boundary shapefile:", os.path.normpath(boundary_shp))

# Output paths
temp_ras = os.path.join(data_folder, "temperature_svy21.tif")
rh_ras = os.path.join(data_folder, "humidity_svy21.tif")
humidex_ras = os.path.join(data_folder, "humidex_svy21.tif")
humidex_ras_norm = os.path.splitext(humidex_ras)[0] + "_norm.tif"
points_geojson = os.path.join(data_folder, "nea_environment_points.geojson")

SVY21_EPSG = 3414
CELL_SIZE = 100        # metres
IDW_POWER = 2          # typical 1–3

# --------------------------------------------------------
# Fetch NEA API
# --------------------------------------------------------
def fetch_weather_data():
    temp_url = "https://api.data.gov.sg/v1/environment/air-temperature"
    rh_url   = "https://api.data.gov.sg/v1/environment/relative-humidity"
    temp = requests.get(temp_url, timeout=30).json()
    rh   = requests.get(rh_url, timeout=30).json()
    return temp, rh

# --------------------------------------------------------
# Build GeoDataFrame in SVY21
# --------------------------------------------------------
def build_geodataframe(temp_json, rh_json):
    temp_items = temp_json["items"][0]["readings"]
    rh_items   = rh_json["items"][0]["readings"]
    temp_by_id = {r["station_id"]: r["value"] for r in temp_items}
    rh_by_id   = {r["station_id"]: r["value"] for r in rh_items}

    stations = temp_json["metadata"]["stations"]
    rows = []
    for s in stations:
        sid = s["id"]
        T = temp_by_id.get(sid)
        RH = rh_by_id.get(sid)
        if T is None or RH is None:
            continue
        rows.append(
            {
                "station_id": sid,
                "T": float(T),
                "RH": float(RH),
                "geometry": Point(s["location"]["longitude"], s["location"]["latitude"]),
            }
        )
    gdf = gpd.GeoDataFrame(rows, crs="EPSG:4326")
    gdf = gdf.to_crs(epsg=SVY21_EPSG)
    return gdf

# --------------------------------------------------------
# Create grid snapped to boundary extent
# --------------------------------------------------------
def make_grid(bounds, cell):
    xmin, ymin, xmax, ymax = bounds
    xs = np.arange(xmin, xmax + cell, cell)
    ys = np.arange(ymin, ymax + cell, cell)
    xi, yi = np.meshgrid(xs, ys)
    return xs, ys, xi, yi

# --------------------------------------------------------
# IDW interpolation
# --------------------------------------------------------
def idw_interpolate(points_gdf, field, boundary_gdf, cell=CELL_SIZE, power=IDW_POWER):
    x = points_gdf.geometry.x.values
    y = points_gdf.geometry.y.values
    z = points_gdf[field].values
    xs, ys, xi, yi = make_grid(boundary_gdf.total_bounds, cell)

    # Flatten grid for vectorized math
    xi_flat, yi_flat = xi.ravel(), yi.ravel()
    xi_b = xi_flat[:, None]
    yi_b = yi_flat[:, None]

    # squared distances
    dist2 = (xi_b - x)**2 + (yi_b - y)**2
    dist2[dist2 == 0] = 1e-10
    weights = 1.0 / dist2**(power / 2)
    wsum = np.sum(weights, axis=1)
    zsum = np.sum(weights * z, axis=1)
    zi = zsum / wsum
    zi = zi.reshape(xi.shape).astype("float32")

    transform = from_origin(xs[0], ys[-1] + cell, cell, cell)
    return zi, transform

# --------------------------------------------------------
# Save raster and clip to boundary polygon
# --------------------------------------------------------
def save_and_clip_raster(array2d, transform, crs_epsg, boundary_gdf, out_path):
    """Save raster and crop it tightly to the boundary extent (no full-extent rectangle)."""
    import rasterio
    from rasterio.mask import mask
    from shapely.geometry import mapping
    import numpy as np

    # --- Step 1: Write temp unmasked raster ---
    temp_path = out_path.replace(".tif", "_temp.tif")
    with rasterio.open(
        temp_path,
        "w",
        driver="GTiff",
        height=array2d.shape[0],
        width=array2d.shape[1],
        count=1,
        dtype=array2d.dtype,
        crs=CRS.from_epsg(crs_epsg),
        transform=transform,
    ) as dst:
        dst.write(array2d, 1)

    # --- Step 2: Proper mask/crop ---
    with rasterio.open(temp_path) as src:
        if boundary_gdf.crs != src.crs:
            boundary_gdf = boundary_gdf.to_crs(src.crs)
        geoms = [mapping(boundary_gdf.unary_union)]
        clipped, clipped_transform = mask(src, geoms, crop=True, filled=True, nodata=np.nan)
        meta = src.meta.copy()
        meta.update({
            "height": clipped.shape[1],
            "width": clipped.shape[2],
            "transform": clipped_transform,
            "nodata": np.nan
        })

    # --- Step 3: Write clipped result ---
    with rasterio.open(out_path, "w", **meta) as dst:
        dst.write(clipped)

    os.remove(temp_path)  # clean up
    print(f"✅ Saved and tightly clipped raster → {out_path}")

# --------------------------------------------------------
# Humidex + normalization
# --------------------------------------------------------
def compute_humidex_raster(temp_arr, rh_arr):
    T = temp_arr.astype("float64")
    RH = rh_arr.astype("float64")
    e = 6.11 * np.exp(5417.7530 * ((1 / 273.16) - (1 / (273.15 + T))))
    H = 0.5555 * (e * RH / 100.0 - 10.0)
    humidex = T + H
    return humidex.astype("float32")

def normalize_0_100(arr):
    finite = np.isfinite(arr)
    if not finite.any():
        return arr
    vmin = np.nanmin(arr[finite])
    vmax = np.nanmax(arr[finite])
    if vmax == vmin:
        return np.zeros_like(arr, dtype="float32")
    norm = (arr - vmin) / (vmax - vmin) * 100.0
    return norm.astype("float32")

# --------------------------------------------------------
# Convert normalized raster → 8-bit TIFF
# --------------------------------------------------------
def convert_to_8bit(in_tif, out_tif):
    with rasterio.open(in_tif) as src:
        data = src.read(1)
        meta = src.meta.copy()
        scaled = np.clip(data, 0, 100) / 100 * 255
        meta.update(dtype="uint8")

    with rasterio.open(out_tif, "w", **meta) as dst:
        dst.write(scaled.astype("uint8"), 1)
    print(f"🌐 Converted to 8-bit TIFF → {out_tif}")

# --------------------------------------------------------
# Mapbox Uploads API
# --------------------------------------------------------
import boto3
import json
import requests

def upload_to_mapbox(file_path, username, dataset_name, access_token):
    """Upload a GeoJSON or GeoTIFF to Mapbox automatically."""
    print(f"🚀 Uploading {os.path.basename(file_path)} to Mapbox...")

    creds_url = f"https://api.mapbox.com/uploads/v1/{username}/credentials?access_token={access_token}"
    creds = requests.post(creds_url)
    creds.raise_for_status()
    creds_json = creds.json()
    print("DEBUG credentials response:", creds_json)

    if "fields" in creds_json and "url" in creds_json:
        s3_url = creds_json["url"]
        s3_fields = creds_json["fields"]
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f)}
            resp = requests.post(s3_url, data=s3_fields, files=files)
            resp.raise_for_status()
        upload_url = s3_url + "/" + s3_fields["key"]
    elif all(k in creds_json for k in ("bucket", "key", "accessKeyId", "secretAccessKey", "sessionToken")):
        s3 = boto3.client(
            "s3",
            aws_access_key_id=creds_json["accessKeyId"],
            aws_secret_access_key=creds_json["secretAccessKey"],
            aws_session_token=creds_json["sessionToken"],
            region_name="us-east-1"
        )
        with open(file_path, "rb") as f:
            s3.upload_fileobj(f, creds_json["bucket"], creds_json["key"])
        upload_url = f"https://{creds_json['bucket']}.s3.amazonaws.com/{creds_json['key']}"
    else:
        print("❌ Unrecognized credentials response:")
        print(json.dumps(creds_json, indent=2))
        raise RuntimeError("Mapbox did not return recognizable upload credentials.")

    tileset = f"{username}.{dataset_name}"
    body = {"url": upload_url, "tileset": tileset, "name": dataset_name}
    resp = requests.post(f"https://api.mapbox.com/uploads/v1/{username}?access_token={access_token}", json=body)
    resp.raise_for_status()
    print(f"✅ {dataset_name} uploaded to Mapbox. Processing may take 1–3 min.")

# --------------------------------------------------------
# Convert normalized raster → 8-bit TIFF (preserve NoData)
# --------------------------------------------------------
def convert_to_8bit_with_alpha(in_tif, out_tif, boundary_gdf=None):
    """
    Pure rasterio version (no GDAL, no ArcPy).
    Converts a normalized (0–100) GeoTIFF to a clipped RGBA 8-bit GeoTIFF
    with transparency outside the Singapore boundary (no black edges).
    Suitable for Mapbox Upload API.
    """
    import rasterio
    from rasterio.mask import mask
    import numpy as np
    from shapely.geometry import mapping

    with rasterio.open(in_tif) as src:
        data = src.read(1).astype("float32")
        meta = src.meta.copy()

        # --- Optional clipping to boundary polygon ---
        if boundary_gdf is not None:
            if boundary_gdf.crs != src.crs:
                boundary_gdf = boundary_gdf.to_crs(src.crs)
            geoms = [mapping(boundary_gdf.unary_union)]
            clipped, transform = mask(src, geoms, crop=True, filled=True, nodata=np.nan)
            data = clipped[0]
            meta.update({
                "height": data.shape[0],
                "width": data.shape[1],
                "transform": transform
            })

        # --- Convert normalized values (0–100) → grayscale 0–255 ---
        mask_valid = np.isfinite(data)
        scaled = np.zeros_like(data, dtype="uint8")
        scaled[mask_valid] = np.clip((data[mask_valid] / 100.0) * 255.0, 0, 255)

        # --- Build RGBA channels ---
        R = G = B = scaled
        A = np.where(mask_valid, 255, 0).astype("uint8")

        meta.update({
            "driver": "GTiff",
            "dtype": "uint8",
            "count": 4,            # RGBA
            "compress": "lzw",
            "tiled": True,
            "photometric": "RGB",
            "nodata": None         # prevents NaN issue for uint8
        })

        with rasterio.open(out_tif, "w", **meta) as dst:
            dst.write(R, 1)
            dst.write(G, 2)
            dst.write(B, 3)
            dst.write(A, 4)
            dst.set_band_description(4, "alpha")

    print(f"✅ Saved RGBA GeoTIFF (Mapbox-ready, transparent edges) → {out_tif}")


# --------------------------------------------------------
# MAIN
# --------------------------------------------------------
def main():
    print("Fetching NEA data…")
    temp_json, rh_json = fetch_weather_data()

    print("Building SVY21 GeoDataFrame…")
    pts = build_geodataframe(temp_json, rh_json)
    pts.to_file(points_geojson, driver="GeoJSON")
    print(f"✅ Exported environment points → {points_geojson}")

    boundary = gpd.read_file(boundary_shp)
    if boundary.crs is None or boundary.crs.to_epsg() != SVY21_EPSG:
        boundary = boundary.to_crs(epsg=SVY21_EPSG)

    print("Interpolating Temperature (IDW)…")
    T_arr, T_transform = idw_interpolate(pts, "T", boundary)
    save_and_clip_raster(T_arr, T_transform, SVY21_EPSG, boundary, temp_ras)

    print("Interpolating Relative Humidity (IDW)…")
    RH_arr, RH_transform = idw_interpolate(pts, "RH", boundary)
    save_and_clip_raster(RH_arr, RH_transform, SVY21_EPSG, boundary, rh_ras)

    print("Computing Humidex raster…")
    H_arr = compute_humidex_raster(T_arr, RH_arr)
    save_and_clip_raster(H_arr, T_transform, SVY21_EPSG, boundary, humidex_ras)

    print("Normalizing Humidex to 0–100…")
    H_norm = normalize_0_100(H_arr)
    save_and_clip_raster(H_norm, T_transform, SVY21_EPSG, boundary, humidex_ras_norm)

    print("🎉 Done. All rasters SVY21, clipped, IDW-interpolated.")

    # --------------------------------------------------------
    # Prepare web-safe exports for Mapbox
    # --------------------------------------------------------
    print("🌍 Preparing web-safe layers for Mapbox...")

    # 1️⃣ Points → WGS84
    pts_wgs84 = pts.to_crs(epsg=4326)
    points_geojson_web = os.path.join(web_folder, "nea_environment_points_wgs84.geojson")
    pts_wgs84.to_file(points_geojson_web, driver="GeoJSON")

     # 2️⃣ Normalized humidex → 8-bit TIFF with transparency + clip
    humidex_8bit_clipped = os.path.join(web_folder, "humidex_norm_8bit_clipped.tif")
    convert_to_8bit_with_alpha(humidex_ras_norm, humidex_8bit_clipped, boundary)

    # 3️⃣ Upload to Mapbox
    print("Uploading to Mapbox...")
    token = os.getenv("MAPBOX_TOKEN") or mapbox_access_token

    upload_to_mapbox(points_geojson_web, mapbox_username, dataset_name, token)
    upload_to_mapbox(humidex_8bit_clipped, mapbox_username, "humidex_raster", token)

    print("🎉 All uploads sent to Mapbox.")

if __name__ == "__main__":
    main()

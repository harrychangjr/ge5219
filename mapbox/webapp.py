import os
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
DATASET_NAME = "nea_points"
mapbox_access_token = "sk.eyJ1IjoibncwMyIsImEiOiJjbWhuaDYxdnMwMGhmMmlyenFycXNoM2tzIn0.d0oaGmXCmqMxFiG124kIbA"

script_dir = os.getcwd()
data_folder = os.path.join(script_dir, "Data")

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
    with rasterio.open(
        out_path,
        "w",
        driver="GTiff",
        height=array2d.shape[0],
        width=array2d.shape[1],
        count=1,
        dtype=array2d.dtype,
        crs=CRS.from_epsg(crs_epsg),
        transform=transform,
        compress="lzw",
    ) as dst:
        dst.write(array2d, 1)

    # Clip to boundary polygon
    with rasterio.open(out_path) as src:
        geoms = [mapping(boundary_gdf.unary_union)]
        clipped, clipped_transform = mask(src, geoms, crop=True)
        meta = src.meta.copy()
        meta.update(
            {
                "height": clipped.shape[1],
                "width": clipped.shape[2],
                "transform": clipped_transform,
            }
        )
    with rasterio.open(out_path, "w", **meta) as dst:
        dst.write(clipped)

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
    print(f"✅ Saved {temp_ras}")

    print("Interpolating Relative Humidity (IDW)…")
    RH_arr, RH_transform = idw_interpolate(pts, "RH", boundary)
    save_and_clip_raster(RH_arr, RH_transform, SVY21_EPSG, boundary, rh_ras)
    print(f"✅ Saved {rh_ras}")

    print("Computing Humidex raster…")
    H_arr = compute_humidex_raster(T_arr, RH_arr)
    save_and_clip_raster(H_arr, T_transform, SVY21_EPSG, boundary, humidex_ras)
    print(f"✅ Saved {humidex_ras}")

    print("Normalizing Humidex to 0–100…")
    H_norm = normalize_0_100(H_arr)
    save_and_clip_raster(H_norm, T_transform, SVY21_EPSG, boundary, humidex_ras_norm)
    print(f"✅ Saved normalized Humidex → {humidex_ras_norm}")

    print("🎉 Done. All rasters SVY21, clipped, IDW-interpolated.")

if __name__ == "__main__":
    main()

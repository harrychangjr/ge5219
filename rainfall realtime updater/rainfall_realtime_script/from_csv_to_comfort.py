# ============================================================
# from_csv_to_comfort.py
#
# Purpose
# -------
# End-to-end script to:
#   - Read latest rainfall_latest.csv
#   - Convert to projected rainfall points
#   - If no effective rain:
#         create 100% comfort raster
#     Else:
#         create comfort raster from:
#             IDW rainfall + shelter_01_30m
#   - Always:
#         save final raster as comfort_score_30m in GDB
#         export GeoTIFF as comfort_score_latest.tif
#   - Clean up temporary data so nothing keeps piling up.
#
# Design
# ------
# - No timestamp-based folder names.
# - No datetime-based path logic.
# - Only one final raster in GDB.
# - Only one final GeoTIFF on disk (overwritten every run).
#
# Requirements
# ------------
# - ArcGIS Pro with Spatial Analyst.
# - rainfall_pipeline.gdb contains:
#       sg_boundary_3414    (polygon, SVY21)
#       shelter_01_30m      (raster, 0/1, 30m, SVY21)
# - CSV file rainfall_latest.csv contains:
#       Station ID
#       Station Name
#       Rainfall__mm_hr_    (created by ArcGIS when reading from CSV)
#       Reading_Time
#       lat
#       lon
#
# ============================================================

import os
import shutil

import arcpy
from arcpy.sa import *

# ------------------------------------------------------------
# Global environment settings
# ------------------------------------------------------------
arcpy.CheckOutExtension("Spatial")
arcpy.env.overwriteOutput = True
arcpy.env.addOutputsToMap = False  # Do not auto-add layers to the map


# ============================================================
# STEP 1: PATH SETTINGS
# ============================================================
print("\n==================== STEP 1: PATH SETTINGS ====================")

# File geodatabase for this pipeline
project_gdb = (
    r"C:\Users\zirui\Documents\ArcGIS\Projects\rainfall_pipeline\rainfall_pipeline.gdb"
)

# Latest rainfall CSV produced by fetch_latest_rainfall_to_csv.py
csv_path = (
    r"C:\Users\zirui\Desktop\5219 final\rainfall realtime updater\output_data"
    r"\rainfall_latest.csv"
)

# Core reference datasets
sg_boundary_fc = os.path.join(project_gdb, "sg_boundary_3414")
shelter_raster_path = os.path.join(project_gdb, "shelter_01_30m")

# Final comfort raster (always overwritten)
comfort_out = os.path.join(project_gdb, "comfort_score_30m")

# A single GeoTIFF for Mapbox (always overwritten)
tif_out = (
    r"C:\Users\zirui\Desktop\5219 final\rainfall realtime updater\output_data"
    r"\comfort_score_latest.tif"
)

# Temporary feature classes inside the GDB
rain_points_wgs84_tmp = os.path.join(project_gdb, "_rain_points_wgs84_tmp")
rain_points_3414_tmp = os.path.join(project_gdb, "_rain_points_3414_tmp")

# Temporary layer name for latest timestamp selection
latest_lyr = "rain_latest_lyr"

print(f"[INFO] Geodatabase: {project_gdb}")
print(f"[INFO] CSV input : {csv_path}")
print(f"[INFO] Final GDB raster : {comfort_out}")
print(f"[INFO] Final GeoTIFF    : {tif_out}")
print("✅ STEP 1 completed.\n")


# ============================================================
# STEP 2: CLEANUP OLD OUTPUTS
# ============================================================
print("==================== STEP 2: CLEANUP OLD DATA ====================")

# Delete previous final outputs (we always overwrite with latest)
for item in [comfort_out, tif_out, rain_points_wgs84_tmp, rain_points_3414_tmp, latest_lyr]:
    if arcpy.Exists(item):
        arcpy.management.Delete(item)
        print(f"[CLEANUP] Deleted previous {item}")

print("✅ STEP 2 completed.\n")


# ============================================================
# STEP 3: VALIDATE INPUTS
# ============================================================
print("==================== STEP 3: VALIDATING INPUTS ====================")

if not os.path.exists(csv_path):
    raise RuntimeError(f"Rainfall CSV not found: {csv_path}")

if not arcpy.Exists(sg_boundary_fc):
    raise RuntimeError("Missing sg_boundary_3414 in rainfall_pipeline.gdb.")

if not arcpy.Exists(shelter_raster_path):
    raise RuntimeError("Missing shelter_01_30m in rainfall_pipeline.gdb.")

print("✅ STEP 3 completed – all inputs exist.\n")


# ============================================================
# Helper: write full 100% comfort and export TIFF
# ============================================================
def write_full_comfort():
    """
    Create a full 100% comfort raster based on shelter_01_30m grid
    and export it as both:
      - comfort_score_30m in the GDB
      - comfort_score_latest.tif in output_data
    """
    print("[INFO] Creating full 100% comfort raster (no effective rainfall).")

    template = Raster(shelter_raster_path)
    base = template * 0
    comfort = base + 100

    # Save into GDB
    comfort.save(comfort_out)
    print(f"[INFO] Saved full comfort raster → {comfort_out}")

    # Export GeoTIFF (overwrite)
    arcpy.management.CopyRaster(
        in_raster=comfort_out,
        out_rasterdataset=tif_out,
        format="TIFF",
        nodata_value=0,
        pixel_type="32_BIT_FLOAT"
    )
    print(f"[INFO] Exported full comfort GeoTIFF → {tif_out}")


# ============================================================
# STEP 4: CSV → TEMP POINTS
# ============================================================
print("==================== STEP 4: CSV → TEMP POINTS ====================")

# Create XY Event Layer from CSV (WGS84)
sr_wgs84 = arcpy.SpatialReference(4326)
sr_svy21 = arcpy.SpatialReference(3414)

xy_layer = "rain_xy_layer"

arcpy.management.MakeXYEventLayer(
    table=csv_path,
    in_x_field="lon",
    in_y_field="lat",
    out_layer=xy_layer,
    spatial_reference=sr_wgs84
)

# If no rows at all → full comfort and exit
if int(arcpy.management.GetCount(xy_layer)[0]) == 0:
    print("[WARN] CSV has no rows → fallback to full comfort.")
    write_full_comfort()
    raise SystemExit(0)

# Copy to a proper feature class in WGS84
arcpy.management.CopyFeatures(xy_layer, rain_points_wgs84_tmp)

# Project into SVY21
arcpy.management.Project(
    in_dataset=rain_points_wgs84_tmp,
    out_dataset=rain_points_3414_tmp,
    out_coor_system=sr_svy21,
)

print("✅ STEP 4 completed – temporary projected points created.\n")


# ============================================================
# STEP 5: STANDARDIZE FIELDS
# ============================================================
print("==================== STEP 5: STANDARDIZING FIELDS ====================")

# We know the CSV→GDB field names from your environment:
# - Rainfall__mm_hr_  (rainfall values)
# - Reading_Time      (timestamp, stored as text)
rain_src_field = "Rainfall__mm_hr_"
time_src_field = "Reading_Time"

fields = [f.name for f in arcpy.ListFields(rain_points_3414_tmp)]
print("[DEBUG] Fields in _rain_points_3414_tmp:", fields)

if rain_src_field not in fields:
    raise RuntimeError(f"Expected rainfall field '{rain_src_field}' not found.")
if time_src_field not in fields:
    raise RuntimeError(f"Expected time field '{time_src_field}' not found.")

# Ensure a clean "rainfall" field for analysis
if "rainfall" not in fields:
    arcpy.management.AddField(rain_points_3414_tmp, "rainfall", "DOUBLE")

# Populate "rainfall" from Rainfall__mm_hr_
with arcpy.da.UpdateCursor(
    rain_points_3414_tmp,
    [rain_src_field, "rainfall"]
) as cur:
    for old_rain, new_rain in cur:
        try:
            val = float(old_rain) if old_rain not in (None, "",) else 0.0
        except Exception:
            val = 0.0
        cur.updateRow((old_rain, val))

print("✅ STEP 5 completed – rainfall values standardized.\n")


# ============================================================
# STEP 6: CHECK RAINFALL STATUS (LATEST TIME + ANY > 0?)
# ============================================================
print("==================== STEP 6: CHECKING RAINFALL STATUS ====================")

max_ts = None        # latest timestamp (string from Reading_Time)
any_positive = False # whether any rainfall > 0 exists

with arcpy.da.SearchCursor(
    rain_points_3414_tmp,
    [time_src_field, "rainfall"]
) as cur:
    for ts, val in cur:
        # ts is text; skip empty
        if not ts:
            continue

        # Track latest timestamp as max string (ISO-like strings compare correctly)
        if (max_ts is None) or (ts > max_ts):
            max_ts = ts

        # Track any positive rainfall
        if val is not None and val > 0:
            any_positive = True

# Case A: No valid timestamps at all
if max_ts is None:
    print("[WARN] No valid Reading_Time values → using full comfort.")
    write_full_comfort()
    # Clean temp and exit
    for fc in [rain_points_wgs84_tmp, rain_points_3414_tmp]:
        if arcpy.Exists(fc):
            arcpy.management.Delete(fc)
    raise SystemExit(0)

# Case B: All rainfall <= 0
if not any_positive:
    print("[INFO] All rainfall <= 0 → full comfort.")
    write_full_comfort()
    # Clean temp and exit
    for fc in [rain_points_wgs84_tmp, rain_points_3414_tmp]:
        if arcpy.Exists(fc):
            arcpy.management.Delete(fc)
    raise SystemExit(0)

# If we reach here → there is rain and a valid latest timestamp
print(f"[INFO] Latest rainfall timestamp (text): {max_ts}")
print("[INFO] Positive rainfall detected → continue to IDW.\n")


# ============================================================
# STEP 7: FILTER POINTS TO LATEST TIMESTAMP
# ============================================================
print("==================== STEP 7: FILTERING LATEST TIMESTAMP ====================")

if arcpy.Exists(latest_lyr):
    arcpy.management.Delete(latest_lyr)

# time_src_field is text, so filter as string equality
where = f"{time_src_field} = '{max_ts}'"
arcpy.management.MakeFeatureLayer(
    in_features=rain_points_3414_tmp,
    out_layer=latest_lyr,
    where_clause=where
)

if int(arcpy.management.GetCount(latest_lyr)[0]) == 0:
    print("[WARN] No points found for latest timestamp → full comfort.")
    write_full_comfort()
    for fc in [rain_points_wgs84_tmp, rain_points_3414_tmp]:
        if arcpy.Exists(fc):
            arcpy.management.Delete(fc)
    raise SystemExit(0)

print("✅ STEP 7 completed – latest timestamp layer ready.\n")


# ============================================================
# STEP 8: CONFIGURE ENVIRONMENT
# ============================================================
print("==================== STEP 8: CONFIGURING ENVIRONMENT ====================")

arcpy.env.extent = sg_boundary_fc
arcpy.env.snapRaster = shelter_raster_path
arcpy.env.cellSize = 30

print("[INFO] Extent, snap raster, and cell size set.")
print("✅ STEP 8 completed.\n")


# ============================================================
# STEP 9: IDW INTERPOLATION
# ============================================================
print("==================== STEP 9: RUNNING IDW ====================")

idw_ras = Idw(
    in_point_features=latest_lyr,
    z_field="rainfall",
    cell_size=30,
    power=2
)

# Limit to Singapore boundary
idw_ras = ExtractByMask(idw_ras, sg_boundary_fc)

# Get min/max for normalization
arcpy.management.CalculateStatistics(idw_ras)
rmin = float(arcpy.management.GetRasterProperties(idw_ras, "MINIMUM").getOutput(0))
rmax = float(arcpy.management.GetRasterProperties(idw_ras, "MAXIMUM").getOutput(0))

if rmax <= rmin:
    print("[WARN] IDW has no variation → fallback to full comfort.")
    write_full_comfort()
    for fc in [rain_points_wgs84_tmp, rain_points_3414_tmp]:
        if arcpy.Exists(fc):
            arcpy.management.Delete(fc)
    raise SystemExit(0)

norm_rain = (idw_ras - rmin) / (rmax - rmin)
norm_rain = Con(IsNull(norm_rain), 0, norm_rain)

print(f"[INFO] IDW rainfall range: {rmin:.3f} – {rmax:.3f}")
print("✅ STEP 9 completed – rainfall normalized to 0–1.\n")


# ============================================================
# STEP 10: COMPUTE COMFORT SCORE
# ============================================================
print("==================== STEP 10: COMPUTING COMFORT SCORE ====================")

shelter = Raster(shelter_raster_path)
unsheltered = 1 - shelter  # 1 = exposed, 0 = sheltered

# Exposure = rain intensity * unsheltered
exposure = norm_rain * unsheltered
exposure = Con(exposure < 0, 0, Con(exposure > 1, 1, exposure))

# Comfort = (1 - exposure) * 100
comfort = (1 - exposure) * 100
comfort = Con(comfort < 0, 0, Con(comfort > 100, 100, comfort))

# Save final comfort raster (overwrite)
comfort.save(comfort_out)
print(f"[OK] Comfort score raster saved → {comfort_out}")

# Export GeoTIFF (overwrite)
arcpy.management.CopyRaster(
    in_raster=comfort_out,
    out_rasterdataset=tif_out,
    format="TIFF",
    nodata_value=0,
    pixel_type="32_BIT_FLOAT"
)
print(f"[OK] Comfort score GeoTIFF exported → {tif_out}")
print("✅ STEP 10 completed.\n")


# ============================================================
# STEP 11: FINAL CLEANUP
# ============================================================
print("==================== STEP 11: CLEANUP TEMP DATA ====================")

for obj in [latest_lyr, rain_points_wgs84_tmp, rain_points_3414_tmp]:
    if arcpy.Exists(obj):
        arcpy.management.Delete(obj)
        print(f"[CLEANUP] Deleted {obj}")

print("\n✅ ALL STEPS COMPLETED SUCCESSFULLY.")
print(f"📁 Final comfort raster : {comfort_out}")
print(f"📁 Final GeoTIFF        : {tif_out}")
print("============================================================\n")
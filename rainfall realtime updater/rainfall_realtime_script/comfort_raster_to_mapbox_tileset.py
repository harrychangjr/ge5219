# ============================================================
# raster_to_mapbox_tileset_svy21.py
#
# Purpose:
#   1. Read the latest comfort raster (GeoTIFF).
#   2. Normalize values to 0–255 and convert to 8-bit unsigned.
#   3. Reproject to SVY21 (EPSG:3414) for Mapbox (team standard).
#   4. Upload the processed GeoTIFF to Mapbox via Uploads API
#      and create / overwrite a raster tileset.
#
# Usage:
#   - Designed to be run repeatedly (e.g. every 15 minutes).
#   - Automatically deletes old outputs each run.
#
# Requirements:
#   - ArcGIS Pro + arcpy + Spatial Analyst
#   - Python packages: requests, boto3, botocore
#   - Environment variable: MAPBOX_TOKEN = your Mapbox access token
#
# Notes:
#   - Your group workflow uses SVY21 (EPSG:3414) for visualization,
#     so this script keeps that CRS for Mapbox upload.
# ============================================================

import os
import time
import requests
import arcpy
from arcpy.sa import *
import boto3
from botocore.exceptions import NoCredentialsError, ClientError

# ------------------------------------------------------------
# 0. ArcGIS environment setup
# ------------------------------------------------------------

arcpy.CheckOutExtension("Spatial")
arcpy.env.overwriteOutput = True

# Workspace for intermediate files
workspace_folder = r"C:\Users\zirui\Desktop\5219 final\rainfall realtime updater\output_data"
if not os.path.exists(workspace_folder):
    os.makedirs(workspace_folder)

arcpy.env.workspace = workspace_folder

# ------------------------------------------------------------
# 1. User-defined paths and settings
# ------------------------------------------------------------

# Input raster (updated by previous script)
input_raster = os.path.join(workspace_folder, "comfort_score_latest.tif")

# Expected comfort score range
input_min_value = 0.0
input_max_value = 100.0

# Output rasters
normalized_raster_8bit = os.path.join(workspace_folder, "comfort_8bit_raw.tif")
svy21_raster_8bit = os.path.join(workspace_folder, "comfort_8bit_3414.tif")

# Mapbox configuration
MAPBOX_USERNAME = "ziruizeng"
MAPBOX_TILESET_ID = f"{MAPBOX_USERNAME}.comfort_raster_svy21"
MAPBOX_UPLOAD_NAME = "Rainfall_Comfort_Raster_SVY21"
MAPBOX_TOKEN = "sk.eyJ1IjoiemlydWl6ZW5nIiwiYSI6ImNtaHAwZmhhdDBlaXUybHBndnE3ZjlnNGgifQ.DbSUUNnlEhzTHId7R3Hxsw"
# MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN")  # <- set this in system env (pk.ey...)

# ------------------------------------------------------------
# 2. Remove old outputs before starting
# ------------------------------------------------------------

for raster_path in [normalized_raster_8bit, svy21_raster_8bit]:
    if arcpy.Exists(raster_path):
        print(f"Removing previous output: {raster_path}")
        arcpy.management.Delete(raster_path)

# ------------------------------------------------------------
# 3. Step A – Normalize raster to 0–255 (8-bit unsigned)
# ------------------------------------------------------------

print("Step A: Normalizing raster to 0–255 and converting to 8-bit unsigned...")

if not arcpy.Exists(input_raster):
    raise FileNotFoundError(f"Input raster not found: {input_raster}")

# Load input raster
in_ras = Raster(input_raster)

# Compute normalization
value_range = float(input_max_value) - float(input_min_value)
if value_range == 0:
    raise ValueError("Input max and min values are equal; cannot normalize.")

norm_ras = (in_ras - input_min_value) / value_range
norm_ras = Con(norm_ras < 0, 0, norm_ras)
norm_ras = Con(norm_ras > 1, 1, norm_ras)
scaled_ras = norm_ras * 255
scaled_int = Int(scaled_ras)

# Save normalized raster in the source CRS
arcpy.management.CopyRaster(
    in_raster=scaled_int,
    out_rasterdataset=normalized_raster_8bit,
    pixel_type="8_BIT_UNSIGNED",
    format="TIFF",
    nodata_value=0
)

print(f"✅ Normalized 8-bit raster saved: {normalized_raster_8bit}")

# ------------------------------------------------------------
# 4. Step B – Project normalized raster to SVY21 (EPSG:3414)
# ------------------------------------------------------------

print("Step B: Projecting normalized raster to SVY21 (EPSG:3414)...")

sr_svy21 = arcpy.SpatialReference(3414)

# Project to SVY21
arcpy.management.ProjectRaster(
    in_raster=normalized_raster_8bit,
    out_raster=svy21_raster_8bit,
    out_coor_system=sr_svy21,
    resampling_type="BILINEAR"
)

print(f"✅ SVY21 8-bit raster saved: {svy21_raster_8bit}")

# ------------------------------------------------------------
# 5. Step C – Upload the SVY21 GeoTIFF to Mapbox
# ------------------------------------------------------------

if not MAPBOX_TOKEN:
    raise RuntimeError("MAPBOX_TOKEN not set. Please set it as an environment variable with your secret token.")

print("Step C: Requesting temporary S3 credentials from Mapbox...")

credentials_url = (
    f"https://api.mapbox.com/uploads/v1/{MAPBOX_USERNAME}/credentials"
    f"?access_token={MAPBOX_TOKEN}"
)
credentials_response = requests.post(credentials_url)

if not credentials_response.ok:
    raise RuntimeError(
        f"Failed to get upload credentials from Mapbox: "
        f"{credentials_response.status_code} {credentials_response.text}"
    )

credentials = credentials_response.json()

aws_access_key_id = credentials["accessKeyId"]
aws_secret_access_key = credentials["secretAccessKey"]
aws_session_token = credentials["sessionToken"]
aws_bucket = credentials["bucket"]
aws_key = credentials["key"]
staged_file_url = credentials["url"]  # <-- HTTPS URL Mapbox expects

print("✅ Temporary S3 credentials received. Uploading raster...")

s3_client = boto3.client(
    "s3",
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key,
    aws_session_token=aws_session_token,
    region_name="us-east-1"
)

try:
    # Upload local GeoTIFF to the exact bucket/key given by Mapbox
    s3_client.upload_file(svy21_raster_8bit, aws_bucket, aws_key)
    print("✅ GeoTIFF uploaded to S3 staging bucket.")
except FileNotFoundError:
    raise RuntimeError("SVY21 raster not found. Check svy21_raster_8bit path.")
except (NoCredentialsError, ClientError) as e:
    raise RuntimeError(f"AWS upload error: {e}")

print("Creating Mapbox upload job (GeoTIFF → raster tileset)...")

uploads_url = f"https://api.mapbox.com/uploads/v1/{MAPBOX_USERNAME}?access_token={MAPBOX_TOKEN}"

upload_payload = {
    "url": staged_file_url,       # <-- use HTTPS URL from credentials, NOT s3://
    "tileset": MAPBOX_TILESET_ID,
    "name": MAPBOX_UPLOAD_NAME
}

upload_response = requests.post(uploads_url, json=upload_payload)

if not upload_response.ok:
    raise RuntimeError(
        f"Failed to create Mapbox upload: "
        f"{upload_response.status_code} {upload_response.text}"
    )

upload_info = upload_response.json()
upload_id = upload_info.get("id")
if not upload_id:
    raise RuntimeError(f"No upload ID returned from Mapbox: {upload_info}")

print(f"✅ Upload job created. Upload ID: {upload_id}")

# ------------------------------------------------------------
# 6. Step D – Poll Mapbox processing status
# ------------------------------------------------------------

print("Step D: Checking Mapbox processing status...")

status_url = (
    f"https://api.mapbox.com/uploads/v1/{MAPBOX_USERNAME}/{upload_id}"
    f"?access_token={MAPBOX_TOKEN}"
)

for attempt in range(15):
    status_response = requests.get(status_url)

    if not status_response.ok:
        print(f"⚠ Failed to fetch upload status: {status_response.text}")
        break

    status = status_response.json()

    if status.get("complete") is True:
        print("🎉 Mapbox tileset processing completed successfully.")
        print(f"Tileset ID: {MAPBOX_TILESET_ID}")
        break

    if status.get("error"):
        raise RuntimeError(f"Mapbox processing error: {status['error']}")

    print(f"Processing... attempt {attempt + 1}/15")
    time.sleep(10)

else:
    print("ℹ Mapbox is still processing. Check tileset in Mapbox Studio.")

print("✅ All steps completed.")

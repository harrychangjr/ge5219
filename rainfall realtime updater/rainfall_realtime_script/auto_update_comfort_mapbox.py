# ============================================================
# auto_update_comfort_mapbox.py
#
# One-stop pipeline for Rainfall Comfort Score (Singapore)
#
# What this script does:
#   1. Calls "fetch_latest_rainfall_to_csv.py" to:
#        - Fetch latest rainfall data from data.gov.sg
#        - Save a clean CSV (and GeoJSON) to output folder
#
#   2. Calls "from_csv_to_comfort.py" to:
#        - Read the latest rainfall CSV
#        - Generate a comfort score raster in ArcGIS Pro project GDB
#        - Export "comfort_score_latest.tif" into the output folder
#
#   3. Normalizes "comfort_score_latest.tif" to 8-bit (0–255):
#        - This makes the raster suitable and compact for Mapbox tiling
#
#   4. Uploads the 8-bit raster to Mapbox as a tileset:
#        - Tileset ID: ziruizeng.comfort_raster_svy21
#        - Uses Mapbox Uploads API via the official Python SDK (mapbox.Uploader)
#        - Overwrites/updates the existing tileset used in Mapbox style
#
# Result:
#   - Embedded Mapbox map (iframe using style cmhq60a9600n601sdc1oh5nwc)
#     will automatically display the updated comfort raster,
#     while KEEPING the same zoom, center, and opacity settings in the style.
#
# Requirements:
#   - Run with ArcGIS Pro Python environment (ge5219) that has arcpy + Spatial Analyst.
#   - Install "mapbox" library in that environment:
#       C:/Users/zirui/AppData/Local/ESRI/conda/envs/ge5219/python.exe -m pip install mapbox
#   - MUST use a Mapbox secret access token (sk-...) with "uploads:write" permission.
#

# ============================================================

import os
import json
import subprocess

import arcpy
from arcpy.sa import *

from mapbox import Uploader  # Provided by "mapbox" Python package


# ------------------------------------------------------------
# 0. USER CONFIGURATION (EDIT THESE PARTS IF NEEDED)
# ------------------------------------------------------------

# Base directory for rainfall pipeline project
BASE_DIR = r"C:\Users\zirui\Desktop\5219 final\rainfall realtime updater"

# Directory where Python scripts are stored
SCRIPT_DIR = os.path.join(BASE_DIR, "rainfall_realtime_script")

# Directory where outputs (CSV, GeoTIFF, etc.) will be written
OUTPUT_DIR = os.path.join(BASE_DIR, "output_data")

# Input comfort raster produced by from_csv_to_comfort.py
INPUT_TIF = os.path.join(OUTPUT_DIR, "comfort_score_latest.tif")

# Output 8-bit raster (this is the file that will be uploaded to Mapbox)
OUTPUT_8BIT = os.path.join(OUTPUT_DIR, "comfort_score_8bit_3414.tif")

# Expected value range of comfort score model
# (0 = worst comfort, 100 = best comfort)
COMFORT_MIN = 0.0
COMFORT_MAX = 100.0

# Mapbox account username
MAPBOX_USERNAME = "ziruizeng"

# Target tileset ID that existing Mapbox style is already using
# IMPORTANT:
#   - This must match exactly the tileset referenced in style
MAPBOX_TILESET_ID = "ziruizeng.comfort_raster_svy21"

# Mapbox secret token with "uploads:write" permission
# DO NOT use public (pk...) token here.
# DO NOT expose the real token publicly (keep it local / private).
MAPBOX_ACCESS_TOKEN = "sk.eyJ1IjoiemlydWl6ZW5nIiwiYSI6ImNtaHJxbms0cTEwbmkyaXF5ZGpjeXY5YWoifQ.dDAnQCfkPEqBuEU5KJ-8Pw"

# A readable name for the upload job (shown in Mapbox Studio)
MAPBOX_UPLOAD_NAME = "Rainfall Comfort Score Auto Updated"

# Path to the Python interpreter of ArcGIS Pro / ge5219 environment
PYTHON_EXE = r"C:/Users/zirui/AppData/Local/ESRI/conda/envs/ge5219/python.exe"


# ------------------------------------------------------------
# 1. ARCPY / ENVIRONMENT SETUP
# ------------------------------------------------------------

# Enable Spatial Analyst extension (required for raster operations)
arcpy.CheckOutExtension("Spatial")

# Allow overwriting outputs without manual deletion each run
arcpy.env.overwriteOutput = True

# Set default workspace to output directory for convenience
arcpy.env.workspace = OUTPUT_DIR

# for consistently updating and printing out the running status
def log(message: str) -> None:
    """
    Simple logger for consistent tagged console output.
    """
    print(f"[AUTO UPDATE] {message}")


# ------------------------------------------------------------
# 2. STEP 1 – FETCH LATEST RAINFALL DATA
# ------------------------------------------------------------

# call the script to fetch latest rainfall data
def fetch_latest_rainfall() -> None:
    """
    Run the standalone script "fetch_latest_rainfall_to_csv.py".

    This will:
      - Call NEA / data.gov.sg rainfall API.
      - Generate rainfall_latest.csv (and rainfall_latest.geojson if --geojson is used).
      - Overwrite previous outputs in OUTPUT_DIR.
    """
    log("Fetching latest rainfall data from data.gov.sg...")

    fetch_script = os.path.join(SCRIPT_DIR, "fetch_latest_rainfall_to_csv.py")

    # Construct the command to run the script using the ge5219 Python interpreter
    cmd = [
        PYTHON_EXE,
        fetch_script,
        "--out_dir", OUTPUT_DIR,
        "--geojson",        # Also produce a GeoJSON for inspection (optional but useful)
    ]

    # Run the command and raise an error if it fails
    subprocess.run(cmd, check=True)

    log("Rainfall data fetched successfully.")


# ------------------------------------------------------------
# 3. STEP 2 – GENERATE COMFORT RASTER
# ------------------------------------------------------------
# call the sub-script to generate comfort raster
def generate_comfort_raster() -> None:
    """
    Run the script "from_csv_to_comfort.py".

    This script is expected to:
      - Read rainfall_latest.csv from OUTPUT_DIR.
      - Create an IDW (or rule-based) comfort score raster in GDB.
      - Export a GeoTIFF: comfort_score_latest.tif into OUTPUT_DIR.

    This function assumes that:
      - "from_csv_to_comfort.py" already implements that full pipeline.
    """
    log("Generating comfort raster from latest rainfall CSV...")

    comfort_script = os.path.join(SCRIPT_DIR, "from_csv_to_comfort.py")

    cmd = [
        PYTHON_EXE,
        comfort_script,
    ]

    subprocess.run(cmd, check=True)

    # At this point, INPUT_TIF should exist.
    log("Comfort raster generated successfully.")


# ------------------------------------------------------------
# 4. STEP 3 – NORMALIZE COMFORT RASTER TO 8-BIT
# ------------------------------------------------------------

# call the sub-script to normalized the comfort raster into Mapbox upload-ready 8-bit raster
def normalize_to_8bit() -> str:
    """
    Normalize "comfort_score_latest.tif" into an 8-bit (0–255) GeoTIFF.

    Why:
      - Mapbox raster tilesets typically use 8-bit or 16-bit rasters.
      - Converting to 8-bit keeps the file small and efficient.
      - Values are linearly mapped from [COMFORT_MIN, COMFORT_MAX] to [0, 255].

    Returns:
      - The file path to the 8-bit output raster (OUTPUT_8BIT).
    """
    log("Normalizing comfort raster to 8-bit for Mapbox tiling...")

    # Ensure the input raster exists
    if not arcpy.Exists(INPUT_TIF):
        raise FileNotFoundError(
            f"Input comfort raster not found: {INPUT_TIF}\n"
            f"Make sure from_csv_to_comfort.py completed successfully."
        )

    # If an old 8-bit raster exists, delete it to avoid conflicts
    if arcpy.Exists(OUTPUT_8BIT):
        arcpy.management.Delete(OUTPUT_8BIT)

    # Load the comfort raster
    in_ras = Raster(INPUT_TIF)

    # Validate range configuration
    value_range = COMFORT_MAX - COMFORT_MIN
    if value_range <= 0:
        raise ValueError("Invalid COMFORT_MIN / COMFORT_MAX range for normalization.")

    # Step 1: Normalize raw values to [0, 1]
    norm = (in_ras - COMFORT_MIN) / value_range

    # Step 2: Clamp values to [0, 1]
    norm = Con(norm < 0, 0, norm)
    norm = Con(norm > 1, 1, norm)

    # Step 3: Scale to [0, 255] and cast to integer (8-bit)
    scaled = norm * 255
    scaled_int = Int(scaled)

    # Step 4: Save as 8-bit unsigned GeoTIFF
    arcpy.management.CopyRaster(
        in_raster=scaled_int,
        out_rasterdataset=OUTPUT_8BIT,
        pixel_type="8_BIT_UNSIGNED",
        format="TIFF",
        nodata_value=0  # 0 can represent "no data" or "full comfort background" as you define
    )

    log(f"8-bit raster created: {OUTPUT_8BIT}")
    return OUTPUT_8BIT


# ------------------------------------------------------------
# 5. STEP 4 – UPLOAD 8-BIT RASTER TO MAPBOX
# ------------------------------------------------------------

# call the script to upload the raster
def upload_to_mapbox(file_path: str) -> dict:
    """
    Upload the given raster file to Mapbox as a tileset.

    Uses:
      - Mapbox Python SDK's Uploader class.
      - This internally:
          1. Requests temporary S3 credentials.
          2. Uploads the file to S3.
          3. Creates an Uploads API job to build/update the tileset.

    Behavior:
      - If MAPBOX_TILESET_ID already exists:
          → The upload will update that tileset with new data.
      -  style (cmhq60a9600n601sdc1oh5nwc) should already reference this tileset,
        so it will display the new raster automatically once processing is done.

    Returns:
      - The JSON response from Mapbox Uploads API (for logging/debugging).
    """
    log("Uploading 8-bit raster to Mapbox tileset...")

    # Initialize the Uploader with secret access token
    uploader = Uploader(access_token=MAPBOX_ACCESS_TOKEN)

    # Open the raster file in binary mode
    with open(file_path, "rb") as src:
        response = uploader.upload(
            src,
            tileset=MAPBOX_TILESET_ID,
            name=MAPBOX_UPLOAD_NAME
        )

    # Check if the upload request was accepted
    if response.status_code != 201:
        # If something went wrong, include response text for debugging
        raise RuntimeError(
            f"Mapbox upload failed "
            f"(HTTP {response.status_code}): {response.text}"
        )

    info = response.json()

    # Log some key info from the response
    log(f"Mapbox upload started for tileset: {MAPBOX_TILESET_ID}")
    log(json.dumps(info, indent=2))

    return info


# ------------------------------------------------------------
# 6. MAIN – ORCHESTRATE THE FULL PIPELINE
# ------------------------------------------------------------

def main() -> None:
    """
    Orchestrate the full end-to-end pipeline:

      1. Fetch latest rainfall observations.
      2. Build the latest comfort score raster.
      3. Normalize to an 8-bit GeoTIFF.
      4. Upload the raster to Mapbox and update the tileset.

    Notes:
      - This script does NOT modify Mapbox style.
      - The iframe settings (center, zoom, opacity) stay exactly
        as configured in the style / embed URL.
      - Only the underlying tileset data is refreshed.
    """
    # Step 1: Update rainfall input
    fetch_latest_rainfall()

    # Step 2: Generate new comfort raster based on latest rainfall
    generate_comfort_raster()

    # Step 3: Convert to 8-bit raster for efficient Mapbox upload
    raster_8bit_path = normalize_to_8bit()

    # Step 4: Push the new raster to Mapbox tileset
    upload_to_mapbox(raster_8bit_path)

    log("Pipeline completed. Mapbox tileset updated with latest comfort surface.")


# ------------------------------------------------------------
# 7. SCRIPT ENTRY POINT
# ------------------------------------------------------------

if __name__ == "__main__":
    main()
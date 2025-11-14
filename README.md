# SG Rainfall Realtime → CSV (for Mapbox / ArcGIS / Anything)
Objective: 

1. Run the main controller script "auto_update_comfort_mapbox.py" to finish the whole rainfall dashboard pipeline. 

 (a) It starts from set up the arcpy and environment; The output from previous runs will be overwrited once start the new run.
 (b) Later it calls the script "fetch_latest_rainfall()" to automatically retrieve the real-time rainfall api data from data.gov.sg (v1 API), and export a clean CSV (optionally GeoJSON). The output CSV will be named as "rainfall_latest.csv"
 (c) It calls the function "generate_comfort_raster()", and use the data in the latest rainfall .csv file to generate the rainfall comfort score raster;
 (d) To fit the upload format in Mapbox, "normalize_to_8bit()" will be called for converting the rainfall comfort score raster to Mapbox-ready 8bit TIFF
 (e) To finalized the upload, "upload_to_mapbox()" will be called, for refreshing/uploading the comfort score TIFF onto mapbox dashboard. The linked google site dashboard refreshes the latest map as well, while the delay on syncing on Google site-end dashboard may limit the instant view of rainfall comfort score.

To further break down the workflow, this readme file will go through the sub-scripts which called by main controller script "auto_update_comfort_mapbox.py".

The main controller script will automatically call the sub-scripts in this quence: 
    (1) fetch_latest_rainfall_to_csv.py; -> for convert the API raw data into csv file
        by running the function "fetch_latest_rainfall()"
    (2) from csv_to_comfort.py; -> convert the csv file into comfort score raster
        by running the function "generate_comfort_raster()"
    (2) comfort_raster_to_mapbox.py. -> upload the comfort score raster into Mapbox, for or synchronization with the Google Site
        by running the function "normalize_to_8bit()" and "upload_to_mapbox()"

---
## Installation & Environment

This project requires:
- ArcGIS Pro (with arcpy available in Python environment)
- Python 3.11 (ESRI default)
- Requests
- Pandas
- GDAL (optional, only needed if raster operations are done outside arcpy)

To activate the correct environment:
conda activate ge5219

## Repository layout
This project contains the full end-to-end pipeline for generating and auto-uploading the Singapore Rainfall Comfort Score to Mapbox.  
Runtime outputs and Python cache folders are separated from the main scripts.

```text
/`<project_root>`
│
├── README.md                       ← Project documentation
│
├── rainfall_realtime_script/       ← All Python scripts for the pipeline
│     ├── auto_update_comfort_mapbox.py          ← Main controller (one-click run)
│     ├── fetch_latest_rainfall_to_csv.py        ← Fetch real-time rainfall API
│     ├── from_csv_to_comfort.py                 ← Generate comfort raster (ArcGIS)
│     ├── comfort_raster_to_mapbox_tileset.py    ← Normalize & prep for Mapbox upload
│     └── __pycache__/                           ← Auto-generated Python bytecode (ignored)
│
└── output_data/                    ← Automatically generated outputs 
      ├── rainfall_latest.csv
      ├── comfort_score_latest.tif
      └── comfort_score_8bit_3414.tif
```


## Configuration

Before running the pipeline, update the following variables inside  
`auto_update_comfort_mapbox.py` and `from_csv_to_comfort.py` to match your local setup.

### Mapbox settings
MAPBOX_TOKEN       = "your-secret-mapbox-token"
TILESET_ID         = "ziruizeng.comfort_raster_svy21"

### Local ArcGIS paths (my local machine)
ARCGIS_GDB         = r"C:\Users\zirui\Documents\ArcGIS\Projects\rainfall_pipeline\rainfall_pipeline.gdb"

# Singapore boundary (SVY21)
SG_BOUNDARY_FC     = r"C:\Users\zirui\Documents\ArcGIS\Projects\rainfall_pipeline\rainfall_pipeline.gdb\sg_boundary_3414"

# 30 m buffered sheltered linkways (0/1 raster)
SHELTER_RASTER     = r"C:\Users\zirui\Documents\ArcGIS\Projects\rainfall_pipeline\rainfall_pipeline.gdb\shelter_01_30m"

### Output directory
OUTPUT_DIR         = r"C:\Users\zirui\Desktop\5219 final\rainfall realtime updater\output_data"


## How to Run
## How to Run (on my local setup)

> Note: The scripts are wired to my local ArcGIS Pro project and data folders.
> The geodatabase and shelter rasters are not included in this repo due to size
> and licensing, so the exact paths below are specific to my machine.

1. Activate the ArcGIS Pro Python environment:

   ```bash
   conda activate ge5219

2. Navigate to project folder:
cd "C:\Users\zirui\Desktop\5219 final\rainfall realtime updater\rainfall_realtime_script"
3. run: 
python auto_update_comfort_mapbox.py

## Example output 
output_data/
  ├─ rainfall_latest.csv
  ├─ comfort_score_2025_11_14_1530.tif
  ├─ comfort_score_2025_11_14_1530_8bit.tif

### Troubleshooting
- If Mapbox tileset updates but Google Site does not refresh:
  → Google Sites caches iframe tiles for 5–10 minutes.
  → Try adding `&fresh=true` to the iframe URL.

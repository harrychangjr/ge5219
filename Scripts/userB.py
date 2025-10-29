import arcpy
print("ArcGIS version:", arcpy.GetInstallInfo()["Version"]) #to verify arcpy is working
import requests
import os

# Set up environment
print("Script file:", os.path.abspath(__file__))
print("Current working directory:", os.getcwd())
arcpy.env.overwriteOutput = True
script_dir = os.path.dirname(os.path.abspath(__file__))

#### Set working directory
temperature_dir = os.path.abspath(os.path.join(script_dir, "..", "Data", "temperature"))
os.makedirs(temperature_dir, exist_ok=True)
print("Saving to:", temperature_dir)

#### 1. Process NEA Temperature & Humidity datasets
spatial_ref = arcpy.SpatialReference(3414)  # SVY21
## Import temperature data
temperature_url = "https://api-open.data.gov.sg/v2/real-time/api/air-temperature"
temperature_header = {"X-Api-Key": "v2:4e6365a415445397c22f95f316915fb26f7fef84f03a460fc4979df0622f3d52:YCW8iU4aw9ftZ8qTNFDgOhtlVfKESyaP"}
temperature_response = requests.get(temperature_url, headers=temperature_header)
print(temperature_response.json())
temperature_data = temperature_response.json()
## Convert temperature data to shapefile
# Set temperature output directory
temperature_dir = os.path.abspath(os.path.join(script_dir, "..", "Data", "temperature"))
os.makedirs(temperature_dir, exist_ok=True)
# Define output shapefile path
temperature_fc = "air_temperature"
temperature_path = os.path.join(temperature_dir, temperature_fc + ".shp")
# Create shapefile
arcpy.CreateFeatureclass_management(out_path=temperature_dir,
                                    out_name=temperature_fc,
                                    geometry_type="POINT",
                                    spatial_reference=spatial_ref)
# Add fields to shapefile
arcpy.AddField_management(temperature_path, "stn_id", "TEXT")
arcpy.AddField_management(temperature_path, "stn_name", "TEXT")
arcpy.AddField_management(temperature_path, "temp", "FLOAT")
# Parse JSON data
temperature_readings = {r['stationId']: r['value'] for r in temperature_data['data']['readings'][0]['data']}
# Insert rows
with arcpy.da.InsertCursor(temperature_path, ["SHAPE@XY", "stn_id", "stn_name", "temp"]) as cursor:
    for s in temperature_data['data']['stations']:
        stn_id = s['id']
        stn_name = s['name']
        lon = s['location']['longitude']
        lat = s['location']['latitude']
        temp = temperature_readings.get(stn_id, None)
        cursor.insertRow(((lon, lat), stn_id, stn_name, temp))

print(arcpy.GetMessages())
print("Temperature shapefile created:", os.path.abspath(temperature_path))

## Import relative humidity data
# Get data from NEA API
rh_url = "https://api-open.data.gov.sg/v2/real-time/api/relative-humidity"
rh_header = {"X-Api-Key": "v2:4e6365a415445397c22f95f316915fb26f7fef84f03a460fc4979df0622f3d52:YCW8iU4aw9ftZ8qTNFDgOhtlVfKESyaP"}
rh_response = requests.get(rh_url, headers=rh_header)
print(rh_response.json())
rh_data = rh_response.json()

# Set RH output directory
rh_dir = os.path.abspath(os.path.join(script_dir, "..", "Data", "relative_humidity"))
os.makedirs(rh_dir, exist_ok=True)
# Define output shapefile path
rh_fc = "relative_humidity"
temperature_path = os.path.join(temperature_dir, temperature_fc + ".shp")
# Create shapefile
arcpy.CreateFeatureclass_management(out_path=temperature_dir,
                                    out_name=temperature_fc,
                                    geometry_type="POINT",
                                    spatial_reference=spatial_ref)
# Add fields to shapefile
arcpy.AddField_management(temperature_path, "stn_id", "TEXT")
arcpy.AddField_management(temperature_path, "stn_name", "TEXT")
arcpy.AddField_management(temperature_path, "temp", "FLOAT")
# Parse JSON data
temperature_readings = {r['stationId']: r['value'] for r in temperature_data['data']['readings'][0]['data']}
# Insert rows
with arcpy.da.InsertCursor(temperature_path, ["SHAPE@XY", "stn_id", "stn_name", "temp"]) as cursor:
    for s in temperature_data['data']['stations']:
        stn_id = s['id']
        stn_name = s['name']
        lon = s['location']['longitude']
        lat = s['location']['latitude']
        temp = temperature_readings.get(stn_id, None)
        cursor.insertRow(((lon, lat), stn_id, stn_name, temp))

print(arcpy.GetMessages())
print("Temperature shapefile created:", os.path.abspath(temperature_path))



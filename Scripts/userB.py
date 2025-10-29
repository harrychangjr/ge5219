import arcpy
print("ArcGIS version:", arcpy.GetInstallInfo()["Version"]) #to verify arcpy is working
import requests
import os

#Get current working directory 
print("Script file:", os.path.abspath(__file__))
print("Current working directory:", os.getcwd())

#### Set working directory
script_dir = os.path.dirname(os.path.abspath(__file__))
project_dir = os.path.abspath(os.path.join(script_dir, "..", "Data", "temperature"))
os.makedirs(project_dir, exist_ok=True)
print("Saving to:", project_dir)

arcpy.env.workspace = project_dir
arcpy.env.overwriteOutput = True
#### 1. Process NEA Temperature & Humidity datasets
spatial_ref = arcpy.SpatialReference(3414)  # SVY21
## Import temperature data
temperature_url = "https://api-open.data.gov.sg/v2/real-time/api/air-temperature"
temperature_header = {"X-Api-Key": "v2:4e6365a415445397c22f95f316915fb26f7fef84f03a460fc4979df0622f3d52:YCW8iU4aw9ftZ8qTNFDgOhtlVfKESyaP"}
temperature_response = requests.get(temperature_url, headers=temperature_header)
print(temperature_response.json())
temperature_data = temperature_response.json()
## Convert temperature data to shapefile
output_folder = project_dir
output_folder = os.path.abspath(output_folder)
os.makedirs(output_folder, exist_ok=True)
print("Saving shapefile to:", output_folder)

temperature_fc = "air_temperature"
temperature_path = os.path.join(output_folder, temperature_fc + ".shp")
# Create shapefile
arcpy.CreateFeatureclass_management(out_path=output_folder,
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






import arcpy
print("ArcGIS version:", arcpy.GetInstallInfo()["Version"])
import os
import requests
import geopandas as gpd
from shapely.geometry import Point
arcpy.env.overwriteOutput = True

############### Obtain data & create shapefiles from NEA realtime API ###############
### Create function to create shapefiles from NEA JSON realtime data
def create_shapefile(data, value_field, out_folder, out_name, spatial_ref):
    os.makedirs(out_folder, exist_ok=True)
    out_path = os.path.join(out_folder, out_name + ".shp")
    arcpy.CreateFeatureclass_management(out_path = out_folder,
                                        out_name = out_name,
                                        geometry_type = "POINT",
                                        spatial_reference = spatial_ref)
    arcpy.AddField_management(out_path, "stn_id", "TEXT")
    arcpy.AddField_management(out_path, "stn_name", "TEXT")
    arcpy.AddField_management(out_path, value_field, "FLOAT")
    with arcpy.da.InsertCursor(out_path, ["SHAPE@XY", "stn_id", "stn_name", value_field]) as cursor:
        for s in data:
            cursor.insertRow(((s['longitude'], s['latitude']),
                              s['id'], s['name'], s['value']))
    return out_path

# Set spatial reference to SVY21
spatial_ref = arcpy.SpatialReference(3414)

#Link to data folder
script_dir = os.path.dirname(os.path.abspath(__file__))
data_folder = os.path.abspath(os.path.join(script_dir, "..", "Data"))

## Import temperature data
temperature_url = "https://api-open.data.gov.sg/v2/real-time/api/air-temperature"
temperature_header = {"X-Api-Key": "v2:4e6365a415445397c22f95f316915fb26f7fef84f03a460fc4979df0622f3d52:YCW8iU4aw9ftZ8qTNFDgOhtlVfKESyaP"}
temperature_response = requests.get(temperature_url, headers=temperature_header)
print(temperature_response.json())
temperature_data = temperature_response.json()

# Create temperature point data
temp_points = []
for s in temperature_data['data']['stations']:
    stn_id = s['id']
    stn_name = s['name']
    lon = s['location']['longitude']
    lat = s['location']['latitude']
    temp = next((r['value'] for r in temperature_data['data']['readings'][0]['data'] if r['stationId']==stn_id), None)
    temp_points.append({'id': stn_id, 'name': stn_name, 'longitude': lon, 'latitude': lat, 'value': temp})
print(temp_points)

# Create geopandas DataFrame for temperature
temp_gdf = gpd.GeoDataFrame(
    temp_points,
    geometry=[Point(p['longitude'], p['latitude']) for p in temp_points],
    crs="EPSG:4326"  # WGS84 lat/lon
)
temp_gdf = temp_gdf.to_crs(epsg=3414)  # Convert to SVY21
print(temp_gdf.head())

# Save temperature points to shapefile
temp_dir = os.path.join(data_folder, "temperature")
temp_shp = create_shapefile(temp_points, "temp", temp_dir, "air_temperature", spatial_ref)
print("Temperature shapefile created:", os.path.abspath(temp_shp))

## Import relative humidity data
rh_url = "https://api-open.data.gov.sg/v2/real-time/api/relative-humidity"
rh_header = {"X-Api-Key": "v2:4e6365a415445397c22f95f316915fb26f7fef84f03a460fc4979df0622f3d52:YCW8iU4aw9ftZ8qTNFDgOhtlVfKESyaP"}
rh_response = requests.get(rh_url, headers=rh_header)
print(rh_response.json())
rh_data = rh_response.json()

# Create relative humidity point data
rh_points = []
for s in rh_data['data']['stations']:
    stn_id = s['id']
    stn_name = s['name']
    lon = s['location']['longitude']
    lat = s['location']['latitude']
    rh = next((r['value'] for r in rh_data['data']['readings'][0]['data'] if r['stationId']==stn_id), None)
    rh_points.append({'id': stn_id, 'name': stn_name, 'longitude': lon, 'latitude': lat, 'value': rh})
print(rh_points)

# Create geopandas DataFrame for relative humidity
rh_gdf = gpd.GeoDataFrame(
    rh_points,
    geometry=[Point(p['longitude'], p['latitude']) for p in rh_points],
    crs="EPSG:4326"  # WGS84 lat/lon
)
rh_gdf = rh_gdf.to_crs(epsg=3414)  # Convert to SVY21
print(rh_gdf.head())

# Save relative humidity points to shapefile
rh_dir = os.path.join(data_folder, "relative_humidity")
rh_shp = create_shapefile(rh_points, "rh", rh_dir, "relative_humidity", spatial_ref)
print("Relative humidity shapefile created:", os.path.abspath(rh_shp))

############### Generate continuous rasters ###############
# Link to Singapore boundary shapefile used for clipping and masking rasters
singapore_boundary = os.path.join(data_folder, "planning_area_boundary", "planning_area_boundary.shp")
if arcpy.Exists(singapore_boundary):
    print("Shapefile is ready to use.")
else:
    print("Shapefile not found — check the path.")
print("Singapore boundary path:", singapore_boundary)
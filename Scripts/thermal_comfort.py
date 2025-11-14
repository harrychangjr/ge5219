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
import boto3
import json
print("done importing packages")

####### Configuration #######
mapbox_username = "username" #replace with actual mapbox username
dataset_name = "nea_points"
mapbox_access_token = "mapbox_access_token" #replace with actual mapbox access token

script_dir = os.getcwd() # Get path for script file
data_folder = os.path.join(script_dir, "Data") # Set relative path for the data folder
thermal_comfort_folder = os.path.join(data_folder, "thermal_comfort") # Create a new folder called "web" within the data folder 
os.makedirs(thermal_comfort_folder, exist_ok=True)

# Load Singapore boundary shapefile
boundary_shp = os.path.join(
    data_folder, "planning_area_boundary", "planning_area_boundary.shp"
)
# Notify whether the shapefile was found and loaded in or not
if not os.path.exists(boundary_shp):
    raise FileNotFoundError(f"Singapore boundary not found at {boundary_shp}")
else:
    print("Found Singapore boundary shapefile:", os.path.normpath(boundary_shp))

# Define output paths
temp_ras = os.path.join(thermal_comfort_folder, "temperature_svy21.tif")
rh_ras = os.path.join(thermal_comfort_folder, "humidity_svy21.tif")
humidex_ras = os.path.join(thermal_comfort_folder, "humidex_svy21.tif")
humidex_ras_norm = os.path.splitext(humidex_ras)[0] + "_norm.tif"
points_geojson = os.path.join(thermal_comfort_folder, "nea_environment_points.geojson")

# Set raster parameters
SVY21_EPSG = 3414 # SVY21
CELL_SIZE = 100 # metres
IDW_POWER = 2

######## Create various functions ##########

# Get RH and temp data through NEA API
def fetch_weather_data():
    temp_url = "https://api.data.gov.sg/v1/environment/air-temperature"
    rh_url   = "https://api.data.gov.sg/v1/environment/relative-humidity"
    temp = requests.get(temp_url, timeout=30).json()
    rh   = requests.get(rh_url, timeout=30).json()
    return temp, rh

# Create a GeoDataFrame using the lat/long provided in the data returned by the API
def build_geodataframe(temp_json, rh_json): #function takes the outputs from the NEA API results
    #extract readings from temp and RH data
    temp_items = temp_json["items"][0]["readings"] 
    rh_items   = rh_json["items"][0]["readings"]
    #build dictionary for temp and rh
    temp_by_id = {r["station_id"]: r["value"] for r in temp_items}
    rh_by_id   = {r["station_id"]: r["value"] for r in rh_items}

    stations = temp_json["metadata"]["stations"] #get metadata from the temperature result. Since temp and rh share the same stations, just temp_json is used.
    stn_rows = [] #start empty list where dictionary items will be input into
    #create loop for looking at each station metadata entry
    for s in stations: 
        sid = s["id"] #station ID
        T = temp_by_id.get(sid) #temperature value for corresponding station ID
        RH = rh_by_id.get(sid) #rh value for corresponding station id
        #skip stations where no temp or rh data is available
        if T is None or RH is None:
            continue
        #add the results to the empty list that was created
        stn_rows.append(
            {
                "station_id": sid,
                "T": float(T),
                "RH": float(RH),
                "geometry": Point(s["location"]["longitude"], s["location"]["latitude"]),
            }
        )
    weather = gpd.GeoDataFrame(stn_rows, crs="EPSG:4326") #make the geodataframe using weather station data
    weather = weather.to_crs(epsg=SVY21_EPSG) #reproject to SVY21
    return weather

#Create a raster grid that the IDW raster will be interpolated to
def make_grid(bounds, cell): 
    xmin, ymin, xmax, ymax = bounds #create bounds based on a given extent
    #create evently-spaced coordinate values along the x and y axis based on extent and specified cell size
    xs = np.arange(xmin, xmax + cell, cell)
    ys = np.arange(ymin, ymax + cell, cell)
    #generate full coordinate grid
    xi, yi = np.meshgrid(xs, ys)
    return xs, ys, xi, yi

#Perform IDW interpolation on station points 
def idw_interpolate(points_gdf, field, boundary_gdf, cell=CELL_SIZE, power=IDW_POWER): 
   #get x and y points from a geodataframe (the stations)
    x = points_gdf.geometry.x.values 
    y = points_gdf.geometry.y.values
    #get the rh or temperature value
    z = points_gdf[field].values
    #use the previous function to create the idw raster grid output using the singapore boundary shapefile and specified cell size 
    xs, ys, xi, yi = make_grid(boundary_gdf.total_bounds, cell) 

    #flattens the 2D grid arrays into 1D arrays of coordinate pairs for numpy
    xi_flat, yi_flat = xi.ravel(), yi.ravel()
    xi_b = xi_flat[:, None]
    yi_b = yi_flat[:, None]

    # compute the idw 
    dist2 = (xi_b - x)**2 + (yi_b - y)**2 #calculate squared distance from every grid point to every data point (from station gdf)
    dist2[dist2 == 0] = 1e-10 #replace 0 with a very small value to prevent division by 0 errors in case a grid point is directly above a data point
    weights = 1.0 / dist2**(power / 2) #use the idw formula for weight by distance (less weight for bigger distance)
    wsum = np.sum(weights, axis=1) #sum of all weights for each grid cell (denominator)
    zsum = np.sum(weights * z, axis=1) #sum of (weight × value) for each grid cell (numerator)
    zi = zsum / wsum #calculate interpolated value
    zi = zi.reshape(xi.shape).astype("float32") #converts 1D array of interpolated values back to 2D grid format

    transform = from_origin(xs[0], ys[-1] + cell, cell, cell) #tell rasterio how to georeference the grid
    return zi, transform

# save the interpolated rasters and mask and clip it to singapore boundary again (safety precaution)
def save_and_clip_raster(array2d, transform, crs_epsg, boundary_gdf, out_path):
    # save a temporary unclipped and unmasked raster 
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

    # crop and mask the raster
    with rasterio.open(temp_path) as src:
        if boundary_gdf.crs != src.crs: #ensure boundary and idw raster crs match
            boundary_gdf = boundary_gdf.to_crs(src.crs) #if it doesnt then reproject
        geoms = [mapping(boundary_gdf.unary_union)] #convert boundary shapefile to compatible format for rasterio mask
        clipped, clipped_transform = mask(src, geoms, crop=True, filled=True, nodata=np.nan) #crop and mask the raster
        meta = src.meta.copy() #copies the original raster metadata
        meta.update({ #updates the metadata to reflect the new extent and crs
            "height": clipped.shape[1],
            "width": clipped.shape[2],
            "transform": clipped_transform,
            "nodata": np.nan #specify that cells outside the boundary should be treated as missing values 
        })

    # save the clipped result to data folder
    with rasterio.open(out_path, "w", **meta) as dst:
        dst.write(clipped)

    os.remove(temp_path)  # remove the temporary folder
    print(f"Saved and tightly clipped raster at → {out_path}")

#Calculate the humidex 
def compute_humidex_raster(temp_arr, rh_arr):
    T = temp_arr.astype("float64")
    RH = rh_arr.astype("float64")
    # Tetens' formula for saturation vapor pressure (in hPa)
    e_sat = 6.112 * 10 ** ((7.5 * T) / (237.7 + T))
    # Actual vapor pressure using RH
    e = RH * e_sat / 100.0
    # Humidex calculation
    humidex = T + (5.0 / 9.0) * (e - 10.0)

    return humidex.astype("float32")

#Normalise the raster to reflect the comfort score. Higher humidex value = lower comfort score
def normalize_0_100(arr):
    finite = np.isfinite(arr) #ignore noData values/cells
    if not finite.any(): #if all values are noData then just do nothing and return the old array
        return arr
    #compute the minimum and maximum value of the array (min and max humidex values)
    vmin = np.nanmin(arr[finite])
    print("Min humidex value:", vmin)
    vmax = np.nanmax(arr[finite])
    print("Max humidex value:", vmax)
    #if all values are equal then just return all zeroes
    if vmax == vmin:
        return np.zeros_like(arr, dtype="float32")
    #perform the reverse linear normalization
    norm = (vmax - arr) / (vmax - vmin) * 100.0
    return norm.astype("float32")

######## Formulas for Mapbox upload ########

# Upload to mapbox using the mapbox api
def upload_to_mapbox(file_path, username, dataset_name, access_token):
    """Upload a GeoJSON or GeoTIFF to Mapbox automatically."""
    print(f"Uploading {os.path.basename(file_path)} to Mapbox")

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
        print("Unrecognized credentials response:")
        print(json.dumps(creds_json, indent=2))
        raise RuntimeError("Mapbox did not return recognizable upload credentials.")

    tileset = f"{username}.{dataset_name}"
    body = {"url": upload_url, "tileset": tileset, "name": dataset_name}
    resp = requests.post(f"https://api.mapbox.com/uploads/v1/{username}?access_token={access_token}", json=body)
    resp.raise_for_status()
    print(f"{dataset_name} uploaded to Mapbox.")

# Convert normalized raster to 8-bit (mapbox only accepts 8-bit)
def convert_to_8bit(in_tif, out_tif, boundary_gdf=None):
    with rasterio.open(in_tif) as src: 
        data = src.read(1).astype("float32")
        meta = src.meta.copy()

        #clip to boundary polygon
        if boundary_gdf is not None: #ensure crs matches if not reproject to match
            if boundary_gdf.crs != src.crs:
                boundary_gdf = boundary_gdf.to_crs(src.crs)
            geoms = [mapping(boundary_gdf.unary_union)] #convert boundary (planning area) into single geometry
            clipped, transform = mask(src, geoms, crop=True, filled=True, nodata=np.nan) #mask the raster
            data = clipped[0]
            meta.update({
                "height": data.shape[0],
                "width": data.shape[1],
                "transform": transform
            })

        #build mask for data that isn't NA (within the boundary polygon)
        mask_valid = np.isfinite(data)
        scaled = np.zeros_like(data, dtype="uint8")
        scaled[mask_valid] = np.clip((data[mask_valid] / 100.0) * 255.0, 0, 255) #scale to 0-255 (8-bit)

        # create RGBA so areas outside the boundary polygon do not show up on the web map
        R = G = B = scaled
        A = np.where(mask_valid, 255, 0).astype("uint8") #create channel where 255 is where data is valid, and 0 is where there's no data (outside boundary)
        #update metadata
        meta.update({
            "driver": "GTiff",
            "dtype": "uint8",
            "count": 4,            
            "compress": "lzw",
            "tiled": True,
            "photometric": "RGB",
            "nodata": None        
        })
        #write each channel to each band 
        with rasterio.open(out_tif, "w", **meta) as dst:
            dst.write(R, 1)
            dst.write(G, 2)
            dst.write(B, 3)
            dst.write(A, 4)
            dst.set_band_description(4, "alpha") #rename band 4 to alpha

    print(f"Saved RGBA GeoTIFF to {out_tif}")


######### Main function for running the functions ###############
def main():
    # NEA API function 
    print("Getting NEA data")
    temp_json, rh_json = fetch_weather_data()

    # Convert NEA data to GeoDataFrame
    print("Building SVY21 GeoDataFrame")
    pts = build_geodataframe(temp_json, rh_json)
    # Export points to GeoJSON
    pts.to_file(points_geojson, driver="GeoJSON")
    print(f"Exported points to {points_geojson}")
    
    # Read Singapore boundary shapefile
    boundary = gpd.read_file(boundary_shp)
    # Ensure boundary is in SVY21
    if boundary.crs is None or boundary.crs.to_epsg() != SVY21_EPSG:
        boundary = boundary.to_crs(epsg=SVY21_EPSG)

    # Run IDW interpolation for temperature and RH and save rasters
    print("Interpolating Temperature (IDW)")
    T_arr, T_transform = idw_interpolate(pts, "T", boundary)
    save_and_clip_raster(T_arr, T_transform, SVY21_EPSG, boundary, temp_ras)

    print("Interpolating Relative Humidity (IDW)")
    RH_arr, RH_transform = idw_interpolate(pts, "RH", boundary)
    save_and_clip_raster(RH_arr, RH_transform, SVY21_EPSG, boundary, rh_ras)

    # Compute Humidex raster and save it
    print("Computing Humidex raster")
    H_arr = compute_humidex_raster(T_arr, RH_arr)
    save_and_clip_raster(H_arr, T_transform, SVY21_EPSG, boundary, humidex_ras)

    # Normalize Humidex raster to comfort score (0-100) and save it
    print("Normalizing Humidex")
    H_norm = normalize_0_100(H_arr)
    save_and_clip_raster(H_norm, T_transform, SVY21_EPSG, boundary, humidex_ras_norm)

    print("All rasters SVY21, clipped, IDW-interpolated.")

    #### Start with mapbox functions for uploading points and raster ####
    print("Preparing for mapbox upload")

    # Change point file to WGS84 (requirement by mapbox)
    pts_wgs84 = pts.to_crs(epsg=4326) 
    points_geojson_web = os.path.join(thermal_comfort_folder, "nea_environment_points_wgs84.geojson")
    pts_wgs84.to_file(points_geojson_web, driver="GeoJSON")

     # Convert humidex to 8-bit TIFF
    humidex_8bit_clipped = os.path.join(thermal_comfort_folder, "humidex_norm_8bit_clipped.tif")
    convert_to_8bit(humidex_ras_norm, humidex_8bit_clipped, boundary)

    # Begin upload to mapbox
    print("Uploading to Mapbox")
    token = os.getenv("MAPBOX_TOKEN") or mapbox_access_token #get the mapbox api token that was put in previously

    upload_to_mapbox(points_geojson_web, mapbox_username, dataset_name, token) #upload the station points along with temp & rh data
    upload_to_mapbox(humidex_8bit_clipped, mapbox_username, "humidex_raster", token) #upload the 8-bit humidex raster

    print("All uploads sent to Mapbox.")

# run the main script
#function will only run when the script is executed directly, not when it is imported as a module in another script
#ensures that there will be no accidental mapbox uploads or data overwrite
if __name__ == "__main__": 
    main()

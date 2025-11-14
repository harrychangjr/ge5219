# Transit comfort dashboard - automated thermal comfort indicator

## Overview
This Python code calculates the thermal comfort of each area of Singapore by doing the following steps: 
1. Fetch real-time air temperature and realtive humidity data from weather stations, using NEA's public API
2. Create a Geodataframe of the station points and weather data, projected to SVY21
3. Interpolates temperature and relative humidity using IDW interpolation 
4. Uses the interpolated raster to calculate humidex values, and then converts it to a 0-100 scale using reverse linear normalization. 
5. Exports all points, and raster outputs as GeoTIFF and GeoJSON. 
6. Upload station points and the normalized humidex raster to Mapbox. 

## Input and Outputs by Function
### fetch_weather_data()
The goal of this function is to obtain the most updated temperature and relative humidity readings using the NEA API. 
**Inputs**: None required. It uses pre-defined API endpoints. \
**Outputs**: "temp_json" and "rh_json" which contain the temperature and relative humidity readings respectively, along with their respective stations, station ID and coordinates (lat/lon). 

### build_geodataframe()
The goal of this function is to convert the data obtained from the NEA API to a point dataset. \
**Inputs**: "temp_json" and "rh_json" returned from fetch_weather_data() \
**Outputs**: Geodataframe called "weather". It is a point dataset containing station ID, temperature, relative humidity, and SVY21 coordinates. It also saves this as a GeoJSON, to the path "Data/nea_environment_points.geojson". 

### make_grid(bounds, cell)
This function generates a 2D coordinate grid that is used for IDW interpolation. \
**Inputs**: "bounds" which is the extent of the Singapore boundary shapefile, and "cell" which is the specified cell size in meters. 
**Outputs**: "xs" and "ys" which is the 1D coordinate arrays for x and y, and "xi" and "yi" which is the 2D array for interpolation. 

### idw_interpolate(points_gdf, field, boundary_gdf, cell, power)
It performs IDW interpolation for the temperature and relative humidity point data \
**Inputs**: 
* "points_gdf": geodataframe containing weather station points with Temperature and RH
* "field": attribute to interpolate
* "boundary_gdf": geodataframe containing the Singapore boundary polygon used to control interpolation extent. 
* "cell": grid cell size in meters
* "power": idw power parameter\
**Outputs**: 
* "zi" the interpolated raster array
* "transform" for georeferencing raster grid
* interpolated rasters saved as files

## save_and_clip_raster(array2d, transform, crs_epsg, boundary_gdf, out_path)
Saves the interpolated raster, clips it to the Singapore boundary, and masks values outside the polygon.

**Inputs**:
* "array2d" is the raster array to be saved
* "transform" helps transform the raster
* "crs_epsg" defines the coordinate system that will be transform into (SVY21)
* "boundary_gdf" is the Singapore boundary and used to mask shapefile
* "out_path" is the file path for the output raster

**Outputs**: 
* Raster file clipped to boundary and in SVY21

## compute_humidex_raster(temp_arr, rh_arr)
It computes the humidex raster using inputs 

**Inputs**: 
* "temp_arr" which is the temperature raster
* "rh_arr" which is the rh raster

**Outputs**:
* Calculated humidex raster

## normalize_0_100(arr)
It normalises humidex values to a score of 0-100 using reverse linear normalization

**Inputs**: 
* The humidex raster array

**Outputs**: 
* The normalized humidex raster with values scaled from 0 to 100

## convert_to_8bit(in_tif, out_tif, boundary_gdf)
It converts the normalized humidex raster to 8-bit format for Mapbox visualization. This is because Mapbox does not accept any other format. 

**Inputs**:
* "in_tif" the normalized humidex raster file
* "out_tif" the output path for the 8-bit raster
* "boundary_gdf" the Singapore boundary file 

**Outputs**: 
* "out_tif" the 8-bit humidex raster

## upload_to_mapbox(file_path, username, dataset_name, access_token)
It uploads the station point and raster to mapbox

**Inputs**: 
* "file_path" which states the file path where the upload will go to
* "username" the mapbox account username
* "dataset_name" which is the name for storage
* "access_token" the mapbox API token

**Outputs**: 
* No physical outputs. It will just provide a response stating the upload has been successfully completed. 

## main()
It helps to run all the other functions

**Inputs**: none

**Outputs**: prints progress through each step and the file paths of outputs. The files saved will be whatever is listed above. 
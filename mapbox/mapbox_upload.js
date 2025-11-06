<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Singapore Live Humidex Map</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://api.mapbox.com/mapbox-gl-js/v3.1.1/mapbox-gl.js"></script>
  <link href="https://api.mapbox.com/mapbox-gl-js/v3.1.1/mapbox-gl.css" rel="stylesheet" />
  <style>
    body { margin:0; padding:0; }
    #map { position:absolute; top:0; bottom:0; width:100%; }
  </style>
</head>
<body>
  <div id="map"></div>

  <script>
    // 1️⃣ Your Mapbox token
    mapboxgl.accessToken = 'pk.eyJ1IjoibncwMyIsImEiOiJjbWhuYnFlcWowMTh6MnJvcHdrbHVoenBzIn0.yWDH_8xIe8Xh2nMUdyCmMA';

    // 2️⃣ Create the map
    const map = new mapboxgl.Map({
      container: 'map',
      style: 'mapbox://styles/mapbox/light-v11',
      center: [103.8198, 1.3521],  // Singapore
      zoom: 10
    });

    map.on('load', () => {
      // 3️⃣ Add your Humidex raster layer (Mapbox tileset)
      map.addSource('humidex', {
        'type': 'raster',
        'url': 'mapbox://nw03.humidex_raster',
        'tileSize': 256
      });
      map.addLayer({
        'id': 'humidex-layer',
        'type': 'raster',
        'source': 'humidex',
        'paint': { 'raster-opacity': 0.85 }
      });

      // 4️⃣ Add your environment points (Mapbox tileset or GitHub GeoJSON)
      map.addSource('stations', {
        'type': 'geojson',
        'data': 'https://raw.githubusercontent.com/harrychangjr/ge5219/NW/Data/nea_environment_points.geojson'
      });
      map.addLayer({
        'id': 'stations-layer',
        'type': 'circle',
        'source': 'stations',
        'paint': {
          'circle-radius': 5,
          'circle-color': '#ff7800',
          'circle-stroke-color': '#ffffff',
          'circle-stroke-width': 1
        }
      });

      console.log("✅ Layers added successfully!");
    });
  </script>
</body>
</html>

function transform(input) {
  var ac = (input && Array.isArray(input.ac)) ? input.ac : [];
  
  // Use geocoded lat/lon from proxy if available, fallback to settings
  var centerLat = parseFloat(input.lat || input.trmnl.plugin_settings.custom_fields_values.lat || 51.5074);
  var centerLon = parseFloat(input.lon || input.trmnl.plugin_settings.custom_fields_values.lon || -0.1278);

  var showGround = (input.trmnl.plugin_settings.custom_fields_values.show_ground === 'yes');
  var units = input.trmnl.plugin_settings.custom_fields_values.unit || 'metric';

  var planesWithDistance = ac
    .filter(function(a) { 
      return a.lat != null && a.lon != null && (showGround || a.alt_baro !== 'ground'); 
    })
    .map(function(a) {
      // Calculate simple Euclidean distance for sorting (relative to center)
      var latDiff = a.lat - centerLat;
      var lonDiff = a.lon - centerLon;
      var distance = Math.sqrt(latDiff * latDiff + lonDiff * lonDiff);

      // Unit conversion
      var speed = a.gs;
      var altitude = a.alt_baro;
      
      if (units === 'metric') {
        if (speed != null) speed = Math.round(speed * 1.852); // knots to km/h
        if (altitude != null && altitude !== 'ground') altitude = Math.round(altitude * 0.3048); // ft to m
      }

      return {
        distance: distance,
        plane: {
          hex:       a.hex || '',
          flight:    (a.flight || '').trim(),
          r:         a.r || '',
          t:         a.t || '',
          alt_baro:  altitude,
          gs:        speed,
          track:     a.track,
          baro_rate: a.baro_rate || 0,
          lat:       a.lat,
          lon:       a.lon
        }
      };
    })
    .sort(function(a, b) { return a.distance - b.distance; })
    .slice(0, 15); // Take only the 15 closest

  var planes = planesWithDistance.map(function(item) { return item.plane; });

  return {
    data: {
      planes: planes,
      total:  input ? (input.total != null ? input.total : planes.length) : 0,
      lat:    centerLat,
      lon:    centerLon,
      fetched_at: input.fetched_at_utc,
      unit_system: units
    }
  };
}
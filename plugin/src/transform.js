function transform(input) {
  var ac = (input && Array.isArray(input.ac)) ? input.ac : [];
  var centerLat = parseFloat(input.trmnl.plugin_settings.custom_fields_values.lat || 51.5074);
  var centerLon = parseFloat(input.trmnl.plugin_settings.custom_fields_values.lon || -0.1278);

  var planesWithDistance = ac
    .filter(function(a) { return a.lat != null && a.lon != null; })
    .map(function(a) {
      // Calculate distance from center
      var latDiff = Math.abs(a.lat - centerLat);
      var lonDiff = Math.abs(a.lon - centerLon);
      var distance = Math.sqrt(latDiff * latDiff + lonDiff * lonDiff);

      return {
        distance: distance,
        plane: {
          hex:       a.hex || '',
          flight:    (a.flight || '').trim(),
          r:         a.r || '',
          t:         a.t || '',
          alt_baro:  a.alt_baro,
          gs:        a.gs,
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
      lat: input.trmnl.plugin_settings.custom_fields_values.lat,
      lon: input.trmnl.plugin_settings.custom_fields_values.lon
    }
  };
}
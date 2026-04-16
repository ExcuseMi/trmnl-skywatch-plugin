function transform(input) {
  var ac = (input && Array.isArray(input.ac)) ? input.ac : [];
  var trmnl = input.trmnl || {};
  var plugin_settings = trmnl.plugin_settings || {};
  var custom_fields = plugin_settings.custom_fields_values || {};

  // Use geocoded lat/lon from proxy if available, fallback to settings, then hardcoded default
  var centerLat = parseFloat(input.lat) || parseFloat(custom_fields.lat) || 51.5074;
  var centerLon = parseFloat(input.lon) || parseFloat(custom_fields.lon) || -0.1278;
  var units = custom_fields.unit || 'metric';

  var planes = ac.map(function(a) {
    var speed = a.gs;
    var altitude = a.alt_baro;

    if (units === 'metric') {
      if (speed != null) speed = Math.round(speed * 1.852); // knots to km/h
      if (altitude != null && altitude !== 'ground') altitude = Math.round(altitude * 0.3048); // ft to m
    }

    return {
      hex:       a.hex || '',
      flight:    (a.flight || '').trim(),
      r:         a.r || '',
      t:         a.t || '',
      cat:       a.cat || '',
      desc:      a.desc || '',
      alt_baro:  altitude,
      gs:        speed,
      track:     a.track,
      baro_rate: a.baro_rate || 0,
      lat:       a.lat,
      lon:       a.lon
    };
  })
  .slice(0, 15); // Limit to 15 for UI clarity on-screen

  return {
    data: {
      planes:      planes,
      total:       input ? (input.total != null ? input.total : planes.length) : 0,
      lat:         centerLat,
      lon:         centerLon,
      fetched_at:  input.fetched_at_utc,
      unit_system: units
    }
  };
}

function transform(input) {
  var ac = (input && Array.isArray(input.data.ac)) ? input.data.ac : [];

  var centerLat = parseFloat(input.data.lat || 51.5074);
  var centerLon = parseFloat(input.data.lon || -0.1278);
  var units = input.trmnl.plugin_settings.custom_fields_values.unit || 'metric';

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
      alt_baro:  altitude,
      gs:        speed,
      track:     a.track,
      baro_rate: a.baro_rate || 0,
      lat:       a.lat,
      lon:       a.lon
    };
  });

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

function transform(input) {
  var ac = (input && Array.isArray(input.data.ac)) ? input.data.ac : [];

  var centerLat = parseFloat(input.data.lat || 51.5074);
  var centerLon = parseFloat(input.data.lon || -0.1278);
  var units = input.trmnl.plugin_settings.custom_fields_values.unit || 'metric';

  var planes = ac.map(function(a) {
    var altitude = a.alt_baro;
    var speed = a.gs;
    if (units === 'metric') {
      if (altitude != null && altitude !== 'ground') altitude = Math.round(altitude * 0.3048); // ft to m
      if (speed != null) speed = Math.round(speed * 1.852); // kt to km/h
    }

    return {
      flight:   (a.flight || '').trim(),
      r:        a.r || '',
      t:        (a.t || '').slice(0, 8),
      cat:      a.cat || '',
      desc:     a.desc || '',
      alt_baro: altitude,
      gs:       speed,
      track:    a.track,
      squawk:   a.squawk || '',
      lat:      a.lat,
      lon:      a.lon
    };
  })
  .slice(0, 30);

  return {
    data: {
      planes:     planes,
      airports:   Array.isArray(input.data.airports) ? input.data.airports : [],
      total:      input.data.total != null ? input.data.total : planes.length,
      lat:        centerLat,
      lon:        centerLon,
      fetched_at: input.data.fetched_at_utc
    }
  };
}

import csv
import io
import requests
from datetime import date

URL = 'https://davidmegginson.github.io/ourairports-data/airports.csv'
OUT = 'AIRPORTS.md'

resp = requests.get(URL, timeout=30)
resp.raise_for_status()

airports = []
reader = csv.DictReader(io.StringIO(resp.text))
for row in reader:
    if row.get('type') not in ('large_airport', 'medium_airport'):
        continue
    iata = (row.get('iata_code') or '').strip()
    if not iata:
        continue
    airports.append({
        'iata':    iata,
        'icao':    (row.get('gps_code') or row.get('ident') or '').strip(),
        'name':    (row.get('name') or '').strip(),
        'city':    (row.get('municipality') or '').strip(),
        'country': (row.get('iso_country') or '').strip(),
        'type':    row.get('type', ''),
        'lat':     row.get('latitude_deg', ''),
        'lon':     row.get('longitude_deg', ''),
    })

airports.sort(key=lambda a: a['iata'])

lines = [
    '# SkyWatch Airport List',
    '',
    f'Large and medium airports shown on the SkyWatch radar display. Updated daily from [OurAirports](https://ourairports.com). Last updated: {date.today().isoformat()}.',
    '',
    f'**{len(airports)} airports** across {len(set(a["country"] for a in airports))} countries.',
    '',
    '| IATA | ICAO | Airport | City | Country |',
    '|------|------|---------|------|---------|',
]

for a in airports:
    lines.append(f'| {a["iata"]} | {a["icao"]} | {a["name"]} | {a["city"]} | {a["country"]} |')

lines.append('')

with open(OUT, 'w') as f:
    f.write('\n'.join(lines))

print(f'Written {len(airports)} airports to {OUT}')

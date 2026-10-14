"""GeoNames cities15000 (CC BY 4.0): parsing and the radius filter. Download and caching live in app.py."""
import csv
import io
import math
import zipfile

CITIES_URL = 'https://download.geonames.org/export/dump/cities15000.zip'
MAX_CITIES = 30


def _label(name: str, ascii_name: str) -> str:
    """The name as written, unless it has glyphs outside Latin and Latin Extended-A (the display font lacks them)."""
    return name if all(ord(c) < 0x180 for c in name) else (ascii_name or name)


def parse_cities(text: str) -> list:
    """Rows of cities15000.txt (tab separated: 1 name, 2 asciiname, 4 lat, 5 lon, 14 population) as dicts."""
    out = []
    for row in csv.reader(io.StringIO(text), delimiter='\t', quoting=csv.QUOTE_NONE):
        if len(row) < 15:
            continue
        try:
            out.append({'name': _label(row[1].strip(), row[2].strip()), 'lat': float(row[4]), 'lon': float(row[5]),
                        'pop': int(row[14] or 0)})
        except ValueError:
            continue
    return out


def read_zip(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return zf.read('cities15000.txt').decode('utf-8')


def _nm(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(a))


def within(cities: list, lat: float, lon: float, radius_nm: float, limit: int = MAX_CITIES) -> list:
    """The most populous cities within a radius, most populous first."""
    near = [c for c in cities if _nm(lat, lon, c['lat'], c['lon']) <= radius_nm]
    near.sort(key=lambda c: -c['pop'])
    return near[:limit]

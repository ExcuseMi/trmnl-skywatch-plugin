"""Terrain profile around a point from AWS Terrain Tiles (Terrarium PNG), as a polar grid.

Pure helpers (tile maths, decoding, the grid) plus one async fetch; no Redis here, app.py caches the result.
Elevation in metres = (R * 256 + G + B / 256) - 32768.
"""
import asyncio
import io
import math
import logging

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

TERRAIN_URL = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'
ZOOM = 9
BEARINGS = 16
STEP_NM = 2
DISTANCES = 25          # 2 .. 50 nm
EARTH_NM = 3440.065


def decode_pixel(r: int, g: int, b: int) -> float:
    return (r * 256 + g + b / 256) - 32768


def tile_of(lat: float, lon: float, z: int = ZOOM):
    """Tile x, y and the pixel inside it (0..255) for a point."""
    n = 2 ** z
    lat = max(-85.0511, min(85.0511, lat))
    fx = (lon + 180.0) / 360.0 * n
    fy = (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi) / 2 * n
    x, y = int(math.floor(fx)) % n, min(n - 1, max(0, int(math.floor(fy))))
    px = min(255, int((fx - math.floor(fx)) * 256))
    py = min(255, int((fy - math.floor(fy)) * 256))
    return x, y, px, py


def destination(lat: float, lon: float, bearing_deg: float, dist_nm: float):
    d = dist_nm / EARTH_NM
    b = math.radians(bearing_deg)
    p1, l1 = math.radians(lat), math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540) % 360 - 180


def grid_points(lat: float, lon: float):
    """The sample points: BEARINGS rows of DISTANCES points (2 nm steps), as (bearing index, distance index, lat, lon)."""
    for bi in range(BEARINGS):
        for di in range(DISTANCES):
            plat, plon = destination(lat, lon, bi * 360.0 / BEARINGS, (di + 1) * STEP_NM)
            yield bi, di, plat, plon


def required_tiles(lat: float, lon: float, z: int = ZOOM) -> set:
    tiles = {tile_of(lat, lon, z)[:2]}
    for _, _, plat, plon in grid_points(lat, lon):
        tiles.add(tile_of(plat, plon, z)[:2])
    return tiles


def decode_tile(png: bytes):
    """A pixel-access object for a Terrarium tile (raises on a corrupt PNG)."""
    img = Image.open(io.BytesIO(png)).convert('RGB')
    if img.size != (256, 256):
        raise ValueError(f'unexpected tile size {img.size}')
    img.load()
    return img.load()


def sample(tiles: dict, lat: float, lon: float, z: int = ZOOM):
    """Elevation in metres at a point from decoded tiles, or None when its tile is missing."""
    x, y, px, py = tile_of(lat, lon, z)
    tile = tiles.get((x, y))
    if tile is None:
        return None
    r, g, b = tile[px, py]
    return decode_pixel(r, g, b)


def build_grid(lat: float, lon: float, tiles: dict, z: int = ZOOM):
    """{'step_nm', 'bearings', 'home_m', 'grid'}: grid[bearing][distance] in whole metres. None when a tile is missing."""
    home = sample(tiles, lat, lon, z)
    if home is None:
        return None
    grid = [[0] * DISTANCES for _ in range(BEARINGS)]
    for bi, di, plat, plon in grid_points(lat, lon):
        v = sample(tiles, plat, plon, z)
        if v is None:
            return None
        grid[bi][di] = int(round(v))
    return {'step_nm': STEP_NM, 'bearings': BEARINGS, 'home_m': int(round(home)), 'grid': grid}


async def fetch_terrain(lat: float, lon: float, client: httpx.AsyncClient, concurrency: int = 4, z: int = ZOOM):
    """Fetch the tiles around a point and build the grid. Any failure returns None (never raises)."""
    try:
        need = sorted(required_tiles(lat, lon, z))
        sem = asyncio.Semaphore(concurrency)

        async def one(xy):
            async with sem:
                resp = await client.get(TERRAIN_URL.format(z=z, x=xy[0], y=xy[1]))
                resp.raise_for_status()
                return xy, decode_tile(resp.content)

        tiles = dict(await asyncio.gather(*[one(xy) for xy in need]))
        return build_grid(lat, lon, tiles, z)
    except Exception as e:  # network, bad PNG, anything: the plugin falls back to the flat strip
        logger.warning(f'terrain fetch failed for {lat:.2f},{lon:.2f}: {e}')
        return None

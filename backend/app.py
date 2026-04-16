import os
import asyncio
import aiosqlite
import httpx
import time
import json
import logging
import math
from datetime import datetime, timedelta, timezone
from quart import Quart, request, jsonify

MAX_PLANES = 30

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Quart(__name__)

# Configuration
CACHE_MINUTES = 5
DB_PATH = '/data/skywatch_cache.db'
ENABLE_IP_WHITELIST = os.getenv('ENABLE_IP_WHITELIST', 'false').lower() == 'true'
IP_REFRESH_HOURS = 24
MAX_QUEUE_SIZE = 20      # reject new requests beyond this queue depth
QUEUE_TIMEOUT = 5.0      # seconds to wait in queue before falling back to cache

# TRMNL server IPs
TRMNL_IPS: set = set()

# API request queue (single worker, 1 req/sec rate limit)
api_queue: asyncio.Queue = None
last_api_call_time: float = 0.0

# Ensure data directory exists
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS plane_cache_v2 (
                lat_key INTEGER,
                lon_key INTEGER,
                show_ground INTEGER,
                data_json TEXT,
                fetched_at TIMESTAMP,
                PRIMARY KEY (lat_key, lon_key, show_ground)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS geocoding_cache (
                address TEXT PRIMARY KEY,
                lat REAL,
                lon REAL,
                cached_at TIMESTAMP
            )
        ''')
        await db.commit()


async def get_from_cache(lat_key: int, lon_key: int, show_ground: bool):
    """Returns (data_dict, is_fresh).  data_dict is None when no cache entry."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'SELECT data_json, fetched_at FROM plane_cache_v2 WHERE lat_key = ? AND lon_key = ? AND show_ground = ?',
            (lat_key, lon_key, int(show_ground))
        )
        row = await cursor.fetchone()
        if row:
            data_json, fetched_at_str = row
            fetched_at = datetime.fromisoformat(fetched_at_str)
            if fetched_at.tzinfo is None:
                fetched_at = fetched_at.replace(tzinfo=timezone.utc)
            
            age = datetime.now(timezone.utc) - fetched_at
            is_fresh = age < timedelta(minutes=CACHE_MINUTES)
            return json.loads(data_json), is_fresh
    return None, False


async def purge_cache():
    """Delete old cache entries to keep the DB small."""
    try:
        now = datetime.now(timezone.utc)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                'DELETE FROM plane_cache_v2 WHERE fetched_at < ?',
                ((now - timedelta(hours=1)).isoformat(),)
            )
            await db.execute(
                'DELETE FROM geocoding_cache WHERE cached_at < ?',
                ((now - timedelta(days=30)).isoformat(),)
            )
            await db.commit()
        logger.info("Purged old cache entries")
    except Exception as e:
        logger.error(f"Error purging cache: {e}")


# ---------------------------------------------------------------------------
# IP whitelist
# ---------------------------------------------------------------------------

async def fetch_trmnl_ips() -> set:
    """Fetch TRMNL server IPs from their API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get('https://trmnl.com/api/ips')
            response.raise_for_status()
            data = response.json()
            ips = set(data.get('data', {}).get('ipv4', []))
            ips.update(data.get('data', {}).get('ipv6', []))
            logger.info(f"Fetched {len(ips)} TRMNL IPs")
            return ips
    except Exception as e:
        logger.error(f"Failed to fetch TRMNL IPs: {e}")
        return set()


def check_ip_whitelist() -> bool:
    if not ENABLE_IP_WHITELIST:
        return True
    client_ip = (
        request.headers.get('CF-Connecting-IP') or
        request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or
        request.remote_addr
    )
    return client_ip in TRMNL_IPS


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

async def geocode_address(address: str):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'SELECT lat, lon FROM geocoding_cache WHERE address = ?', (address,)
        )
        row = await cursor.fetchone()
        if row:
            return {'lat': row[0], 'lon': row[1]}

    url = "https://nominatim.openstreetmap.org/search"
    params = {'q': address, 'format': 'json', 'limit': 1}
    headers = {'User-Agent': 'TRMNL-Skywatch-Plugin/1.0'}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if data:
                    lat, lon = float(data[0]['lat']), float(data[0]['lon'])
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute(
                            'INSERT OR REPLACE INTO geocoding_cache VALUES (?, ?, ?, ?)',
                            (address, lat, lon, datetime.now(timezone.utc).isoformat())
                        )
                        await db.commit()
                    return {'lat': lat, 'lon': lon}
    except Exception as e:
        logger.error(f"Geocoding error: {e}")
    return None


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def reduce_payload(raw_data: dict, center_lat: float, center_lon: float, show_ground: bool = False) -> dict:
    """Filter, sort by proximity, and limit aircraft data."""
    ac_list = raw_data.get('ac', [])
    processed = []

    for a in ac_list:
        p_lat = a.get('lat')
        p_lon = a.get('lon')
        alt = a.get('alt_baro')

        if p_lat is None or p_lon is None:
            continue

        if not show_ground and alt == 'ground':
            continue

        # Simple Euclidean distance for sorting
        dist = math.sqrt((p_lat - center_lat)**2 + (p_lon - center_lon)**2)
        desc = a.get('desc')

        processed.append({
            'hex':       a.get('hex', ''),
            'flight':    (a.get('flight', '')).strip(),
            'r':         a.get('r', ''),
            't':         a.get('t', ''),
            'alt_baro':  alt,
            'gs':        a.get('gs'),
            'track':     a.get('track'),
            'baro_rate': a.get('baro_rate', 0),
            'lat':       p_lat,
            'lon':       p_lon,
            '_dist':     dist,
            'desc':      desc,
        })

    # Sort by distance and limit to closest 20
    processed.sort(key=lambda x: x['_dist'])
    closest = processed[:MAX_PLANES]

    for p in closest:
        del p['_dist']

    return {
        'ac':    closest,
        'total': raw_data.get('total', len(processed)),
    }


# ---------------------------------------------------------------------------
# API queue worker
# ---------------------------------------------------------------------------

async def _do_api_call(lat_key: int, lon_key: int, lat: float, lon: float, show_ground: bool) -> dict:
    """Make the upstream API call, persist to cache, and return the payload."""
    global last_api_call_time

    url = f"https://api.airplanes.live/v2/point/{lat}/{lon}/50"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url)
        last_api_call_time = time.monotonic()
        response.raise_for_status()
        raw_data = response.json()

    reduced = reduce_payload(raw_data, lat, lon, show_ground)
    now_utc = datetime.now(timezone.utc)
    reduced['fetched_at_utc'] = now_utc.isoformat()

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            'INSERT OR REPLACE INTO plane_cache_v2 VALUES (?, ?, ?, ?, ?)',
            (lat_key, lon_key, int(show_ground), json.dumps(reduced), now_utc.isoformat())
        )
        await db.commit()

    return reduced


async def api_worker():
    """Single worker that drains api_queue, rate-limited to ≤1 req/sec."""
    global last_api_call_time

    while True:
        lat_key, lon_key, lat, lon, show_ground, fut = await api_queue.get()
        try:
            if fut.done():
                continue

            elapsed = time.monotonic() - last_api_call_time
            sleep_time = max(0.0, 1.0 - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

            data = await _do_api_call(lat_key, lon_key, lat, lon, show_ground)
            if not fut.done():
                fut.set_result(data)

        except Exception as e:
            logger.error(f"API worker error for {lat_key},{lon_key}: {e}")
            if not fut.done():
                fut.set_exception(e)
        finally:
            api_queue.task_done()


# ---------------------------------------------------------------------------
# fetch_planes — queue + cache fallback
# ---------------------------------------------------------------------------

async def fetch_planes(lat: float, lon: float, show_ground: bool):
    lat_key = int(lat * 100)
    lon_key = int(lon * 100)

    cached_data, is_fresh = await get_from_cache(lat_key, lon_key, show_ground)
    if is_fresh:
        logger.info(f"CACHE HIT: {lat_key}, {lon_key}, ground={show_ground}")
        return cached_data

    logger.info(f"CACHE MISS: {lat_key}, {lon_key}, ground={show_ground}")

    if api_queue.qsize() >= MAX_QUEUE_SIZE:
        logger.warning(f"Queue full, returning stale cache for {lat_key},{lon_key}")
        return cached_data

    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()
    await api_queue.put((lat_key, lon_key, lat, lon, show_ground, fut))

    try:
        return await asyncio.wait_for(fut, timeout=QUEUE_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(f"Queue timeout, returning stale cache for {lat_key},{lon_key}")
        return cached_data
    except Exception as e:
        logger.error(f"fetch_planes error: {e}")
        return cached_data


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
async def get_planes():
    if not check_ip_whitelist():
        return jsonify({'error': 'Access denied'}), 403

    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    address = request.args.get('address', type=str)
    show_ground = request.args.get('show_ground', 'false').lower() == 'true'

    if address:
        geo = await geocode_address(address)
        if geo:
            lat, lon = geo['lat'], geo['lon']
        else:
            return jsonify({'error': 'Location not found'}), 400

    if lat is None or lon is None:
        return jsonify({'error': 'Missing lat/lon or address'}), 400

    data = await fetch_planes(lat, lon, show_ground)
    if data:
        data['lat'] = lat
        data['lon'] = lon
        return jsonify({ 'data': data})
    return jsonify({'error': 'Failed to fetch data'}), 500


@app.route('/health')
async def health():
    return jsonify({
        'status':       'healthy',
        'ip_whitelist': ENABLE_IP_WHITELIST,
        'queue_size':   api_queue.qsize() if api_queue else 0,
    })


# ---------------------------------------------------------------------------
# Startup / background tasks
# ---------------------------------------------------------------------------

async def _background_purge():
    """Purge stale cache entries every 24 hours."""
    while True:
        await asyncio.sleep(24 * 3600)
        await purge_cache()


async def _background_ip_refresh():
    """Re-fetch TRMNL IP list every IP_REFRESH_HOURS hours."""
    global TRMNL_IPS
    while True:
        await asyncio.sleep(IP_REFRESH_HOURS * 3600)
        TRMNL_IPS = await fetch_trmnl_ips()
        logger.info(f"Refreshed TRMNL IPs ({len(TRMNL_IPS)} addresses)")


@app.before_serving
async def startup():
    global api_queue, TRMNL_IPS

    await init_db()

    api_queue = asyncio.Queue()
    asyncio.ensure_future(api_worker())

    if ENABLE_IP_WHITELIST:
        TRMNL_IPS = await fetch_trmnl_ips()
        asyncio.ensure_future(_background_ip_refresh())

    asyncio.ensure_future(_background_purge())

    logger.info("Startup complete — Hypercorn/Quart ASGI server ready")

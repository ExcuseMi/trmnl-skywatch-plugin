import os
import asyncio
import httpx
import time
import json
import logging
import math
from datetime import datetime, timezone
import redis.asyncio as aioredis
from quart import Quart, request, jsonify

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Quart(__name__)

REDIS_URL        = os.getenv('REDIS_URL', 'redis://localhost:6379')
CACHE_TTL        = int(os.getenv('CACHE_TTL_SECONDS', '300'))   # 5 min
GEO_CACHE_TTL    = 30 * 24 * 3600                               # 30 days
ENABLE_IP_WHITELIST = os.getenv('ENABLE_IP_WHITELIST', 'false').lower() == 'true'
IP_REFRESH_HOURS = 24
MAX_QUEUE_SIZE   = 20
QUEUE_TIMEOUT    = 5.0
MAX_PLANES       = 50

TRMNL_IPS: set = set()

redis_client: aioredis.Redis = None
api_queue: asyncio.Queue     = None
last_api_call_time: float    = 0.0
_inflight: dict              = {}   # (lat_key, lon_key, show_ground) -> Future


# ---------------------------------------------------------------------------
# Tile key — 0.5° resolution (~55 km), well within the 50 nm API radius
# ---------------------------------------------------------------------------

def tile_key(lat: float, lon: float):
    return round(lat * 2), round(lon * 2)


def tile_center(lat_key: int, lon_key: int):
    return lat_key / 2.0, lon_key / 2.0


def cache_key(lat_key: int, lon_key: int, show_ground: bool) -> str:
    return f"skywatch:planes:{lat_key}:{lon_key}:{int(show_ground)}"


def geo_key(address: str) -> str:
    return f"skywatch:geo:{address.lower().strip()}"


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

async def get_from_cache(lat_key: int, lon_key: int, show_ground: bool):
    key = cache_key(lat_key, lon_key, show_ground)
    raw = await redis_client.get(key)
    if raw:
        return json.loads(raw)
    return None


async def set_cache(lat_key: int, lon_key: int, show_ground: bool, data: dict):
    key = cache_key(lat_key, lon_key, show_ground)
    await redis_client.setex(key, CACHE_TTL, json.dumps(data))


# ---------------------------------------------------------------------------
# IP whitelist
# ---------------------------------------------------------------------------

async def fetch_trmnl_ips() -> set:
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
    key = geo_key(address)
    raw = await redis_client.get(key)
    if raw:
        return json.loads(raw)

    url = "https://nominatim.openstreetmap.org/search"
    params = {'q': address, 'format': 'json', 'limit': 1}
    headers = {'User-Agent': 'TRMNL-Skywatch-Plugin/1.0'}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params, headers=headers)
            if response.status_code == 200:
                data = response.json()
                if data:
                    result = {'lat': float(data[0]['lat']), 'lon': float(data[0]['lon'])}
                    await redis_client.setex(key, GEO_CACHE_TTL, json.dumps(result))
                    return result
    except Exception as e:
        logger.error(f"Geocoding error: {e}")
    return None


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------

def reduce_payload(raw_data: dict, center_lat: float, center_lon: float, show_ground: bool) -> dict:
    ac_list = raw_data.get('ac', [])
    processed = []

    for a in ac_list:
        p_lat = a.get('lat')
        p_lon = a.get('lon')
        alt   = a.get('alt_baro')

        if p_lat is None or p_lon is None:
            continue
        if not show_ground and alt == 'ground':
            continue

        dist = math.sqrt((p_lat - center_lat) ** 2 + (p_lon - center_lon) ** 2)
        processed.append({
            'hex':       a.get('hex', ''),
            'flight':    (a.get('flight', '')).strip(),
            'r':         a.get('r', ''),
            't':         a.get('t', ''),
            'cat':       a.get('category'),
            'desc':      a.get('desc', ''),
            'alt_baro':  alt,
            'gs':        a.get('gs'),
            'track':     a.get('track'),
            'baro_rate': a.get('baro_rate', 0),
            'squawk':    a.get('squawk', ''),
            'lat':       p_lat,
            'lon':       p_lon,
            '_dist':     dist,
        })

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

async def _do_api_call(lat_key: int, lon_key: int, show_ground: bool) -> dict:
    global last_api_call_time

    lat, lon = tile_center(lat_key, lon_key)
    url = f"https://api.airplanes.live/v2/point/{lat}/{lon}/50"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url)
        last_api_call_time = time.monotonic()
        response.raise_for_status()
        raw_data = response.json()

    reduced = reduce_payload(raw_data, lat, lon, show_ground)
    reduced['fetched_at_utc'] = datetime.now(timezone.utc).isoformat()

    await set_cache(lat_key, lon_key, show_ground, reduced)
    return reduced


async def api_worker():
    global last_api_call_time

    while True:
        lat_key, lon_key, show_ground, fut = await api_queue.get()
        inflight_key = (lat_key, lon_key, show_ground)
        try:
            if fut.done():
                continue

            # Another queued entry may have already populated the cache
            cached = await get_from_cache(lat_key, lon_key, show_ground)
            if cached is not None:
                logger.info(f"WORKER CACHE HIT (dedup): {lat_key},{lon_key}")
                if not fut.done():
                    fut.set_result(cached)
                continue

            elapsed    = time.monotonic() - last_api_call_time
            sleep_time = max(0.0, 1.0 - elapsed)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

            data = await _do_api_call(lat_key, lon_key, show_ground)
            if not fut.done():
                fut.set_result(data)

        except Exception as e:
            logger.error(f"API worker error for {lat_key},{lon_key}: {e}")
            if not fut.done():
                fut.set_exception(e)
        finally:
            _inflight.pop(inflight_key, None)
            api_queue.task_done()


# ---------------------------------------------------------------------------
# fetch_planes — cache → deduplicate → queue
# ---------------------------------------------------------------------------

async def fetch_planes(lat: float, lon: float, show_ground: bool):
    lat_key, lon_key = tile_key(lat, lon)
    inflight_key = (lat_key, lon_key, show_ground)

    cached = await get_from_cache(lat_key, lon_key, show_ground)
    if cached is not None:
        logger.info(f"CACHE HIT: {lat_key},{lon_key} ground={show_ground}")
        return cached

    logger.info(f"CACHE MISS: {lat_key},{lon_key} ground={show_ground}")

    # Attach to an already-queued future for the same tile
    if inflight_key in _inflight:
        logger.info(f"IN-FLIGHT HIT: {lat_key},{lon_key}")
        try:
            return await asyncio.wait_for(asyncio.shield(_inflight[inflight_key]), timeout=QUEUE_TIMEOUT)
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

    if api_queue.qsize() >= MAX_QUEUE_SIZE:
        logger.warning(f"Queue full, returning stale cache for {lat_key},{lon_key}")
        return cached  # may be None; caller handles it

    loop = asyncio.get_event_loop()
    fut: asyncio.Future = loop.create_future()
    _inflight[inflight_key] = fut
    await api_queue.put((lat_key, lon_key, show_ground, fut))

    try:
        return await asyncio.wait_for(asyncio.shield(fut), timeout=QUEUE_TIMEOUT)
    except asyncio.TimeoutError:
        logger.warning(f"Queue timeout, returning stale cache for {lat_key},{lon_key}")
        stale = await get_from_cache(lat_key, lon_key, show_ground)
        return stale
    except Exception as e:
        logger.error(f"fetch_planes error: {e}")
        stale = await get_from_cache(lat_key, lon_key, show_ground)
        return stale


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
async def get_planes():
    if not check_ip_whitelist():
        return jsonify({'error': 'Access denied'}), 403

    lat        = request.args.get('lat', type=float)
    lon        = request.args.get('lon', type=float)
    address    = request.args.get('address', type=str)
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
        return jsonify({'data': data})
    return jsonify({'error': 'Failed to fetch data'}), 500


@app.route('/health')
async def health():
    redis_ok = False
    try:
        await redis_client.ping()
        redis_ok = True
    except Exception:
        pass

    return jsonify({
        'status':       'healthy' if redis_ok else 'degraded',
        'redis':        redis_ok,
        'ip_whitelist': ENABLE_IP_WHITELIST,
        'queue_size':   api_queue.qsize() if api_queue else 0,
        'inflight':     len(_inflight),
    })


# ---------------------------------------------------------------------------
# Startup / background tasks
# ---------------------------------------------------------------------------

async def _background_ip_refresh():
    global TRMNL_IPS
    while True:
        await asyncio.sleep(IP_REFRESH_HOURS * 3600)
        TRMNL_IPS = await fetch_trmnl_ips()
        logger.info(f"Refreshed TRMNL IPs ({len(TRMNL_IPS)} addresses)")


@app.before_serving
async def startup():
    global api_queue, redis_client, TRMNL_IPS

    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    await redis_client.ping()
    logger.info(f"Redis connected: {REDIS_URL}")

    api_queue = asyncio.Queue()
    asyncio.ensure_future(api_worker())

    if ENABLE_IP_WHITELIST:
        TRMNL_IPS = await fetch_trmnl_ips()
        asyncio.ensure_future(_background_ip_refresh())

    logger.info("Startup complete — Hypercorn/Quart ASGI server ready")


@app.after_serving
async def shutdown():
    if redis_client:
        await redis_client.aclose()

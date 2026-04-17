import os
import asyncio
import csv
import io
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
CACHE_TTL        = int(os.getenv('CACHE_TTL_SECONDS', '840'))   # 14 min
USER_AGENT       = os.getenv('USER_AGENT', 'TRMNL-Skywatch-Plugin/1.0')
GEO_CACHE_TTL    = 30 * 24 * 3600                               # 30 days
ENABLE_IP_WHITELIST = os.getenv('ENABLE_IP_WHITELIST', 'false').lower() == 'true'
IP_REFRESH_HOURS = 24
MAX_QUEUE_SIZE   = 20
QUEUE_TIMEOUT    = 5.0
MAX_PLANES       = 50

AIRPORT_CACHE_TTL    = 24 * 3600   # airports barely change
OURAIRPORTS_CSV_URL  = 'https://davidmegginson.github.io/ourairports-data/airports.csv'
OURAIRPORTS_CACHE_KEY = 'skywatch:ourairports'
RADIUS_DEG           = 1.5        # ~165 km bounding box pre-filter before precise distance check
RADIUS_NM            = 50.0       # 50 nautical miles
NM_PER_DEG_LAT       = 60.0

TRMNL_IPS: set = set()

redis_client: aioredis.Redis = None
api_queue: asyncio.Queue     = None
last_api_call_time: float    = 0.0
_backoff_until: float        = 0.0
_inflight: dict              = {}   # (lat_key, lon_key, show_ground) -> Future

STATS_KEY = 'skywatch:stats'


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
# Stats
# ---------------------------------------------------------------------------

async def increment_stat(field: str, amount: int = 1):
    await redis_client.hincrby(STATS_KEY, field, amount)


async def _background_stats_logger():
    """Log a stats summary every hour."""
    while True:
        await asyncio.sleep(3600)
        raw = await redis_client.hgetall(STATS_KEY)
        s = {k: int(v) for k, v in raw.items()}
        total  = s.get('requests', 0)
        hits   = s.get('cache_hits', 0)
        misses = s.get('cache_misses', 0)
        dedup  = s.get('inflight_hits', 0)
        calls  = s.get('api_calls', 0)
        errors = s.get('api_errors', 0)
        hit_rate = f"{hits/total*100:.1f}%" if total else "n/a"
        logger.info(
            f"STATS | requests={total} cache_hits={hits} misses={misses} "
            f"inflight_dedup={dedup} api_calls={calls} api_errors={errors} "
            f"hit_rate={hit_rate}"
        )


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
# Airports
# ---------------------------------------------------------------------------

def airport_cache_key(lat_key: int, lon_key: int) -> str:
    return f"skywatch:airports:{lat_key}:{lon_key}"


async def _load_ourairports() -> list:
    """Return the cached airport list, or [] if not yet populated."""
    raw = await redis_client.get(OURAIRPORTS_CACHE_KEY)
    return json.loads(raw) if raw else []


async def _refresh_ourairports():
    """Fetch and parse OurAirports CSV, store in Redis."""
    logger.info("Refreshing OurAirports CSV...")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(OURAIRPORTS_CSV_URL)
            resp.raise_for_status()
    except Exception as e:
        logger.error(f"OurAirports fetch error: {e} — keeping existing cache")
        return

    airports = []
    reader = csv.DictReader(io.StringIO(resp.text))
    for row in reader:
        if row.get('type') not in ('large_airport', 'medium_airport'):
            continue
        iata = (row.get('iata_code') or '').strip()
        if not iata:
            continue
        try:
            a_lat = float(row['latitude_deg'])
            a_lon = float(row['longitude_deg'])
        except (ValueError, KeyError):
            continue
        airports.append({
            'iata': iata,
            'icao': (row.get('gps_code') or row.get('ident') or '').strip(),
            'name': (row.get('name') or '').strip(),
            'lat':  a_lat,
            'lon':  a_lon,
        })

    await redis_client.set(OURAIRPORTS_CACHE_KEY, json.dumps(airports))
    logger.info(f"OurAirports: {len(airports)} large/medium airports cached")


async def _background_ourairports():
    """Refresh OurAirports dataset immediately at startup, then every 24h."""
    while True:
        await _refresh_ourairports()
        await asyncio.sleep(AIRPORT_CACHE_TTL)


async def fetch_airports(lat: float, lon: float, lat_key: int, lon_key: int) -> list:
    key = airport_cache_key(lat_key, lon_key)
    raw = await redis_client.get(key)
    if raw:
        return json.loads(raw)

    all_airports = await _load_ourairports()
    if not all_airports:
        return []

    cos_lat = math.cos(math.radians(lat))
    nearby = []
    for a in all_airports:
        dlat = a['lat'] - lat
        dlon = (a['lon'] - lon) * cos_lat
        if math.sqrt(dlat ** 2 + dlon ** 2) * NM_PER_DEG_LAT <= RADIUS_NM:
            nearby.append(a)

    await redis_client.setex(key, AIRPORT_CACHE_TTL, json.dumps(nearby))
    logger.info(f"Airports for tile {lat_key},{lon_key}: {len(nearby)} within {RADIUS_NM}nm")
    return nearby


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
    global last_api_call_time, _backoff_until

    lat, lon = tile_center(lat_key, lon_key)
    url = f"https://api.airplanes.live/v2/point/{lat}/{lon}/50"

    t0 = time.monotonic()
    last_api_call_time = t0
    async with httpx.AsyncClient(timeout=15.0, headers={'User-Agent': USER_AGENT}) as client:
        response = await client.get(url)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if response.status_code == 429:
        retry_after = float(response.headers.get('Retry-After', 10.0))
        logger.warning(f"429 rate limited tile={lat_key},{lon_key} retry_after={retry_after}s")
        await increment_stat('api_rate_limited')
        _backoff_until = time.monotonic() + retry_after
        raise Exception(f"429 rate limited for tile {lat_key},{lon_key}")

    response.raise_for_status()
    raw_data = response.json()

    await increment_stat('api_calls')
    ac_count = len(raw_data.get('ac', []))
    logger.info(f"API CALL: tile={lat_key},{lon_key} ac={ac_count} status={response.status_code} elapsed={elapsed_ms}ms")

    reduced = reduce_payload(raw_data, lat, lon, show_ground)
    reduced['fetched_at_utc'] = datetime.now(timezone.utc).isoformat()

    await set_cache(lat_key, lon_key, show_ground, reduced)
    return reduced


async def api_worker():
    global last_api_call_time, _backoff_until

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

            now        = time.monotonic()
            sleep_time = max(0.0, _backoff_until - now, 1.0 - (now - last_api_call_time))
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

            data = await _do_api_call(lat_key, lon_key, show_ground)
            if not fut.done():
                fut.set_result(data)

        except Exception as e:
            logger.error(f"API worker error for {lat_key},{lon_key}: {e}")
            await increment_stat('api_errors')
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
        await increment_stat('cache_hits')
        return cached

    logger.info(f"CACHE MISS: {lat_key},{lon_key} ground={show_ground}")
    await increment_stat('cache_misses')

    # Attach to an already-queued future for the same tile
    if inflight_key in _inflight:
        logger.info(f"IN-FLIGHT HIT: {lat_key},{lon_key}")
        await increment_stat('inflight_hits')
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

    await increment_stat('requests')
    lat_key, lon_key = tile_key(lat, lon)
    data, airports = await asyncio.gather(
        fetch_planes(lat, lon, show_ground),
        fetch_airports(lat, lon, lat_key, lon_key),
    )
    if data:
        data['lat']      = lat
        data['lon']      = lon
        data['airports'] = airports
        return jsonify({'data': data})
    return jsonify({'error': 'Failed to fetch data'}), 500


@app.route('/debug/airports')
async def debug_airports():
    lat = request.args.get('lat', type=float, default=51.5074)
    lon = request.args.get('lon', type=float, default=-0.1278)
    lat_key, lon_key = tile_key(lat, lon)
    airports = await fetch_airports(lat, lon, lat_key, lon_key)
    return jsonify({'tile': [lat_key, lon_key], 'count': len(airports), 'airports': airports})


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
    asyncio.ensure_future(_background_ourairports())
    asyncio.ensure_future(_background_stats_logger())

    if ENABLE_IP_WHITELIST:
        TRMNL_IPS = await fetch_trmnl_ips()
        asyncio.ensure_future(_background_ip_refresh())

    logger.info("Startup complete — Hypercorn/Quart ASGI server ready")


@app.after_serving
async def shutdown():
    if redis_client:
        await redis_client.aclose()

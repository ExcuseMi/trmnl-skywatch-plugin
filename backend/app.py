import os
import re
import asyncio
import csv
import io
import httpx
import time
import json
import logging
import math
import yaml
from datetime import datetime, timezone
from pathlib import Path
import redis.asyncio as aioredis
from quart import Quart, request, jsonify

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('httpcore').setLevel(logging.WARNING)
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
ROUTE_CACHE_TTL      = 4 * 3600    # routes don't change mid-flight
OURAIRPORTS_CSV_URL  = 'https://davidmegginson.github.io/ourairports-data/airports.csv'
OURAIRPORTS_CACHE_KEY = 'skywatch:ourairports'
RADIUS_NM            = float(os.getenv('RADIUS_NM', '50'))
RADIUS_DEG           = RADIUS_NM / 60.0 * 1.1  # bounding box pre-filter with margin
NM_PER_DEG_LAT       = 60.0

TRMNL_IPS: set = set()

redis_client: aioredis.Redis = None
api_queue: asyncio.Queue     = None
_backoff_until: float        = 0.0
_inflight: dict              = {}   # (lat_key, lon_key, show_ground) -> Future
_providers: list             = []
_provider_last_call: dict    = {}   # provider name -> monotonic timestamp
_route_semaphore: asyncio.Semaphore = None
_adsbdb_backoff_until: float        = 0.0

STATS_KEY = 'skywatch:stats'

# ---------------------------------------------------------------------------
# Providers
# ---------------------------------------------------------------------------

def _load_providers() -> list:
    path = Path(__file__).parent / 'providers.yml'
    with open(path) as f:
        data = yaml.safe_load(f)
    providers = data.get('providers', [])
    logger.info(f"Loaded {len(providers)} providers: {[p['name'] for p in providers]}")
    return providers


def select_provider() -> dict:
    """Return the highest-priority provider (list order) that is off cooldown."""
    now = time.monotonic()
    for p in _providers:
        last = _provider_last_call.get(p['name'], 0.0)
        if now - last >= p['cooldown_ms'] / 1000.0:
            return p
    return None


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
    if CACHE_TTL <= 0:
        return
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

        total    = s.get('requests', 0)
        hits     = s.get('cache_hits', 0)
        misses   = s.get('cache_misses', 0)
        dedup    = s.get('inflight_hits', 0)
        errors   = s.get('api_errors', 0)
        hit_rate = f"{hits/total*100:.1f}%" if total else "n/a"

        logger.info(
            f"STATS | requests={total} cache_hits={hits}({hit_rate}) misses={misses} "
            f"inflight_dedup={dedup} api_errors={errors}"
        )

        # Per-provider breakdown
        for p in _providers:
            name  = p['name']
            calls = s.get(f"calls:{name}", 0)
            rl    = s.get(f"rate_limited:{name}", 0)
            errs  = s.get(f"errors:{name}", 0)
            logger.info(f"  {name}: calls={calls} rate_limited={rl} errors={errs}")


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
    try:
        async with httpx.AsyncClient(timeout=10.0, headers={'User-Agent': USER_AGENT}) as client:
            response = await client.get(url, params=params)
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

def reduce_payload(raw_data: dict, center_lat: float, center_lon: float, show_ground: bool, ac_key: str = 'ac') -> dict:
    ac_list = raw_data.get(ac_key, [])
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
    global _backoff_until

    provider = select_provider()
    if provider is None:
        raise Exception("All providers on cooldown")

    lat, lon = tile_center(lat_key, lon_key)
    url = provider['url'].format(lat=lat, lon=lon, radius=int(RADIUS_NM))
    _provider_last_call[provider['name']] = time.monotonic()

    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=15.0, headers={'User-Agent': USER_AGENT}) as client:
        response = await client.get(url)
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    if response.status_code == 429:
        retry_after = float(response.headers.get('Retry-After', provider['cooldown_ms'] / 1000.0))
        _provider_last_call[provider['name']] = time.monotonic() + retry_after - provider['cooldown_ms'] / 1000.0
        _backoff_until = time.monotonic() + 1.0
        await increment_stat(f"rate_limited:{provider['name']}")
        logger.warning(f"RATE LIMITED: {provider['name']} retry_after={retry_after}s tile={lat_key},{lon_key}")
        raise Exception(f"429 rate limited on {provider['name']}")

    response.raise_for_status()
    raw_data = response.json()

    ac_count = len(raw_data.get(provider.get('ac_key', 'ac'), []))
    await increment_stat(f"calls:{provider['name']}")
    logger.info(f"API: {provider['name']} tile={lat_key},{lon_key} ac={ac_count} elapsed={elapsed_ms}ms")

    reduced = reduce_payload(raw_data, lat, lon, show_ground, ac_key=provider.get('ac_key', 'ac'))
    reduced['fetched_at_utc'] = datetime.now(timezone.utc).isoformat()
    reduced['provider'] = provider['name']

    await set_cache(lat_key, lon_key, show_ground, reduced)
    return reduced


async def api_worker():
    global _backoff_until

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
            sleep_time = max(0.0, _backoff_until - now)
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

            # If all providers still on cooldown, wait for the soonest one
            while select_provider() is None:
                min_wait = min(
                    p['cooldown_ms'] / 1000.0 - (now - _provider_last_call.get(p['name'], 0.0))
                    for p in _providers
                )
                logger.info(f"All providers on cooldown, waiting {min_wait:.1f}s")
                await asyncio.sleep(max(0.05, min_wait))

            data = await _do_api_call(lat_key, lon_key, show_ground)
            if not fut.done():
                fut.set_result(data)

        except Exception as e:
            logger.error(f"API worker error for {lat_key},{lon_key}: {e}")
            await increment_stat('api_errors')
            # Track which provider errored if name is in the message
            for p in _providers:
                if p['name'] in str(e):
                    await increment_stat(f"errors:{p['name']}")
                    break
            if not fut.done():
                stale = await get_from_cache(lat_key, lon_key, show_ground)
                fut.set_result(stale)
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
# Route lookup (adsbdb.com)
# ---------------------------------------------------------------------------

def route_key(callsign: str) -> str:
    return f"skywatch:route:{callsign.strip().lower()}"


def _valid_callsign(cs: str) -> bool:
    # Airline callsigns: 2-3 alpha prefix + digits, min 4 chars (e.g. BAW1, EZY42VZ)
    return bool(cs and len(cs) >= 4 and re.match(r'^[A-Z]{2,3}\d', cs))


async def fetch_route(callsign: str) -> tuple[dict | None, bool]:
    """Returns (route_or_None, cache_hit)."""
    callsign = callsign.strip()
    if not callsign or not _valid_callsign(callsign):
        return None, False

    key = route_key(callsign)
    raw = await redis_client.get(key)
    if raw is not None:
        return json.loads(raw), True

    global _adsbdb_backoff_until
    if time.monotonic() < _adsbdb_backoff_until:
        return None, False

    try:
        async with _route_semaphore:
            async with httpx.AsyncClient(timeout=5.0, headers={'User-Agent': USER_AGENT}) as client:
                resp = await client.get(f'https://api.adsbdb.com/v0/callsign/{callsign}')

        if resp.status_code == 429:
            retry_after = float(resp.headers.get('Retry-After', 60))
            _adsbdb_backoff_until = time.monotonic() + retry_after
            logger.warning(f"adsbdb rate limited, backoff {retry_after}s")
            return None, False

        if resp.status_code == 200:
            data = resp.json().get('response', {}).get('flightroute')
            if data:
                def airport_info(a: dict) -> dict:
                    return {
                        'icao':         a.get('icao_code', ''),
                        'code':         a.get('iata_code') or a.get('icao_code', ''),
                        'name':         a.get('name', ''),
                        'municipality': a.get('municipality', ''),
                        'country':      a.get('country_iso_name', ''),
                        'lat':          a.get('latitude'),
                        'lon':          a.get('longitude'),
                    }
                route = {
                    'origin':      airport_info(data.get('origin') or {}),
                    'destination': airport_info(data.get('destination') or {}),
                }
                await redis_client.setex(key, ROUTE_CACHE_TTL, json.dumps(route))
                return route, False
        await redis_client.setex(key, ROUTE_CACHE_TTL, json.dumps(None))
        if resp.status_code not in (400, 404, 200, 429):
            logger.warning(f"adsbdb route {callsign}: HTTP {resp.status_code}")
    except Exception as e:
        logger.debug(f"Route fetch error {callsign}: {e}")
    return None, False


def _route_progress(plane: dict, route: dict) -> float | None:
    try:
        o = route['origin']
        d = route['destination']
        olat, olon = o['lat'], o['lon']
        dlat, dlon = d['lat'], d['lon']
        plat, plon = plane['lat'], plane['lon']
        total = math.sqrt((dlat - olat) ** 2 + (dlon - olon) ** 2)
        if total < 1e-6:
            return None
        covered = math.sqrt((plat - olat) ** 2 + (plon - olon) ** 2)
        return round(max(0.0, min(1.0, covered / total)), 3)
    except (KeyError, TypeError):
        return None


def _airport_label(airport: dict, route_display: str) -> str:
    if route_display == 'hidden':
        return ''
    if route_display == 'cities':
        city    = (airport.get('municipality', '') or '')[:20].upper()
        country = airport.get('country', '')
        return f"{city} ({country})" if city and country else city or country
    return airport.get('code') or airport.get('icao', '')


async def enrich_with_routes(aircraft: list, route_display: str = 'codes') -> None:
    callsigns = [a.get('flight', '').strip() for a in aircraft]
    if not any(callsigns):
        return

    # Single MGET round-trip for all callsigns
    raw_values = await redis_client.mget(*[route_key(cs) if cs else '' for cs in callsigns])

    routes: list[dict | None] = []
    hits = 0
    fetch_indices: list[int] = []
    for i, (cs, raw) in enumerate(zip(callsigns, raw_values)):
        if not cs:
            routes.append(None)
        elif raw is not None:
            routes.append(json.loads(raw))
            hits += 1
        else:
            routes.append(None)
            fetch_indices.append(i)

    # Fetch only callsigns not yet in Redis
    if fetch_indices:
        fetched = await asyncio.gather(*[fetch_route(callsigns[i]) for i in fetch_indices])
        for i, (route, _) in zip(fetch_indices, fetched):
            routes[i] = route

    resolved = 0
    for plane, route in zip(aircraft, routes):
        if not route:
            continue
        origin   = _airport_label(route.get('origin', {}), route_display)
        dest     = _airport_label(route.get('destination', {}), route_display)
        progress = _route_progress(plane, route)
        if origin:
            plane['origin'] = origin
        if dest:
            plane['dest'] = dest
        if progress is not None:
            plane['progress'] = progress
        if origin or dest:
            resolved += 1

    total_cs = sum(1 for cs in callsigns if cs)
    logger.info(f"routes: {total_cs} w/ callsign — {hits} cached, {len(fetch_indices)} fetched, {resolved} resolved")


# ---------------------------------------------------------------------------
# HTTP handlers
# ---------------------------------------------------------------------------

@app.route('/')
async def get_planes():
    if not check_ip_whitelist():
        return jsonify({'error': 'Access denied'}), 403

    lat           = request.args.get('lat', type=float)
    lon           = request.args.get('lon', type=float)
    address       = request.args.get('address', type=str)
    show_ground   = request.args.get('show_ground', 'false').lower() == 'true'
    route_display = request.args.get('route_display', 'codes')

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
        await enrich_with_routes(data.get('ac', []), route_display)
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
    global api_queue, redis_client, TRMNL_IPS, _providers, _route_semaphore

    _providers = _load_providers()
    _route_semaphore = asyncio.Semaphore(5)  # max 5 concurrent adsbdb requests

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

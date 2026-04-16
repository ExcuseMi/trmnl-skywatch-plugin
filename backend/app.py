import os
import asyncio
import aiosqlite
import httpx
import time
import json
import logging
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import math

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
CACHE_MINUTES = 5
DB_PATH = '/data/skywatch_cache.db'
ENABLE_IP_WHITELIST = os.getenv('ENABLE_IP_WHITELIST', 'false').lower() == 'true'
IP_REFRESH_HOURS = 24

# TRMNL server IPs
TRMNL_IPS = set()
last_ip_refresh = None
scheduler = None

# Rate limiting lock/semaphore to ensure 1 request per second
last_api_call_time = 0
api_lock = asyncio.Lock()

# Ensure directories exist
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

async def fetch_trmnl_ips():
    """Fetch TRMNL server IPs from their API"""
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

def update_trmnl_ips_sync():
    global TRMNL_IPS, last_ip_refresh
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        TRMNL_IPS = loop.run_until_complete(fetch_trmnl_ips())
        last_ip_refresh = datetime.now()
    finally:
        loop.close()

async def purge_cache():
    """Delete old cache entries to keep the DB small"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # Purge plane cache older than 1 hour (it's a 5-min cache)
            await db.execute("DELETE FROM plane_cache WHERE fetched_at < ?", 
                             ((datetime.now() - timedelta(hours=1)).isoformat(),))
            # Purge geocoding cache older than 30 days
            await db.execute("DELETE FROM geocoding_cache WHERE cached_at < ?", 
                             ((datetime.now() - timedelta(days=30)).isoformat(),))
            await db.commit()
        logger.info("Background task: Purged old cache data")
    except Exception as e:
        logger.error(f"Error purging cache: {e}")

def start_schedulers():
    global scheduler
    scheduler = BackgroundScheduler(daemon=True)
    
    # Refresh TRMNL IPs every 24 hours if enabled
    if ENABLE_IP_WHITELIST:
        scheduler.add_job(func=update_trmnl_ips_sync, trigger='interval', hours=IP_REFRESH_HOURS)
    
    # Purge old cache data every 24 hours
    scheduler.add_job(func=lambda: asyncio.run(purge_cache()), trigger='interval', hours=24)
    
    scheduler.start()
    logger.info("Started background schedulers")

def check_ip_whitelist():
    if not ENABLE_IP_WHITELIST: return True
    client_ip = (request.headers.get('CF-Connecting-IP') or 
                 request.headers.get('X-Forwarded-For', '').split(',')[0].strip() or 
                 request.remote_addr)
    return client_ip in TRMNL_IPS

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS plane_cache (
                lat_grid REAL,
                lon_grid REAL,
                data_json TEXT,
                fetched_at TIMESTAMP,
                PRIMARY KEY (lat_grid, lon_grid)
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

async def geocode_address(address):
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute('SELECT lat, lon FROM geocoding_cache WHERE address = ?', (address,))
        row = await cursor.fetchone()
        if row: return {'lat': row[0], 'lon': row[1]}

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
                        await db.execute('INSERT OR REPLACE INTO geocoding_cache VALUES (?, ?, ?, ?)',
                                       (address, lat, lon, datetime.now().isoformat()))
                        await db.commit()
                    return {'lat': lat, 'lon': lon}
    except Exception as e:
        logger.error(f"Geocoding error: {e}")
    return None

def reduce_payload(raw_data):
    """Filter aircraft data to only what transform.js needs"""
    ac_list = raw_data.get('ac', [])
    reduced_ac = []
    for a in ac_list:
        reduced_ac.append({
            'hex': a.get('hex', ''),
            'flight': (a.get('flight', '')).strip(),
            'r': a.get('r', ''),
            't': a.get('t', ''),
            'alt_baro': a.get('alt_baro'),
            'gs': a.get('gs'),
            'track': a.get('track'),
            'baro_rate': a.get('baro_rate', 0),
            'lat': a.get('lat'),
            'lon': a.get('lon')
        })
    return {
        'ac': reduced_ac,
        'total': raw_data.get('total', len(reduced_ac))
    }

async def fetch_planes(lat, lon):
    global last_api_call_time
    
    # Grid coordinates to 0.01 (~1km) for better caching
    lat_grid = round(lat, 2)
    lon_grid = round(lon, 2)

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            'SELECT data_json, fetched_at FROM plane_cache WHERE lat_grid = ? AND lon_grid = ?',
            (lat_grid, lon_grid)
        )
        row = await cursor.fetchone()
        if row:
            data_json, fetched_at = row
            if datetime.now() - datetime.fromisoformat(fetched_at) < timedelta(minutes=CACHE_MINUTES):
                logger.info(f"Cache hit for {lat_grid}, {lon_grid}")
                return json.loads(data_json)

    # Rate limiting: 1 request per second
    async with api_lock:
        now = time.time()
        sleep_time = max(0, 1.0 - (now - last_api_call_time))
        if sleep_time > 0:
            await asyncio.sleep(sleep_time)
        
        url = f"https://api.airplanes.live/v2/point/{lat}/{lon}/50"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url)
                last_api_call_time = time.time()
                response.raise_for_status()
                raw_data = response.json()
                reduced_data = reduce_payload(raw_data)
                
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        'INSERT OR REPLACE INTO plane_cache VALUES (?, ?, ?, ?)',
                        (lat_grid, lon_grid, json.dumps(reduced_data), datetime.now().isoformat())
                    )
                    await db.commit()
                return reduced_data
        except Exception as e:
            logger.error(f"API Error: {e}")
            return None

@app.route('/')
async def get_planes():
    if not check_ip_whitelist():
        return jsonify({'error': 'Access denied'}), 403

    lat = request.args.get('lat', type=float)
    lon = request.args.get('lon', type=float)
    address = request.args.get('address', type=str)

    if address:
        geo = await geocode_address(address)
        if geo:
            lat, lon = geo['lat'], geo['lon']
        else:
            return jsonify({'error': 'Location not found'}), 400

    if lat is None or lon is None:
        return jsonify({'error': 'Missing lat/lon or address'}), 400

    data = await fetch_planes(lat, lon)
    if data:
        # Add metadata for the plugin
        data['fetched_at_utc'] = datetime.now(timezone.utc).isoformat()
        data['lat'] = lat
        data['lon'] = lon
        return jsonify(data)
    return jsonify({'error': 'Failed to fetch data'}), 500

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'ip_whitelist': ENABLE_IP_WHITELIST})

async def startup():
    await init_db()
    if ENABLE_IP_WHITELIST:
        global TRMNL_IPS, last_ip_refresh
        TRMNL_IPS = await fetch_trmnl_ips()
        last_ip_refresh = datetime.now()
    
    start_schedulers()

asyncio.run(startup())

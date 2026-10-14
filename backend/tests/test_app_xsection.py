"""The /skywatch handler: towns only for view=xsection."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app as backend  # noqa: E402


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = value

    async def setex(self, key, ttl, value):
        self.store[key] = value

    async def mget(self, *keys):
        return [self.store.get(k) for k in keys]


def call(monkeypatch, query):
    fake = FakeRedis()

    async def planes(lat, lon, show_ground):
        return {'ac': [{'lat': lat + 0.1, 'lon': lon, 'flight': ''}], 'provider': 'x', 'fetched_at_utc': 'now'}

    async def airports(a, b):
        return []

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(backend, 'redis_client', fake)
    monkeypatch.setattr(backend, 'fetch_planes', planes)
    monkeypatch.setattr(backend, 'fetch_airports', airports)
    monkeypatch.setattr(backend, 'increment_stat', noop)
    monkeypatch.setattr(backend, 'enrich_with_routes', noop)
    fake.store[backend.CITIES_CACHE_KEY] = json.dumps([{'name': 'Kortrijk', 'lat': 50.83, 'lon': 3.26, 'pop': 73879}])

    async def go():
        client = backend.app.test_client()
        resp = await client.get('/?lat=50.8&lon=3.3&' + query)
        return resp.status_code, await resp.get_json()

    status, body = asyncio.run(go())
    return status, body


def test_towns_only_for_xsection(monkeypatch):
    status, body = call(monkeypatch, 'view=xsection')
    assert status == 200 and [c['name'] for c in body['data']['cities']] == ['Kortrijk']
    status, body = call(monkeypatch, 'view=radar')
    assert status == 200 and 'cities' not in body['data']
    status, body = call(monkeypatch, '')
    assert status == 200 and 'cities' not in body['data']


def test_no_terrain_is_ever_sent(monkeypatch):
    for query in ('view=xsection', 'view=xsection&terrain=true'):
        status, body = call(monkeypatch, query)
        assert status == 200 and 'terrain' not in body['data']

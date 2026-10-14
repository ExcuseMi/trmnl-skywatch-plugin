"""The /skywatch handler: terrain and towns only for view=xsection, and a terrain failure never fails the request."""
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


GRID = {'step_nm': 2, 'bearings': 16, 'home_m': 100, 'grid': [[1] * 25 for _ in range(16)]}


def call(monkeypatch, query, terrain_result, seed=None):
    fake = FakeRedis()
    asked = {'terrain': 0}

    async def planes(lat, lon, show_ground):
        return {'ac': [{'lat': lat + 0.1, 'lon': lon, 'flight': ''}], 'provider': 'x', 'fetched_at_utc': 'now'}

    async def airports(a, b):
        return []

    async def noop(*a, **k):
        return None

    async def fake_terrain(lat, lon, client, **k):
        asked['terrain'] += 1
        if isinstance(terrain_result, Exception):
            raise terrain_result
        return terrain_result

    monkeypatch.setattr(backend, 'redis_client', fake)
    monkeypatch.setattr(backend, 'fetch_planes', planes)
    monkeypatch.setattr(backend, 'fetch_airports', airports)
    monkeypatch.setattr(backend, 'increment_stat', noop)
    monkeypatch.setattr(backend, 'enrich_with_routes', noop)
    monkeypatch.setattr(backend.terrain_tiles, 'fetch_terrain', fake_terrain)
    fake.store.update(seed or {})
    fake.store[backend.CITIES_CACHE_KEY] = json.dumps([{'name': 'Kortrijk', 'lat': 50.83, 'lon': 3.26, 'pop': 73879}])

    async def go():
        client = backend.app.test_client()
        resp = await client.get('/?lat=50.8&lon=3.3&' + query)
        return resp.status_code, await resp.get_json()

    status, body = asyncio.run(go())
    return status, body, asked, fake


def test_terrain_and_cities_only_for_xsection(monkeypatch):
    status, body, asked, fake = call(monkeypatch, 'view=xsection&terrain=true', GRID)
    assert status == 200 and body['data']['terrain'] == GRID
    assert [c['name'] for c in body['data']['cities']] == ['Kortrijk']
    assert any(k.startswith('skywatch:terrain:v1:') for k in fake.store)     # cached for next time

    status, body, asked, _ = call(monkeypatch, 'view=radar', GRID)
    assert status == 200 and 'terrain' not in body['data'] and 'cities' not in body['data']
    assert asked['terrain'] == 0                                              # no terrain fetch for the radar


def test_terrain_failure_returns_a_response_without_terrain(monkeypatch):
    for failure in (None, RuntimeError('boom')):
        status, body, _, fake = call(monkeypatch, 'view=xsection&terrain=true', failure)
        assert status == 200 and 'terrain' not in body['data'] and body['data']['ac']
        assert not any(k.startswith('skywatch:terrain:') for k in fake.store)  # a failure is not cached


def test_cached_terrain_is_not_fetched_again(monkeypatch):
    key = f"skywatch:terrain:v1:{round(50.8, 2)}:{round(3.3, 2)}"
    status, body, asked, _ = call(monkeypatch, 'view=xsection&terrain=true', None, seed={key: json.dumps(GRID)})
    assert status == 200 and body['data']['terrain'] == GRID and asked['terrain'] == 0


def test_no_terrain_fetch_when_the_terrain_setting_is_off_or_absent(monkeypatch):
    for query in ('view=xsection', 'view=xsection&terrain=false', 'view=radar&terrain=true'):
        status, body, asked, fake = call(monkeypatch, query, GRID)
        assert status == 200 and 'terrain' not in body['data'], query
        assert asked['terrain'] == 0, query
        assert not any(k.startswith('skywatch:terrain:') for k in fake.store), query
    status, body, _, _ = call(monkeypatch, 'view=xsection', GRID)
    assert [c['name'] for c in body['data']['cities']] == ['Kortrijk']      # towns do not depend on the terrain setting

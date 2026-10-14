import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import terrain  # noqa: E402

FIX = Path(__file__).parent / 'fixtures'
INNSBRUCK = (47.2692, 11.4041)
TILE = FIX / 'terrarium_9_272_179.png'


def run(coro):
    return asyncio.run(coro)


def test_terrarium_formula():
    assert terrain.decode_pixel(128, 0, 0) == 0
    assert terrain.decode_pixel(128, 10, 128) == 10.5
    assert terrain.decode_pixel(127, 0, 0) == -256


def test_tile_of_innsbruck():
    assert terrain.tile_of(*INNSBRUCK)[:2] == (272, 179)


def test_stored_tile_has_innsbruck_valley_and_nordkette():
    tile = terrain.decode_tile(TILE.read_bytes())
    tiles = {(272, 179): tile}
    home = terrain.sample(tiles, *INNSBRUCK)
    assert 520 < home < 640                      # Innsbruck lies at about 575 m
    hafelekar = terrain.sample(tiles, 47.3117, 11.3846)
    assert 1900 < hafelekar < 2500               # the Nordkette above it, up to 2334 m


def test_polar_grid_shape_and_values():
    tiles = {xy: terrain.decode_tile(TILE.read_bytes()) for xy in terrain.required_tiles(*INNSBRUCK)}
    grid = terrain.build_grid(*INNSBRUCK, tiles)
    assert grid['step_nm'] == 2 and grid['bearings'] == 16
    assert len(grid['grid']) == 16 and all(len(r) == 25 for r in grid['grid'])
    assert 520 < grid['home_m'] < 640
    assert all(isinstance(v, int) for row in grid['grid'] for v in row)
    # the real tile stands in for every neighbour, so only the centre point is meaningful: the grid is just well formed


def test_grid_is_none_when_a_tile_is_missing():
    tile = terrain.decode_tile(TILE.read_bytes())
    assert terrain.build_grid(*INNSBRUCK, {(272, 179): tile}) is None


def test_destination_north_is_one_degree_per_60_nm():
    lat, lon = terrain.destination(47.0, 11.0, 0, 60)
    assert abs(lat - 48.0) < 0.02 and abs(lon - 11.0) < 1e-6


def test_fetch_failure_returns_none_not_an_exception():
    def handler(request):
        return httpx.Response(500)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await terrain.fetch_terrain(*INNSBRUCK, client)

    assert run(go()) is None


def test_corrupt_tile_returns_none():
    def handler(request):
        return httpx.Response(200, content=b'not a png')

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await terrain.fetch_terrain(*INNSBRUCK, client)

    assert run(go()) is None


def test_fetch_builds_the_grid_from_tiles():
    png = TILE.read_bytes()

    def handler(request):
        return httpx.Response(200, content=png)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await terrain.fetch_terrain(*INNSBRUCK, client)

    grid = run(go())
    assert grid and len(grid['grid']) == 16 and 520 < grid['home_m'] < 640

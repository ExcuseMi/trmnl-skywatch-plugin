import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import cities  # noqa: E402

TEXT = (Path(__file__).parent / 'fixtures' / 'cities15000_excerpt.txt').read_text(encoding='utf-8')


def test_parse_reads_name_position_and_population():
    parsed = {c['name']: c for c in cities.parse_cities(TEXT)}
    assert parsed['Kortrijk']['pop'] == 73879
    assert abs(parsed['Kortrijk']['lat'] - 50.82803) < 1e-6 and abs(parsed['Kortrijk']['lon'] - 3.26487) < 1e-6


def test_names_the_font_lacks_fall_back_to_ascii():
    names = {c['name'] for c in cities.parse_cities(TEXT)}
    assert 'Moskva' in names and 'Москва' not in names


def test_bad_rows_are_skipped():
    assert cities.parse_cities('short\trow\n1\ta\tb\t\tnot\tnumbers\n') == []


def test_radius_filter_returns_the_most_populous_first_and_caps():
    parsed = cities.parse_cities(TEXT)
    near = cities.within(parsed, 50.8221, 3.3749, 50)      # Kortrijk
    names = [c['name'] for c in near]
    assert names[0] == 'Brussels'
    assert 'Kortrijk' in names and 'Roeselare' in names and 'Ieper' in names
    assert 'Tokyo' not in names and 'Innsbruck' not in names
    assert [c['pop'] for c in near] == sorted((c['pop'] for c in near), reverse=True)
    assert len(cities.within(parsed, 50.8221, 3.3749, 50, limit=2)) == 2

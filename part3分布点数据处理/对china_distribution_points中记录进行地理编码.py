# -*- coding: utf-8 -*-
"""
读取 data/triplets/china_distribution_points.csv，使用 geopy / Nominatim
对每条地点记录进行地理编码，输出经纬度及拆分后的行政信息。

默认会进行 1 秒限速，并对同一地点做本地缓存，避免重复请求。
"""

from __future__ import annotations

import csv
from pathlib import Path

from geopy.extra.rate_limiter import RateLimiter
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim


INPUT_FILE = Path('data/triplets/china_distribution_points.csv')
OUTPUT_FILE = Path('data/point/china_distribution_points_geocoded.csv')


class ChinaPointGeocoder:
    """对已筛选出的中国地点进行在线地理编码。"""

    def __init__(self):
        self.geolocator = Nominatim(user_agent='invasives_species_point_geocoder_v1')
        self.geocode = RateLimiter(
            self.geolocator.geocode,
            min_delay_seconds=1.0,
            max_retries=2,
            error_wait_seconds=2.0,
            swallow_exceptions=True,
        )
        self.cache: dict[str, dict[str, str | float]] = {}

    def _row_key(self, row: dict[str, str]) -> tuple[str, str, str, str, str, str]:
        """用完整业务字段识别是否是同一条数据。"""
        return (
            (row.get('species') or '').strip(),
            (row.get('location') or '').strip(),
            (row.get('admin_chain') or '').strip(),
            (row.get('year') or '').strip(),
            (row.get('status') or '').strip(),
            (row.get('property') or '').strip(),
        )

    def _has_coordinates(self, row: dict[str, str]) -> bool:
        """判断一条结果是否已经有可复用的经纬度。"""
        lat = (row.get('lat') or '').strip()
        lon = (row.get('lon') or '').strip()
        return bool(lat and lon)

    def _load_existing_output(self, file_path: Path) -> tuple[list[dict[str, str]], set[tuple[str, str, str, str, str, str]], dict[str, dict[str, str | float]]]:
        """读取已有地理编码结果，并建立去重和地址缓存。"""
        existing_rows: list[dict[str, str]] = []
        existing_keys: set[tuple[str, str, str, str, str, str]] = set()
        geo_cache: dict[str, dict[str, str | float]] = {}

        if not file_path.exists():
            return existing_rows, existing_keys, geo_cache

        with file_path.open('r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_rows.append(row)

                location = (row.get('location') or '').strip()
                admin_chain = (row.get('admin_chain') or '').strip()
                cache_key = location or admin_chain
                if self._has_coordinates(row):
                    existing_keys.add(self._row_key(row))

                if cache_key and cache_key not in geo_cache and self._has_coordinates(row):
                    cached_row = {
                        'geocode_query': (row.get('geocode_query') or '').strip(),
                        'lat': row.get('lat', ''),
                        'lon': row.get('lon', ''),
                        'province': row.get('province', ''),
                        'city': row.get('city', ''),
                        'district': row.get('district', ''),
                        'street': row.get('street', ''),
                    }

                    geo_cache[cache_key] = cached_row

        return existing_rows, existing_keys, geo_cache

    def _load_rows(self, file_path: Path) -> list[dict[str, str]]:
        if not file_path.exists():
            raise FileNotFoundError(f'未找到输入文件: {file_path}')

        with file_path.open('r', encoding='utf-8-sig', newline='') as f:
            return list(csv.DictReader(f))

    def _build_queries(self, location: str, admin_chain: str) -> list[str]:
        queries: list[str] = []

        if admin_chain:
            queries.append(f'{admin_chain}, China')

        if location:
            queries.append(f'{location}, China')

        if location and admin_chain:
            queries.append(f'{admin_chain}, {location}, China')

        deduped: list[str] = []
        seen = set()
        for query in queries:
            if query not in seen:
                seen.add(query)
                deduped.append(query)
        return deduped

    def _extract_address(self, geo) -> dict[str, str]:
        address = geo.raw.get('address', {}) if isinstance(getattr(geo, 'raw', None), dict) else {}
        return {
            'province': address.get('state', '') or address.get('province', '') or '',
            'city': address.get('city', '') or address.get('town', '') or address.get('municipality', '') or '',
            'district': address.get('county', '') or address.get('district', '') or '',
            'street': address.get('road', '') or address.get('neighbourhood', '') or address.get('hamlet', '') or '',
        }

    def geocode_one(self, row: dict[str, str]) -> dict[str, str | float]:
        species = (row.get('species') or '').strip()
        location = (row.get('location') or '').strip()
        admin_chain = (row.get('admin_chain') or '').strip()
        year = (row.get('year') or '').strip()

        result: dict[str, str | float] = {
            'species': species,
            'location': location,
            'admin_chain': admin_chain,
            'year': year,
            'status': (row.get('status') or '').strip(),
            'property': (row.get('property') or '').strip(),
            'geocode_query': '',
            'lat': '',
            'lon': '',
            'province': '',
            'city': '',
            'district': '',
            'street': '',
        }

        cache_key = admin_chain or location
        if cache_key and cache_key in self.cache:
            result.update(self.cache[cache_key])
            return result

        for query in self._build_queries(location, admin_chain):
            try:
                geo = self.geocode(query, timeout=10)
                if not geo:
                    continue

                address = self._extract_address(geo)
                result.update(
                    {
                        'geocode_query': query,
                        'lat': round(geo.latitude, 6),
                        'lon': round(geo.longitude, 6),
                        **address,
                    }
                )
                self.cache[cache_key] = {
                    'geocode_query': result['geocode_query'],
                    'lat': result['lat'],
                    'lon': result['lon'],
                    'province': result['province'],
                    'city': result['city'],
                    'district': result['district'],
                    'street': result['street'],
                }
                print(f"[OK] {location} -> ({result['lat']}, {result['lon']})")
                return result
            except GeocoderTimedOut:
                print(f"[TIMEOUT] {location}")
            except GeocoderServiceError as exc:
                print(f"[ERROR] {location} - {exc}")
            except Exception as exc:
                print(f"[EXCEPTION] {location} - {exc}")

        print(f"[FAIL] {location} 无地理编码结果")
        return result


def main() -> None:
    geocoder = ChinaPointGeocoder()
    rows = geocoder._load_rows(INPUT_FILE)
    existing_rows, existing_keys, existing_cache = geocoder._load_existing_output(OUTPUT_FILE)
    geocoder.cache.update(existing_cache)

    if not rows:
        print(f'未找到输入数据: {INPUT_FILE}')
        return

    print(f'读取到 {len(rows)} 条地点记录，开始地理编码...')
    if existing_rows:
        print(f'发现已有 {len(existing_rows)} 条结果，将复用已编码地址并跳过完全相同的数据')

    output_rows: list[dict[str, str | float]] = []
    seen_keys: set[tuple[str, str, str, str, str, str]] = set()

    for row in rows:
        row_key = geocoder._row_key(row)
        if row_key in seen_keys:
            print(f"[SKIP] {row.get('location', '').strip()} 重复输入行")
            continue
        seen_keys.add(row_key)

        if row_key in existing_keys:
            cached_row = next((item for item in existing_rows if geocoder._row_key(item) == row_key), None)
            if cached_row is not None:
                output_rows.append(cached_row)
                print(f"[SKIP] {row.get('location', '').strip()} 已存在，复用已有结果")
                continue

        output_rows.append(geocoder.geocode_one(row))

    fieldnames = [
        'species', 'location', 'admin_chain', 'year', 'status', 'property',
        'geocode_query', 'lat', 'lon', 'province', 'city', 'district', 'street',
    ]

    with OUTPUT_FILE.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    print(f'[OK] 已保存 {len(output_rows)} 条地理编码记录到 {OUTPUT_FILE}')


if __name__ == '__main__':
    main()
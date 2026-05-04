# -*- coding: utf-8 -*-
"""
合并 data/gbif_results 下各物种的 GBIF 记录，只保留 species、year、property、lat、lon。

输出规则：
- 只读取按物种拆分的 CSV，跳过已汇总文件
- property 统一写成 year=<年份>;status=分布
- 如果原始记录没有年份，则写成 year=null;status=分布
"""

from __future__ import annotations

import csv
from pathlib import Path


INPUT_DIR = Path('data/gbif_results')
OUTPUT_FILE = INPUT_DIR / 'gbif_species_merged_compact.csv'


def _read_rows(file_path: Path) -> list[dict[str, str]]:
    with file_path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def _detect_species(row: dict[str, str], file_path: Path) -> str:
    species = (row.get('species') or row.get('species_label') or '').strip()
    if species:
        return species
    return file_path.stem


def _extract_year(row: dict[str, str]) -> str:
    for key in ('year', 'date'):
        value = (row.get(key) or '').strip()
        if not value:
            continue
        if len(value) >= 4 and value[:4].isdigit():
            return value[:4]
    return ''


def _extract_lat(row: dict[str, str]) -> str:
    return (row.get('lat') or row.get('latitude') or '').strip()


def _extract_lon(row: dict[str, str]) -> str:
    return (row.get('lon') or row.get('lng') or row.get('longitude') or '').strip()


def main() -> None:
    if not INPUT_DIR.exists():
        raise FileNotFoundError(f'未找到输入目录: {INPUT_DIR}')

    output_rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()

    for file_path in sorted(INPUT_DIR.glob('*.csv')):
        if file_path.name in {'gbif_species_merged_compact.csv', 'gbif_dedup_by_admin_year.csv', 'distribution_all_species.csv', 'triplets_reported_in_dedup_by_admin_year.csv'}:
            continue

        rows = _read_rows(file_path)
        if not rows:
            continue

        for row in rows:
            species = _detect_species(row, file_path)
            year = _extract_year(row)
            lat = _extract_lat(row)
            lon = _extract_lon(row)

            if not species or not lat or not lon:
                continue

            property_value = f'year={year or "null"};status=目击'
            compact_row = {
                'species': species,
                'year': year,
                'property': property_value,
                'lat': lat,
                'lon': lon,
            }

            row_key = (species, year, property_value, lat, lon)
            if row_key in seen:
                continue
            seen.add(row_key)
            output_rows.append(compact_row)

    with OUTPUT_FILE.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=['species', 'year', 'property', 'lat', 'lon'])
        writer.writeheader()
        writer.writerows(output_rows)

    print(f'[OK] 已合并 {len(output_rows)} 条记录到 {OUTPUT_FILE}')


if __name__ == '__main__':
    main()
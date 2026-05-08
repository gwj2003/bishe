# -*- coding: utf-8 -*-
"""
将以下两个文件合并为一个新文件：
1) data/points/china_distribution_points_geocoded.csv
2) data/points/gbif_species_merged_admin_levels.csv

处理规则：
- china 文件删除 admin_chain、geocode_query、province、city、district、street 列
- 基于 lat/lon 重新赋值 province、city、district、address、ext_path
- 与 gbif 文件按统一字段拼接输出
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.strtree import STRtree


CHINA_INPUT = Path('data/points/china_distribution_points_geocoded.csv')
GBIF_INPUT = Path('data/points/gbif_species_merged_admin_levels.csv')
ADMIN_CSV = Path('data/admin_shapefiles/AreaCity_ok_geo/ok_geo.csv')
OUTPUT_FILE = Path('data/points/china_gbif_merged_admin_levels.csv')


def normalize_text(text) -> str:
    if text is None:
        return ''
    text = str(text).strip()
    if not text or text.lower() == 'nan':
        return ''
    text = text.replace('\u3000', ' ')
    return ' '.join(text.split())


def out_of_china(lng: float, lat: float) -> bool:
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def transform_lat(lng: float, lat: float) -> float:
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * math.pi) + 40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def transform_lng(lng: float, lat: float) -> float:
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * math.pi) + 40.0 * math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 * math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    if out_of_china(lng, lat):
        return lng, lat
    a = 6378245.0
    ee = 0.00669342162296594323
    dlat = transform_lat(lng - 105.0, lat - 35.0)
    dlng = transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lng + dlng, lat + dlat


def split_admin_path(ext_path: str):
    parts = [part for part in normalize_text(ext_path).split() if part]
    province = parts[0] if len(parts) > 0 else None
    city = parts[1] if len(parts) > 1 else None
    district = parts[2] if len(parts) > 2 else None
    if province and province.endswith('特别行政区'):
        if len(parts) <= 1 or all(part == province for part in parts):
            return province, None, None
        if city == province:
            city = None
        if district == province:
            district = None
    elif len(parts) == 2 and city == province:
        city = None
    return province, city, district


def format_admin_address(province, city, district):
    parts = [part for part in [province, city, district] if part]
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    if district:
        if city and city != province:
            return f'{province} {city} {district}'
        return f'{province} {district}'
    if city and city != province:
        return f'{province} {city}'
    return province


def boundary_depth_value(props: dict) -> int:
    value = props.get('deep')
    try:
        return int(float(value))
    except Exception:
        ext_path = normalize_text(props.get('ext_path'))
        return len([part for part in ext_path.split() if part])


def load_admin_boundaries(csv_path: Path):
    if not csv_path.exists():
        raise FileNotFoundError(f'未找到行政边界文件: {csv_path}')

    df = pd.read_csv(csv_path, dtype=str, low_memory=False)
    need_cols = [c for c in ['ext_path', 'name', 'polygon'] if c not in df.columns]
    if need_cols:
        raise ValueError(f'ok_geo.csv 缺少必要字段: {need_cols}')

    geometries = []
    properties = []
    for _, row in df.iterrows():
        polygon_text = normalize_text(row.get('polygon'))
        if not polygon_text or polygon_text == 'EMPTY':
            continue

        try:
            parts = []
            for block in polygon_text.split(';'):
                block = block.strip()
                if not block:
                    continue

                coords = []
                for pair in block.split(','):
                    pair = pair.strip()
                    if not pair:
                        continue
                    lng_str, lat_str = pair.split()
                    coords.append((float(lng_str), float(lat_str)))

                if len(coords) >= 3:
                    parts.append(Polygon(coords))

            if not parts:
                continue

            geometry = parts[0] if len(parts) == 1 else MultiPolygon(parts)
            if geometry.is_empty:
                continue

            geometries.append(geometry)
            properties.append({
                'name': normalize_text(row.get('name')),
                'ext_path': normalize_text(row.get('ext_path')),
                'deep': row.get('deep'),
                'id': row.get('id'),
            })
        except Exception:
            continue

    if not geometries:
        raise RuntimeError('行政边界文件中没有可用多边形')

    return STRtree(geometries), geometries, properties


def choose_best_boundary(point: Point, candidate_indices, admin_geometries, admin_properties):
    best_index = None
    best_depth = -1
    best_path_len = -1

    for candidate_index in candidate_indices:
        i = int(candidate_index)
        geometry = admin_geometries[i]
        if not geometry.covers(point):
            continue

        props = admin_properties[i]
        depth = boundary_depth_value(props)
        path_len = len([part for part in normalize_text(props.get('ext_path')).split() if part])
        if depth > best_depth or (depth == best_depth and path_len > best_path_len):
            best_index = i
            best_depth = depth
            best_path_len = path_len

    return best_index, best_depth, best_path_len


def find_best_boundary(point: Point, admin_tree, admin_geometries, admin_properties):
    candidate_indices = admin_tree.query(point)
    best_index, best_depth, best_path_len = choose_best_boundary(point, candidate_indices, admin_geometries, admin_properties)
    return best_index, best_depth, best_path_len


def assign_admin_by_latlon(df: pd.DataFrame, admin_tree, admin_geometries, admin_properties) -> pd.DataFrame:
    out_rows = []
    for _, row in df.iterrows():
        lat = float(row['lat'])
        lon = float(row['lon'])

        gcj_lng, gcj_lat = wgs84_to_gcj02(lon, lat)
        best_index, best_depth, best_path_len = find_best_boundary(Point(gcj_lng, gcj_lat), admin_tree, admin_geometries, admin_properties)
        raw_index, raw_depth, raw_path_len = find_best_boundary(Point(lon, lat), admin_tree, admin_geometries, admin_properties)

        if raw_index is not None and (
            best_index is None
            or raw_depth > best_depth
            or (raw_depth == best_depth and raw_path_len > best_path_len)
        ):
            best_index = raw_index

        ext_path = None
        province = None
        city = None
        district = None
        if best_index is not None:
            props = admin_properties[best_index]
            ext_path = props.get('ext_path')
            province, city, district = split_admin_path(ext_path)

        if not ext_path:
            continue

        out = row.to_dict()
        out.update(
            {
                'province': province,
                'city': city,
                'district': district,
                'address': format_admin_address(province, city, district),
                'ext_path': ext_path,
            }
        )
        out_rows.append(out)

    return pd.DataFrame(out_rows)


def load_china_cleaned(file_path: Path) -> pd.DataFrame:
    if not file_path.exists():
        raise FileNotFoundError(f'未找到输入文件: {file_path}')

    df = pd.read_csv(file_path, dtype=str, low_memory=False)
    for col in ['species', 'year', 'property', 'lat', 'lon']:
        if col not in df.columns:
            df[col] = ''

    # 按需求删除列，再重建行政区字段
    drop_cols = ['admin_chain', 'geocode_query', 'province', 'city', 'district', 'street']
    df = df.drop(columns=[c for c in drop_cols if c in df.columns]).copy()
    df['lat'] = pd.to_numeric(df['lat'], errors='coerce')
    df['lon'] = pd.to_numeric(df['lon'], errors='coerce')
    df = df.dropna(subset=['lat', 'lon']).copy()
    return df


def load_gbif(file_path: Path) -> pd.DataFrame:
    if not file_path.exists():
        raise FileNotFoundError(f'未找到输入文件: {file_path}')
    df = pd.read_csv(file_path, dtype=str, low_memory=False)
    for col in ['species', 'year', 'property', 'lat', 'lon', 'province', 'city', 'district', 'address', 'ext_path']:
        if col not in df.columns:
            df[col] = ''
    return df


def main() -> None:
    admin_tree, admin_geometries, admin_properties = load_admin_boundaries(ADMIN_CSV)

    china_df = load_china_cleaned(CHINA_INPUT)
    china_admin_df = assign_admin_by_latlon(china_df, admin_tree, admin_geometries, admin_properties)

    gbif_df = load_gbif(GBIF_INPUT)

    final_cols = ['species', 'year', 'property', 'lat', 'lon', 'province', 'city', 'district', 'address', 'ext_path']
    for col in final_cols:
        if col not in china_admin_df.columns:
            china_admin_df[col] = ''
        if col not in gbif_df.columns:
            gbif_df[col] = ''

    merged_df = pd.concat([gbif_df[final_cols], china_admin_df[final_cols]], ignore_index=True)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    merged_df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8', lineterminator='\n')

    print(f'[OK] GBIF 行数: {len(gbif_df)}')
    print(f'[OK] china 行数(重建后): {len(china_admin_df)}')
    print(f'[OK] 合并后总行数: {len(merged_df)}')
    print(f'[OK] 输出文件: {OUTPUT_FILE}')


if __name__ == '__main__':
    main()

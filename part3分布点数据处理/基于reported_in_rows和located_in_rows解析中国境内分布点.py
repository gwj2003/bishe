# -*- coding: utf-8 -*-
"""
先基于 data/points/reported_in_rows.csv 和 data/points/located_in_rows.csv
解析出中国境内的精确分布点，输出物种名、地点、行政链、年份和状态。

规则：
- 只保留区县级及更精确的地点，如“青岛市黄岛区”“厦门同安放生池”“广州市白云区槎龙社区”
- 省级、市级等过于宽泛的地点不编码
- 每条记录对应一个年份；若同一地点在多个年份出现，则输出多条记录
"""

from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

CHINA_PROVINCES = {
    '北京市', '天津市', '河北省', '山西省', '内蒙古自治区',
    '辽宁省', '吉林省', '黑龙江省', '上海市', '江苏省',
    '浙江省', '安徽省', '福建省', '江西省', '山东省',
    '河南省', '湖北省', '湖南省', '广东省', '广西壮族自治区',
    '海南省', '重庆市', '四川省', '贵州省', '云南省',
    '西藏自治区', '陕西省', '甘肃省', '青海省', '宁夏回族自治区',
    '新疆维吾尔自治区', '台湾省', '香港特别行政区', '澳门特别行政区'
}

PRECISION_PATTERN = re.compile(
    r'(区|县|镇|乡|街道|社区|村|小区|公园|中心公园|风景区|景区|山庄|寺|庙|'
    r'放生池|人工湖|景观池|水库|水塘|广场)$'
)

WEAK_NATURAL_SUFFIXES = ('湖', '湖泊', '河', '河流', '河口', '港', '港口', '湾', '湿地')

BROAD_LOCATION_KEYWORDS = (
    '地区', '流域', '沿海', '沿岸', '周边', '范围', '区域', '华北', '华东', '华中',
    '华南', '华西', '华北地区', '华东地区', '华中地区', '华南地区', '华西地区',
    '东南沿海', '中国各省份', '全国', '亚洲', '北美洲', '南美洲', '欧洲', '非洲',
    '大洋洲', '海湾', '海域'
)


def is_precise_location(location: str) -> bool:
    """判断地点是否足够精确，排除省市级地点。"""
    if not location:
        return False

    location = location.strip()

    if any(keyword in location for keyword in BROAD_LOCATION_KEYWORDS):
        return False

    if location in CHINA_PROVINCES:
        return False

    # 纯“xx市”级别直接排除；带区县/景点等细粒度信息则保留
    if re.fullmatch(r'.+市', location) and not PRECISION_PATTERN.search(location):
        return False

    # 含省级名称但没有精确标记的，排除
    if any(province in location for province in CHINA_PROVINCES):
        if PRECISION_PATTERN.search(location):
            return True
        return any(location.endswith(suffix) for suffix in WEAK_NATURAL_SUFFIXES)

    # 没有省市名时，只保留明确的场景点，单独自然地名默认排除
    if PRECISION_PATTERN.search(location):
        return True

    return False


def extract_year(prop: str) -> str:
    """从 Property 字段中提取单个年份；没有则返回空字符串。"""
    if not prop:
        return ''

    match = re.search(r'year=([^;]+)', prop)
    if not match:
        return ''

    year_text = match.group(1)
    year_match = re.search(r'(19\d{2}|20\d{2})', year_text)
    if not year_match:
        return ''

    year = year_match.group(1)
    if 1900 <= int(year) <= 2099:
        return year
    return ''


class LocationGeocoder:
    """提取并整理精确地点记录。"""

    def __init__(self):
        self.location_parents = self._load_location_parents()
        self.records = self._load_precise_records()

    def _format_admin_chain(self, chain: list[str]) -> str:
        """把地点链整理成省、市、区县/地点的顺序，并用逗号连接。"""
        if not chain:
            return ''

        ordered = list(reversed(chain))
        return ','.join(ordered)

    def _load_rows_from_csv(self, file_path: Path) -> list[dict[str, str]]:
        """读取一个关系 CSV。"""
        rows: list[dict[str, str]] = []
        if not file_path.exists():
            return rows

        try:
            with open(file_path, 'r', encoding='utf-8-sig', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
        except Exception as exc:
            print(f'读取失败: {file_path} - {exc}')

        return rows

    def _load_location_parents(self) -> dict[str, set[str]]:
        """从 LOCATED_IN CSV 中加载地点到上级地点的映射。"""
        parents = defaultdict(set)
        triplets_dir = Path('data/points')
        located_csv = triplets_dir / 'located_in_rows.csv'

        rows = self._load_rows_from_csv(located_csv)

        for row in rows:
            if row.get('Relationship', '').strip() != 'LOCATED_IN':
                continue

            child = row.get('Entity1', '').strip()
            parent = row.get('Entity2', '').strip()
            if child and parent:
                parents[child].add(parent)

        return parents

    def _extract_status(self, prop: str) -> str:
        """从 Property 中提取状态字段。"""
        if not prop:
            return ''

        match = re.search(r'status=([^;]+)', prop)
        if match:
            return match.group(1).strip()
        return ''

    def _resolve_domestic_chain(self, location: str) -> list[str]:
        """沿 LOCATED_IN 向上追溯，找到通往中国的行政链。"""
        if not location:
            return []

        china_aliases = {
            '中国', '中华人民共和国', '中国大陆', '中国内地', '中国香港', '香港',
            '中国澳门', '澳门', '中国台湾', '台湾'
        }

        queue: list[tuple[str, list[str]]] = [(location, [location])]
        visited = set()

        while queue:
            current, path = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)

            if current in CHINA_PROVINCES or current in china_aliases:
                return path

            for parent in sorted(self.location_parents.get(current, set())):
                next_path = path + [parent]
                if parent in CHINA_PROVINCES or parent in china_aliases:
                    return next_path
                queue.append((parent, next_path))

        return []

    def _is_domestic_by_located_in(self, location: str) -> bool:
        """通过 LOCATED_IN 链路判断地点是否位于中国国内。"""
        return bool(self._resolve_domestic_chain(location))

    def _load_precise_records(self) -> list[dict[str, str]]:
        """从 REPORTED_IN CSV 里加载精确地点、年份和行政链。"""
        records: list[dict[str, str]] = []
        triplets_dir = Path('data/points')
        reported_csv = triplets_dir / 'reported_in_rows.csv'

        rows = self._load_rows_from_csv(reported_csv)

        for row in rows:
            if row.get('Relationship', '').strip() != 'REPORTED_IN':
                continue

            species_name = row.get('species', '').strip() or row.get('Entity1', '').strip()
            location = row.get('Entity2', '').strip()
            if not species_name or not location:
                continue
            if not is_precise_location(location):
                continue

            admin_chain = self._resolve_domestic_chain(location)
            if not admin_chain:
                continue

            year = extract_year(row.get('Property', '').strip())
            status = self._extract_status(row.get('Property', '').strip())
            records.append(
                {
                    'species': species_name,
                    'location': location,
                    'admin_chain': self._format_admin_chain(admin_chain),
                    'year': year,
                    'status': status,
                    'property': row.get('Property', '').strip(),
                }
            )

        return records

def process_all_species():
    triplets_dir = Path('data/points')
    resolved_output = triplets_dir / 'china_distribution_points.csv'

    geocoder = LocationGeocoder()

    if not geocoder.records:
        print('未找到符合条件的精确地点记录')
        return

    species_names = sorted({row['species'] for row in geocoder.records})
    print(f'找到 {len(species_names)} 个物种，共 {len(geocoder.records)} 条精确地点记录')

    with open(resolved_output, 'w', newline='', encoding='utf-8-sig') as f:
        resolved_fieldnames = ['species', 'location', 'admin_chain', 'year', 'status', 'property']
        resolved_writer = csv.DictWriter(f, fieldnames=resolved_fieldnames)
        resolved_writer.writeheader()
        resolved_writer.writerows(geocoder.records)

    print(f'[OK] 已保存 {len(geocoder.records)} 条解析记录到 {resolved_output}')
    print('已移除内置地理编码流程，请使用新的地理编码脚本处理后续步骤')


if __name__ == '__main__':
    process_all_species()
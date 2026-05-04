# -*- coding: utf-8 -*-
"""
批量清洗 data/triplets 下的 *_triplets.csv：
1) 删除 Relationship 为 LOCATED_IN 或 REPORTED_IN 的行
2) 每个物种输出一份清洗后文件到 data/triplets/cleaned
3) 合并所有清洗后数据到一个总文件
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd


INPUT_DIR = Path('data/triplets')
CLEANED_DIR = INPUT_DIR / 'cleaned'
MERGED_OUTPUT = INPUT_DIR / 'all_species_triplets_no_located_reported.csv'

DROP_RELATIONS = {'LOCATED_IN', 'REPORTED_IN'}


def normalize_relation(value: object) -> str:
    if value is None:
        return ''
    return str(value).strip().upper()


def clean_one_file(file_path: Path) -> tuple[pd.DataFrame, int, int]:
    df = pd.read_csv(file_path, dtype=str, low_memory=False)

    if 'Relationship' not in df.columns:
        df['Relationship'] = ''

    relation_upper = df['Relationship'].map(normalize_relation)
    keep_mask = ~relation_upper.isin(DROP_RELATIONS)

    cleaned = df.loc[keep_mask].copy()
    dropped = int((~keep_mask).sum())

    species = file_path.name.replace('_triplets.csv', '')
    cleaned['species_source'] = species

    return cleaned, len(df), dropped


def main() -> None:
    if not INPUT_DIR.exists():
        raise FileNotFoundError(f'未找到目录: {INPUT_DIR}')

    files = sorted(INPUT_DIR.glob('*_triplets.csv'))
    if not files:
        raise FileNotFoundError(f'未找到 *_triplets.csv: {INPUT_DIR}')

    CLEANED_DIR.mkdir(parents=True, exist_ok=True)

    merged_parts: list[pd.DataFrame] = []
    total_rows = 0
    total_dropped = 0

    for file_path in files:
        cleaned, before_count, dropped_count = clean_one_file(file_path)
        total_rows += before_count
        total_dropped += dropped_count
        merged_parts.append(cleaned)

        output_file = CLEANED_DIR / file_path.name
        cleaned.to_csv(output_file, index=False, encoding='utf-8-sig', lineterminator='\n')
        print(f'[OK] {file_path.name}: 原始 {before_count} 行, 删除 {dropped_count} 行, 保留 {len(cleaned)} 行')

    merged_df = pd.concat(merged_parts, ignore_index=True)
    merged_df.to_csv(MERGED_OUTPUT, index=False, encoding='utf-8-sig', lineterminator='\n')

    print(f'[OK] 已输出清洗目录: {CLEANED_DIR}')
    print(f'[OK] 已输出合并文件: {MERGED_OUTPUT}')
    print(f'[OK] 全部原始行数: {total_rows}, 共删除: {total_dropped}, 合并后: {len(merged_df)}')


if __name__ == '__main__':
    main()

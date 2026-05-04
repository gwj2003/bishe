# -*- coding: utf-8 -*-
"""
合并 GBIF 和 triplets 的分布点数据为单一 CSV
输出：data/gbif_results/distribution_all_species.csv
"""
import os
import pandas as pd

GBIF_PATH = "data/gbif_results/gbif_dedup_by_admin_year.csv"
TRIPLETS_PATH = "data/gbif_results/triplets_reported_in_dedup_by_admin_year.csv"
OUTPUT_PATH = "data/gbif_results/distribution_all_species.csv"

def merge_distribution_data():
    """合并两个来源的分布数据"""
    frames = []
    
    # 1. 读取 GBIF 数据
    if os.path.exists(GBIF_PATH):
        try:
            gbif_df = pd.read_csv(GBIF_PATH, encoding="utf-8", dtype={'year': str})
            # 将 year 转换为 Int64 类型（支持 NaN）
            gbif_df['year'] = pd.to_numeric(gbif_df['year'], errors='coerce').astype('Int64')
            gbif_df["data_source"] = "GBIF"
            frames.append(gbif_df)
            print(f"✓ 已加载 GBIF 数据：{len(gbif_df)} 行")
        except Exception as e:
            print(f"✗ GBIF 数据读取失败：{e}")
    else:
        print(f"✗ GBIF 数据文件不存在：{GBIF_PATH}")
    
    # 2. 读取 triplets 数据
    if os.path.exists(TRIPLETS_PATH):
        try:
            triplets_df = pd.read_csv(TRIPLETS_PATH, encoding="utf-8", dtype={'year': str})
            # 将 year 转换为 Int64 类型（支持 NaN）
            triplets_df['year'] = pd.to_numeric(triplets_df['year'], errors='coerce').astype('Int64')
            triplets_df["data_source"] = "Triplets"
            frames.append(triplets_df)
            print(f"✓ 已加载 Triplets 数据：{len(triplets_df)} 行")
        except Exception as e:
            print(f"✗ Triplets 数据读取失败：{e}")
    else:
        print(f"✗ Triplets 数据文件不存在：{TRIPLETS_PATH}")
    
    if not frames:
        raise RuntimeError("没有可用的数据源")
    
    # 3. 合并所有数据
    merged_df = pd.concat(frames, ignore_index=True, sort=False)
    
    # 4. 标准化列顺序，确保关键字段在前
    key_cols = ["species_label", "lat", "lng", "province", "city", "district", "address", "year", "count", "data_source"]
    other_cols = [c for c in merged_df.columns if c not in key_cols]
    col_order = key_cols + other_cols
    merged_df = merged_df[[c for c in col_order if c in merged_df.columns]]
    
    # 5. 去重汇总：按 species_label + year + lat + lng 去重并求和 count
    # （假设同一物种同一年同一坐标的多条记录应该被合并计数）
    groupby_cols = ["species_label", "year", "lat", "lng"]
    agg_dict = {"count": "sum", "province": "first", "city": "first", "district": "first", "address": "first", "data_source": lambda x: "/".join(set(x))}
    
    merged_df = merged_df.groupby(groupby_cols, dropna=False).agg(agg_dict).reset_index()
    
    # 6. 排序
    merged_df = merged_df.sort_values(["species_label", "year", "province", "city", "district"], kind="stable").reset_index(drop=True)
    
    # 7. 保存（Int64 类型会自动在 CSV 中表现为整数或空值，不含 .0）
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    merged_df.to_csv(OUTPUT_PATH, index=False, encoding="utf-8", lineterminator="\n")
    
    print(f"\n✓ 合并完成！")
    print(f"  总行数：{len(merged_df)}")
    print(f"  物种数：{merged_df['species_label'].nunique()}")
    print(f"  输出路径：{OUTPUT_PATH}")
    
    return merged_df


if __name__ == "__main__":
    merge_distribution_data()

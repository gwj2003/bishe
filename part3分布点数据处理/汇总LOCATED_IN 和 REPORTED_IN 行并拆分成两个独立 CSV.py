# -*- coding: utf-8 -*-
"""
汇总 data/triplets 下所有 *_triplets.csv 中的 LOCATED_IN 和 REPORTED_IN 行，
并拆分成两个独立 CSV：

- data/triplets/located_in_rows.csv
- data/triplets/reported_in_rows.csv

两个文件都保留 species 列，去掉 source_file 列。
"""

from __future__ import annotations

import csv
from pathlib import Path


TARGET_RELATIONSHIPS = {"LOCATED_IN", "REPORTED_IN"}
OUTPUT_DIR = Path("data/points")


def extract_target_rows() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """读取所有 triplets 文件并按关系类型抽取目标行。"""
    triplets_dir = Path("data/triplets")
    located_rows: list[dict[str, str]] = []
    reported_rows: list[dict[str, str]] = []

    for triplets_file in sorted(triplets_dir.glob("*_triplets.csv")):
        species_name = triplets_file.stem.replace("_triplets", "")

        try:
            with open(triplets_file, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    relationship = row.get("Relationship", "").strip()
                    if relationship not in TARGET_RELATIONSHIPS:
                        continue

                    extracted_row = {
                        "species": species_name,
                        "Entity1": row.get("Entity1", "").strip(),
                        "Relationship": relationship,
                        "Entity2": row.get("Entity2", "").strip(),
                        "Property": row.get("Property", "").strip(),
                    }
                    if relationship == "LOCATED_IN":
                        located_rows.append(extracted_row)
                    else:
                        reported_rows.append(extracted_row)
        except Exception as exc:
            print(f"读取失败: {triplets_file} - {exc}")

    return located_rows, reported_rows


def write_output(rows: list[dict[str, str]], output_file: Path) -> Path:
    """写出单个关系 CSV。"""
    fieldnames = ["species", "Entity1", "Relationship", "Entity2", "Property"]

    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return output_file


def main() -> None:
    located_rows, reported_rows = extract_target_rows()
    located_output = write_output(located_rows, OUTPUT_DIR / "located_in_rows.csv")
    reported_output = write_output(reported_rows, OUTPUT_DIR / "reported_in_rows.csv")

    print(f"LOCATED_IN 已抽取 {len(located_rows)} 条记录")
    print(f"已保存到: {located_output}")
    print(f"REPORTED_IN 已抽取 {len(reported_rows)} 条记录")
    print(f"已保存到: {reported_output}")
    preview_rows = reported_rows[:5] if reported_rows else located_rows[:5]
    if preview_rows:
        print("前5条样本:")
        for index, row in enumerate(preview_rows, start=1):
            print(
                f"{index}. {row['species']} | {row['Relationship']} | "
                f"{row['Entity1']} -> {row['Entity2']} | {row['Property']}"
            )


if __name__ == "__main__":
    main()

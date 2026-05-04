# -*- coding: utf-8 -*-
import requests
import pandas as pd
import os
import time
import argparse

from species_config import species_gbif_targets


def choose_items(options, title, allow_all=True):
    print(f"\n{title}")
    for idx, option in enumerate(options, start=1):
        print(f"  {idx}. {option}")
    if allow_all:
        print("  0. 全部")

    while True:
        choice = input('请输入编号，多个编号用逗号分隔：').strip()
        if not choice:
            return options
        if allow_all and choice == '0':
            return options

        selected = []
        valid = True
        for part in choice.replace('，', ',').split(','):
            part = part.strip()
            if not part:
                continue
            if not part.isdigit():
                valid = False
                break
            idx = int(part)
            if allow_all and idx == 0:
                return options
            if 1 <= idx <= len(options):
                value = options[idx - 1]
                if value not in selected:
                    selected.append(value)
            else:
                valid = False
                break

        if valid and selected:
            return selected

        print('输入无效，请重新输入。')


def get_china_distribution_backbone(species_name, taxon_key):
    """
    通过 REST API 抓取该骨架 ID 在中国(内地、港、澳、台)的所有记录
    """
    api_url = "https://api.gbif.org/v1/occurrence/search"
    regions = ['CN', 'HK', 'MO', 'TW']
    all_records = []

    print(f"🚀 正在提取数据: {species_name} (ID: {taxon_key})")

    for code in regions:
        offset = 0
        limit = 300  # GBIF 单词请求上限
        region_count = 0

        while True:
            params = {
                "taxonKey": taxon_key,
                "country": code,
                "hasCoordinate": "true",
                "limit": limit,
                "offset": offset
            }

            try:
                # 直接使用 requests 避开 pygbif 潜在的传参 bug
                response = requests.get(api_url, params=params, timeout=20)
                res = response.json()

                results = res.get('results', [])
                if not results:
                    break

                for r in results:
                    all_records.append({
                        "species_label": species_name,
                        "gbif_scientific_name": r.get('scientificName'),  # 实际记录中的学名
                        "lat": r.get('decimalLatitude'),
                        "lng": r.get('decimalLongitude'),
                        "province": r.get('stateProvince'),
                        "region_code": code,
                        "date": r.get('eventDate'),
                        "dataset": r.get('datasetName')
                    })

                region_count += len(results)

                if res.get('endOfRecords'):
                    break

                offset += limit
                time.sleep(0.1)  # 频率控制

            except Exception as e:
                print(f"  ❌ {code} 区域请求异常: {e}")
                break

        print(f"  ✅ {code} 区域抓取完成，共 {region_count} 条原始记录")

    if all_records:
        df = pd.DataFrame(all_records)
        # 对经纬度完全相同的点进行去重
        clean_df = df.drop_duplicates(subset=['lat', 'lng'])
        return clean_df
    return None


def main():
    parser = argparse.ArgumentParser(description='GBIF 分布点抓取脚本')
    parser.add_argument('--select', action='store_true', help='保留兼容：当前默认就会交互选择物种')
    args = parser.parse_args()

    save_dir = "data/gbif_results"
    os.makedirs(save_dir, exist_ok=True)

    print('🚀 启动选择：')
    selected_species = list(species_gbif_targets.items())
    selected_names = choose_items(list(species_gbif_targets.keys()), '可选物种：', allow_all=True)
    selected_species = [(name, species_gbif_targets[name]) for name in selected_names]

    for name, t_key in selected_species:
        df = get_china_distribution_backbone(name, t_key)

        if df is not None and len(df) > 0:
            path = os.path.join(save_dir, f"{name}.csv")
            df.to_csv(path, index=False, encoding='utf-8-sig')
            print(f"💾 成功保存 {len(df)} 个不重复地理分布点至: {path}\n")
        else:
            print(f"⚠️ {name} 在中国范围内未发现带坐标的骨架数据\n")


if __name__ == "__main__":
    main()
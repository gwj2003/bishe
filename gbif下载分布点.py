import requests
import pandas as pd
import os
import time

# 1. 配置 GBIF
TARGET_SPECIES = {
    "非洲大蜗牛": 10928934,
    "福寿螺": 2292582,  # Pomacea canaliculata
    "鳄雀鳝": 2346754,  # Atractosteus spatula
    "豹纹翼甲鲶": 2339971,  # Pterygoplichthys pardalis
    "齐氏罗非鱼": 2370703,  # Coptodon zillii
    "美洲牛蛙": 2427091,  # Lithobates catesbeianus
    "大鳄龟": 5220318,  # Macrochelys temminckii
    "红耳彩龟": 2443002  # Trachemys scripta elegans
}


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
    save_dir = "data/gbif_results"
    os.makedirs(save_dir, exist_ok=True)

    for name, t_key in TARGET_SPECIES.items():
        df = get_china_distribution_backbone(name, t_key)

        if df is not None and len(df) > 0:
            path = os.path.join(save_dir, f"{name}.csv")
            df.to_csv(path, index=False, encoding='utf-8-sig')
            print(f"💾 成功保存 {len(df)} 个不重复地理分布点至: {path}\n")
        else:
            print(f"⚠️ {name} 在中国范围内未发现带坐标的骨架数据\n")


if __name__ == "__main__":
    main()
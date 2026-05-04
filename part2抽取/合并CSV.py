# -*- coding: utf-8 -*-
import os
import glob
from io import StringIO
import pandas as pd
from species_config import species_names


OUTPUT_DIR = "data/triplets"
SPECIES_LIST = species_names

def merge_and_deduplicate_csv_texts(csv_texts):
    if not csv_texts:
        return ""
    all_dfs = []
    
    for text in csv_texts:
        try:
            # 1. 预处理：强制把第一行表头里的中文逗号换成英文逗号，防止 Pandas 解析成单列
            lines = text.split('\n')
            if lines and 'Entity1' in lines[0]:
                lines[0] = lines[0].replace('，', ',')
            clean_text = '\n'.join(lines)
            
            # 2. 读取 CSV 数据
            df = pd.read_csv(StringIO(clean_text))
            
            # 3. 强力清洗表头：去除所有列名两端的空格和不可见字符
            df.columns = [str(col).strip() for col in df.columns]
            
            # 4. 安全检查：只有真正包含 Entity1 列的数据才被加入
            if 'Entity1' in df.columns:
                all_dfs.append(df)
            else:
                print("    ⚠️ 跳过一块格式异常的 CSV (未解析出 Entity1 列)")
                
        except Exception as e:
            print(f"    ⚠️ 合并读取时发生异常跳过: {e}")
            continue
            
    if not all_dfs:
        return ""
    
    # 5. 合并所有数据
    final_df = pd.concat(all_dfs, ignore_index=True)
    
    # 6. 去重
    final_df = final_df.drop_duplicates()
    
    # 7. 动态安全排序：只拿真正存在的列来排序，彻底杜绝 KeyError
    sort_cols = [col for col in ['Entity1', 'Relationship', 'Entity2'] if col in final_df.columns]
    if sort_cols:
        final_df = final_df.sort_values(
            by=sort_cols, 
            ascending=[True] * len(sort_cols)
        )
    
    return final_df.to_csv(index=False)

def main():
    print("🚀 启动图谱 CSV 合并程序 (Step 2)")
    total_triplets = 0
    
    for species in SPECIES_LIST:
        print(f"\n========================================")
        print(f"📦 开始合并物种: {species}")
        
        raw_dir = os.path.join(OUTPUT_DIR, 'raw_outputs', species)
        
        if not os.path.exists(raw_dir):
            print(f"  ⚠️ 找不到 {species} 的 raw 数据目录，跳过。")
            continue
            
        csv_files = sorted(glob.glob(os.path.join(raw_dir, "*.csv")))
        if not csv_files:
            print(f"  ⚠️ {species} 没有可合并的 CSV 文件，跳过。")
            continue
            
        csv_texts = []
        for csv_file in csv_files:
            try:
                with open(csv_file, 'r', encoding='utf-8') as f:
                    csv_texts.append(f.read())
            except Exception as e:
                print(f"    ❌ 读取文件 {os.path.basename(csv_file)} 失败: {e}")
                
        print(f"  📚 找到 {len(csv_texts)} 个有效的 CSV 切块，开始清洗并合并...")
        
        csv_content = merge_and_deduplicate_csv_texts(csv_texts)
        
        if csv_content:
            save_path = os.path.join(OUTPUT_DIR, f"{species}_triplets.csv")
            with open(save_path, 'w', encoding='utf-8', newline='') as f:
                f.write(csv_content)

            # 减去表头 1 行
            count = max(0, len(csv_content.strip().split('\n')) - 1)
            total_triplets += count
            print(f"  ✅ 合并成功! 已生成 {save_path} (共 {count} 条去重关系)")
        else:
            print(f"  ⚠️ {species} 合并后无有效数据。")

    print(f"\n🏁 合并完成！全库累计有效三元组数: {total_triplets}")

if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
import os
import time
import glob
import re
from openai import OpenAI
from species_config import species_names


API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-5e6dd505dfba4033bdfd652f00c30959")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

if not API_KEY:
    raise RuntimeError("未检测到环境变量 DEEPSEEK_API_KEY")

OUTPUT_DIR = "data/triplets"
SPECIES_LIST = species_names


client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

def _select_prompt_from_folder():
    """扫描 prompts 文件夹下的 .md 文件并让用户选择"""
    prompt_dir = "prompts"
    
    if not os.path.exists(prompt_dir):
        print(f"⚠️ 提示: 找不到 {prompt_dir} 文件夹，正在为您自动创建...")
        os.makedirs(prompt_dir)
        
    search_path = os.path.join(prompt_dir, "*.md")
    md_files = sorted(glob.glob(search_path))
    
    if not md_files:
        print(f"❌ 错误: 在 {prompt_dir} 目录下没有找到任何 .md 格式的提示词文件！")
        return None

    print('\n📄 可用的提示词文件（请选择）：')
    for i, file_name in enumerate(md_files, start=1):
        print(f"  {i}. {os.path.basename(file_name)}")

    while True:
        choice = input('输入提示词文件编号: ').strip()
        try:
            idx = int(choice)
            if 1 <= idx <= len(md_files):
                selected_file = md_files[idx - 1]
                with open(selected_file, 'r', encoding='utf-8') as f:
                    print(f"\n✅ 已成功加载提示词: {os.path.basename(selected_file)}")
                    return f.read()
            else:
                print("⚠️ 编号超出范围，请重新输入。")
        except ValueError:
            print("⚠️ 请输入有效的数字编号。")

def clean_csv_output(text):
    text = re.sub(r'^\s+|\s+$', '', text)
    text = re.sub(r'```$', '', text, flags=re.MULTILINE)
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    if not lines:
        return ""
    if "Entity1" not in lines[0] and "Relationship" not in lines[0]:
        lines.insert(0, "Entity1,Relationship,Entity2,Property")
    return '\n'.join(lines)

def extract_knowledge(species_name, full_text, system_prompt):
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"请处理以下关于【{species_name}】的文本:\n\n{full_text}"}
            ],
            temperature=0.3,
            frequency_penalty=0.6,
            presence_penalty=0.6,
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"    ❌ API 调用失败: {e}")
        return ""

def load_saved_chunks(raw_dir):
    loaded_chunks = []
    if os.path.exists(raw_dir):
        for filename in os.listdir(raw_dir):
            if filename.endswith(".csv") or filename.endswith(".txt"):
                stem = os.path.splitext(os.path.basename(filename))[0]
                loaded_chunks.append(stem)
    return set(loaded_chunks)

def save_text_document(directory, filename, content):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    return path

def main():
    print("🚀 启动 DeepSeek 知识提取程序")
    
    # 1. 加载提示词
    DEFAULT_SYSTEM_PROMPT = _select_prompt_from_folder()
    if DEFAULT_SYSTEM_PROMPT is None:
        print("❌ 未成功加载提示词文件，程序退出。")
        return

    # 2. 交互选择物种
    print('\n可选物种：')
    for i, s in enumerate(SPECIES_LIST, start=1):
        print(f"  {i}. {s}")
    print("  0. 全部")
    choice = input('输入物种编号（逗号分隔）或按回车处理全部: ').strip()
    
    if not choice:
        selected_species = SPECIES_LIST
    else:
        selected_species = []
        for part in choice.replace('，', ',').split(','):
            part = part.strip()
            if not part:
                continue
            if part == '0':
                selected_species = SPECIES_LIST
                break
            if part.isdigit():
                idx = int(part)
                if 1 <= idx <= len(SPECIES_LIST):
                    selected_species.append(SPECIES_LIST[idx - 1])

    # 3. 交互选择数据源
    # 与数据源前缀映射匹配
    default_sources = ['BAIKE', 'CNKI', 'NEWS'] # 对应您文件名里的前缀，如 BAIKE_001.txt
    print('\n可选数据源：')
    for i, src in enumerate(default_sources, start=1):
        print(f"  {i}. {src}")
    src_choice = input('输入数据源编号（逗号分隔），或按回车使用默认全部: ').strip()
    
    if not src_choice:
        selected_sources = default_sources
    else:
        selected_sources = []
        for part in src_choice.replace('，', ',').split(','):
            part = part.strip()
            if not part:
                continue
            if part.isdigit():
                idx = int(part)
                if 1 <= idx <= len(default_sources):
                    selected_sources.append(default_sources[idx - 1])

    # 4. 执行抽取任务
    for species in selected_species:
        print(f"\n========================================")
        print(f"🔵 开始处理物种: {species}")
        print(f"========================================")

        chunk_dir = os.path.join(OUTPUT_DIR, 'chunks', species)
        raw_dir = os.path.join(OUTPUT_DIR, 'raw_outputs', species)

        if not os.path.exists(chunk_dir):
            print(f"  ⚠️ 找不到切块目录: {chunk_dir}，请先运行清洗脚本。")
            continue

        # 读取切块目录下的所有 .txt 文件
        chunk_files = sorted(glob.glob(os.path.join(chunk_dir, "*.txt")))
        if not chunk_files:
            print(f"  ⚠️ 目录 {chunk_dir} 中没有 txt 文件。")
            continue

        # 筛选出符合所选数据源前缀的文本块
        valid_chunks = []
        for cf in chunk_files:
            stem = os.path.splitext(os.path.basename(cf))[0]
            # 检查当前文件的开头是否与选中的数据源（如 'BAIKE', 'CNKI'）匹配
            if any(stem.startswith(src) for src in selected_sources):
                with open(cf, 'r', encoding='utf-8') as f:
                    valid_chunks.append((stem, f.read()))

        if not valid_chunks:
            print(f"  ⚠️ 没有找到符合所选数据源的文件。")
            continue

        saved_chunk_stems = load_saved_chunks(raw_dir)

        for chunk_index, (file_stem, chunk_text) in enumerate(valid_chunks, start=1):
            if file_stem in saved_chunk_stems:
                print(f"  ⏭️ 跳过已处理块: {file_stem}")
                continue

            print(f"  🧩 抽取第 {chunk_index}/{len(valid_chunks)} 块: {file_stem} (文本长度: {len(chunk_text)})")
            
            raw_result = extract_knowledge(species, chunk_text, DEFAULT_SYSTEM_PROMPT)
            csv_result = clean_csv_output(raw_result)
            
            if csv_result:
                csv_raw_file = save_text_document(raw_dir, f"{file_stem}.csv", csv_result)
                print(f"    📄 CSV 抽取结果已保存: {csv_raw_file}")
            elif raw_result:
                raw_file = save_text_document(raw_dir, f"{file_stem}.txt", raw_result)
                print(f"    📄 原始抽取结果已保存: {raw_file}")

            time.sleep(1)
            
    print("\n🏁 提取完成！所有 raw 数据均已保存。")

if __name__ == "__main__":
    main()
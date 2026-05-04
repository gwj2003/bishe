import os
import time
import pandas as pd
from openai import OpenAI

# ================= 1. 配置区域 =================
# 建议将 KEY 放入环境变量，或者在此处临时填写
API_KEY = "sk-5e6dd505dfba4033bdfd652f00c30959"  # 👈 填入你的 DeepSeek API Key
BASE_URL = "https://api.deepseek.com"

# 输入数据目录 (爬虫保存的txt文件夹)
INPUT_DIR = "data/animals"
# 输出结果目录
OUTPUT_DIR = "data/triplets"

# 目标物种列表 (和你爬虫里的保持一致)
SPECIES_LIST = [
    "非洲大蜗牛", "福寿螺", "鳄雀鳝", "豹纹翼甲鲶",
    "齐氏罗非鱼", "美洲牛蛙", "大鳄龟", "红耳彩龟"
]

# ================= 2. 提示词工程 (Schema Definition) =================
# 这里定义了你希望 AI 严格遵守的图谱结构
SYSTEM_PROMPT = """
# Role
你是一位资深的生态学数据分析专家和知识图谱构建工程师。

# Task
请阅读提供的【文本内容】，从中提取与“水生入侵动物”相关的实体与关系。

# Schema Definition (提取标准)
请严格基于以下定义的图谱模式进行提取：

1. 节点类型 (Entity Type):
   - **Species** (物种): 具体的动物中文名称。
   - **Taxonomy** (分类单元): 具体的科、属、目等名称 (如: 瓶螺科, 雀鳝属)。
   - **Location** (地点): 国家、河流、省份、水系等地理名词。
   - **Impact** (危害): 具体的危害行为或影响 (如: 啃食水稻, 破坏渔业)。
   - **Control** (防治): 具体的治理手段或工具 (如: 鸭子食螺, 物理捕捞)。

2. 关系类型 (Relationship):
   - **HAS_ALIAS**: 别名 (Species -> Species/String)
   - **BELONGS_TO**: 属于分类 (Species -> Taxonomy) [请在Property列注明等级，如 rank=科]
   - **NATIVE_TO**: 原产于 (Species -> Location)
   - **INVADES**: 入侵了 (Species -> Location) [请在Property列注明时间，如 time=1981年]
   - **CAUSES**: 造成危害 (Species -> Impact) [请在Property列注明类型，如 type=农业危害]
   - **SUPPRESSED_BY**: 被防治 (Species -> Control) [请在Property列注明手段，如 method=生物防治]

# Rules (约束条件)
1. **精确匹配**：只提取文中明确提到的信息，不要进行过度推理。
2. **实体规范化**：
   - 去除修饰词，如“巨大的鳄雀鳝” -> “鳄雀鳝”。
   - 将描述性语句转化为实体，如“老家在亚马逊” -> Entity2: "亚马逊", Rel: "NATIVE_TO"。
3. **Property 列的使用**：
   - 该列用于存储关系属性或 Entity2 的元属性。
   - 格式为 `key=value`。若无额外属性，填 `null`。
4. **输出格式**：
   - 严格的 CSV 格式，包含表头：`Entity1,Relationship,Entity2,Property`
   - 不要输出任何 Markdown 标记（如 ```csv），只输出纯文本数据。

# One-Shot Example (参考范例)
输入文本：
"福寿螺（学名：Pomacea canaliculata），又名大瓶螺，隶属于瓶螺科。原产于南美洲。1981年引入中国广东。它通过啃食水稻幼苗造成减产，目前可用鸭子食螺进行生物防治。"

输出:
Entity1,Relationship,Entity2,Property
福寿螺,HAS_ALIAS,大瓶螺,null
福寿螺,HAS_ALIAS,Pomacea canaliculata,type=学名
福寿螺,BELONGS_TO,瓶螺科,rank=科
福寿螺,NATIVE_TO,南美洲,null
福寿螺,INVADES,中国,time=1981年
福寿螺,INVADES,广东,time=1981年
福寿螺,CAUSES,啃食水稻幼苗,type=农业危害
福寿螺,SUPPRESSED_BY,鸭子食螺,method=生物防治

# Input Text (待处理文本)
{{TEXT_PLACEHOLDER}}
"""

# ================= 3. 核心功能函数 =================

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


def read_species_files(species_name):
    """读取该物种的所有来源文本(百度+中维+英维)并合并"""
    content_buffer = []

    # 定义要读取的文件后缀
    suffixes = ["_baidu.txt", "_zh_wiki.txt", "_en_wiki.txt"]

    for suffix in suffixes:
        filename = f"{species_name}{suffix}"
        filepath = os.path.join(INPUT_DIR, filename)

        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    text = f.read()
                    # 给每个来源加个小标题，方便AI区分
                    source_name = suffix.replace(".txt", "").replace("_", " ").upper()
                    content_buffer.append(f"\n--- SOURCE: {source_name} ---\n{text[:15000]}")
                    # 注意: DeepSeek V3窗口很大，但为了省钱和速度，单个来源截取前1.5万字通常足够覆盖核心信息
            except Exception as e:
                print(f"⚠️ 读取文件 {filename} 失败: {e}")

    return "\n".join(content_buffer)


def extract_knowledge(species_name, full_text):
    """调用 DeepSeek API 进行抽取"""
    if not full_text:
        return None

    print(f"  🤖 正在请求 DeepSeek 提取【{species_name}】的三元组 (文本长度: {len(full_text)})...")

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",  # 使用 V3 模型
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"请处理以下关于【{species_name}】的文本:\n\n{full_text}"}
            ],
            temperature=0.1,  # 低温度，保证提取事实的准确性
            stream=False
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"  ❌ API 调用失败: {e}")
        return None


def clean_csv_output(raw_output):
    """清洗 API 返回的可能带有 Markdown 格式的文本"""
    if not raw_output:
        return ""

    # 去除 ```csv 和 ``` 标记
    cleaned = raw_output.replace("```csv", "").replace("```", "").strip()

    # 过滤掉空行
    lines = [line for line in cleaned.split('\n') if line.strip()]
    return "\n".join(lines)


# ================= 4. 主程序 =================

def main():
    if not os.path.exists(INPUT_DIR):
        print(f"❌ 错误: 找不到输入目录 {INPUT_DIR}，请先运行爬虫脚本！")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    total_triplets = 0

    for species in SPECIES_LIST:
        print(f"\n🔵 开始处理: {species}")

        # 1. 准备文本
        combined_text = read_species_files(species)
        if not combined_text:
            print(f"  ⚠️ 跳过: 没有找到 {species} 的任何文本文件")
            continue

        # 2. AI 抽取
        raw_result = extract_knowledge(species, combined_text)

        # 3. 数据清洗与保存
        if raw_result:
            csv_content = clean_csv_output(raw_result)

            # 保存文件
            save_path = os.path.join(OUTPUT_DIR, f"{species}_triplets.csv")
            with open(save_path, "w", encoding="utf-8") as f:
                f.write(csv_content)

            # 统计行数（减去表头）
            count = max(0, len(csv_content.split('\n')) - 1)
            total_triplets += count
            print(f"  ✅ 提取成功! 已保存至 {save_path} (约 {count} 条关系)")

            # 打印前几行看看效果
            print("  👀 数据预览:")
            print("\n".join(csv_content.split('\n')[:3]))
        else:
            print("  ❌ 提取失败，返回内容为空")

        # 避免并发过高（虽然 DeepSeek 限流较松，但在循环里加个sleep是好习惯）
        time.sleep(1)

    print(f"\n🏁 所有任务完成。共提取约 {total_triplets} 条三元组数据。")
    print(f"📂 结果保存在: {os.path.abspath(OUTPUT_DIR)}")


if __name__ == "__main__":
    main()
# -*- coding: utf-8 -*-
import os
import pandas as pd
from neo4j import GraphDatabase

# ================= 1. 配置区域 =================
# Neo4j 连接信息
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "12345sss"  # 👈 记得确认密码

# CSV 数据目录
DATA_DIR = "data/triplets"

# ================= 2. 核心逻辑：标签与关系映射 =================
# 新版图谱统一使用英文标签，并区分空间层级、生态对象和防治措施。
REL_TO_TARGET_LABEL_MAP = {
    # 基础属性与生态关系 (原有)
    "HAS_ALIAS": "Species",
    "BELONGS_TO": "Taxonomy",
    "NATIVE_TO": "Origin",
    "LOCATED_IN": "Origin",
    "REPORTED_IN": "Province",
    "THRIVES_IN": "Habitat",
    "INTRODUCED_VIA": "Pathway",
    "PREYS_ON": "Target",
    "COMPETES_WITH": "Target",
    "CAUSES": "Impact",  
    "SUPPRESSED_BY": "Control",
    "INVADES": "Province",
    "HAS_MORPHOLOGY": "Morphology",
    "HAS_HABIT": "Habit",
    
    # 👇 新增：空间关系
    "ADJACENT_TO": "Region",
    "CONTAINS": "Region",
    "INTERSECTS": "Region",
    "SPREAD_RISK_TO": "Region",
    
    # 👇 新增：因果关系
    "LEADS_TO": "Event",
    "MITIGATES": "Event", 
    "AFFECTS": "Target", 
    
    # 👇 新增：时间关系
    "BEFORE": "Event",
    "AFTER": "Event",
    "DURING": "TimePeriod",
    "OVERLAPS": "Event",
    
    # 🌟 新增：修复 EVENT 未知类型报错
    "EVENT": "Event",
    "HAS_EVENT": "Event",
}

# 👇 新增了 "Region", "Event", "TimePeriod" 到白名单中
ALLOWED_LABELS = {
    "Species", "Taxonomy", "Origin", "Province", "City", "District",
    "Habitat", "Pathway", "Target", "Impact", "Control", "Morphology", "Habit", 
    "Entity", "Region", "Event", "TimePeriod"
}

PROVINCE_SUFFIXES = ("省", "自治区", "特别行政区")
CITY_SUFFIXES = ("市", "盟", "州", "地区", "自治州")
DISTRICT_SUFFIXES = ("区", "县", "旗", "林区", "自治县", "市辖区", "镇", "乡", "村")
ORIGIN_SUFFIXES = ("洲", "国", "流域", "盆地", "大陆", "岛", "海", "洋")
HABITAT_HINTS = (
    "稻田", "水库", "河流", "湖泊", "湿地", "池塘", "沟渠", "沼泽", "海岸",
    "河口", "静水", "浅水", "水域", "塘", "渠", "溪", "江", "海湾"
)


def sanitize_label(label):
    """只允许白名单中的 Neo4j 标签，避免非法标签写入。"""
    if label in ALLOWED_LABELS:
        return label
    return "Entity"


def sanitize_relationship(rel_type):
    """只允许已知关系类型，并将名称规范化为 Neo4j 可接受的格式。"""
    rel_type = str(rel_type).strip().upper()
    if rel_type in REL_TO_TARGET_LABEL_MAP:
        return rel_type
    return ""


def infer_geo_label(name):
    """根据中文地名后缀推断 Province / City / District / Origin。"""
    if not name:
        return "Entity"

    text = str(name).strip()
    if text.endswith(PROVINCE_SUFFIXES):
        return "Province"
    if text.endswith(DISTRICT_SUFFIXES):
        return "District"
    if text.endswith(CITY_SUFFIXES):
        return "City"
    if text.endswith(ORIGIN_SUFFIXES):
        return "Origin"
    if any(hint in text for hint in HABITAT_HINTS):
        return "Habitat"
    return "Origin"


def infer_source_label(entity_name, relationship):
    """根据关系类型和实体名称推断起点节点标签。"""
    relationship = str(relationship).strip().upper()

    if relationship == "MITIGATES":
        return "Control"

    if relationship == "DURING":
        return "Event"

    if relationship == "EVENT":
        return "Entity"

    if relationship == "LOCATED_IN":
        return infer_geo_label(entity_name)

    if relationship in {"AFTER", "BEFORE", "OVERLAPS", "LEADS_TO", "CAUSES"}:
        text = str(entity_name or "")
        if any(keyword in text for keyword in ("事件", "行动", "防治", "入侵", "治理", "整治", "清除")):
            return "Event"

    if relationship in {"CONTAINS", "INTERSECTS", "ADJACENT_TO", "SPREAD_RISK_TO"}:
        return infer_geo_label(entity_name)

    return "Species"


def infer_target_label(entity_name, relationship):
    """根据关系类型和实体名称推断终点节点标签。"""
    relationship = str(relationship).strip().upper()
    default_label = REL_TO_TARGET_LABEL_MAP.get(relationship, "Entity")

    if relationship == "LOCATED_IN":
        return infer_geo_label(entity_name)

    if relationship == "REPORTED_IN":
        geo_label = infer_geo_label(entity_name)
        return geo_label if geo_label in {"Province", "City", "District"} else "Province"

    if relationship == "MITIGATES":
        text = str(entity_name or "")
        if any(keyword in text for keyword in ("事件", "行动", "防治", "整治", "清除", "处置")):
            return "Event"
        return "Species"

    if relationship == "DURING":
        return "TimePeriod"

    if relationship == "EVENT":
        return "Event"

    if relationship == "NATIVE_TO":
        return infer_geo_label(entity_name)

    if relationship == "THRIVES_IN":
        return "Habitat" if any(hint in str(entity_name) for hint in HABITAT_HINTS) else default_label

    if relationship in {"PREYS_ON", "COMPETES_WITH", "AFFECTS"}:
        return "Target"

    if relationship in {"SPREAD_RISK_TO", "CONTAINS", "INTERSECTS", "ADJACENT_TO"}:
        return infer_geo_label(entity_name)

    if relationship == "CAUSES":
        text = str(entity_name or "")
        if any(keyword in text for keyword in ("事件", "行动", "防治", "整治", "清除", "处置")):
            return "Event"
        return "Impact"

    return sanitize_label(default_label)


# ================= 3. 功能函数 =================

def parse_properties(prop_str):
    """
    把 CSV 里的 "time=1981;type=农业" 字符串解析成 Python 字典
    """
    if pd.isna(prop_str) or prop_str == "null" or not prop_str:
        return {}

    props = {}
    # 先按分号拆分多个属性
    items = str(prop_str).split(';')
    for item in items:
        if '=' in item:
            key, value = item.split('=', 1)
            props[key.strip()] = value.strip()
    return props


def normalize_property_values(props):
    """把空属性统一成 null，避免 Neo4j 中写入空字符串。"""
    normalized = {}
    for key, value in props.items():
        if value is None:
            continue
        value_str = str(value).strip()
        if not value_str or value_str.lower() == "none":
            continue
        normalized[key] = value_str
    return normalized


def import_csv_to_graph(driver, filepath):
    """读取单个 CSV 并写入 Neo4j (增强版：自动修复表头问题)"""
    filename = os.path.basename(filepath)

    try:
        # 🌟 修复 1: 使用 'utf-8-sig' 编码，它可以自动去除 BOM 头 (\ufeff)
        # 🌟 修复 2: on_bad_lines='skip' 跳过格式错误的坏行
        df = pd.read_csv(filepath, encoding='utf-8-sig', on_bad_lines='skip')

        # 🌟 修复 3: 强制去除列名的前后空格 (防止 'Entity1 ' 这种情况)
        df.columns = [c.strip() for c in df.columns]

        # 🔍 调试信息：如果列名不对，打印出来让我们看到
        if 'Entity1' not in df.columns:
            print(f"  ⚠️ 跳过 {filename}: 表头格式错误。实际表头是: {df.columns.tolist()}")
            return

        print(f"📄 正在处理: {filename} ({len(df)} 条数据)")

        with driver.session() as session:
            for index, row in df.iterrows():
                try:
                    # 🌟 修复 4: 增加安全性检查，防止空值报错
                    if pd.isna(row['Entity1']) or pd.isna(row['Entity2']):
                        continue

                    e1_name = str(row['Entity1']).strip()
                    rel_type = sanitize_relationship(row['Relationship'])
                    e2_name = str(row['Entity2']).strip()
                    raw_props = row['Property']

                    if not rel_type:
                        print(f"    ⚠️ 第 {index + 1} 行跳过: 未知关系类型 {row['Relationship']}")
                        continue

                    # 1. 解析属性
                    rel_props = normalize_property_values(parse_properties(raw_props))

                    # 2. 根据新版 schema 推断起点/终点节点的 Label
                    source_label = sanitize_label(infer_source_label(e1_name, rel_type))
                    target_label = sanitize_label(infer_target_label(e2_name, rel_type))
                    species_source = ""
                    if "species_source" in df.columns:
                        species_source = str(row.get("species_source") or "").strip()

                    # 3. 如果是地理层级关系，动态补足省/市/区/原产地等标签
                    #    例如：栖霞区 -> District, 南京市 -> City, 江苏省 -> Province

                    # 4. 构建 Cypher
                    cypher = f"""
                    MERGE (s:{source_label} {{name: $e1_name}})
                    MERGE (t:{target_label} {{name: $e2_name}})
                    MERGE (s)-[r:{rel_type}]->(t)
                    SET r += $props
                    """

                    session.run(cypher, e1_name=e1_name, e2_name=e2_name, props=rel_props)

                    if species_source and (source_label == "Event" or target_label == "Event"):
                        event_name = e1_name if source_label == "Event" else e2_name
                        if event_name:
                            session.run(
                                """
                                MERGE (s:Species {name: $species_name})
                                MERGE (e:Event {name: $event_name})
                                MERGE (s)-[r:HAS_EVENT]->(e)
                                """,
                                species_name=species_source,
                                event_name=event_name,
                            )
                except Exception as inner_e:
                    # 某一行出错不影响整个文件
                    print(f"    ⚠️ 第 {index + 1} 行插入失败: {inner_e}")

        print(f"  ✅ {filename} 导入完成！")

    except Exception as e:
        print(f"  ❌ 读取文件 {filename} 失败: {e}")


# ================= 4. 主程序 =================

def main():
    # 1. 检查数据目录
    if not os.path.exists(DATA_DIR):
        print(f"❌ 目录不存在: {DATA_DIR}。请先运行 extract_triplets.py")
        return

    # 2. 连接数据库
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        # 测试连接
        driver.verify_connectivity()
        print("🔌 Neo4j 连接成功！准备开始导入...")
    except Exception as e:
        print(f"❌ 无法连接 Neo4j: {e}")
        return

    # 3. (可选) 清空旧数据 - 开发阶段建议打开，防止数据重复堆积
    # 清空旧数据：在导入前先删除数据库中现有所有节点与关系
    # （如果不希望自动清空，可把下行注释掉或在环境中设置变量）
    def clear_all_data(drv):
        try:
            with drv.session() as s:
                s.run("MATCH (n) DETACH DELETE n")
            print("🧹 旧数据已清空。")
            return True
        except Exception as e:
            print(f"⚠️ 清空旧数据失败: {e}")
            return False

    clear_all_data(driver)

    # 4. 遍历 CSV 文件导入
    csv_files = [f for f in os.listdir(DATA_DIR) if f.endswith('.csv')]
    if not csv_files:
        print("⚠️ 没找到 CSV 文件。")
        return

    for csv_file in csv_files:
        full_path = os.path.join(DATA_DIR, csv_file)
        import_csv_to_graph(driver, full_path)

    driver.close()
    print("\n🎉 全部导入完成！")


if __name__ == "__main__":
    main()
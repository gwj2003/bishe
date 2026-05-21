# 水生入侵动物知识图谱项目

本项目是一条从数据采集、文本抽取、分布点处理，到 Neo4j 导入和 Streamlit 展示的完整流水线。下面给出一份“从零到跑通”的推荐执行顺序，默认在 Windows 下使用 PowerShell 和 Conda 环境 `invasives-env`。

## 一、环境准备

先进入项目目录，并激活 Python 环境：

```powershell
cd /d "D:\Users\44574\Desktop\毕设代码"
conda activate invasives-env
```

如果你要使用 DeepSeek 抽取、新闻爬取或在线地理编码，请确认已准备好相应网络权限和 API Key。

## 二、推荐运行顺序

### 1. 启动 Neo4j

如果后面要导入图谱或打开问答界面，先启动 Neo4j：

```powershell
.
start-neo4j.bat
```

如果你只想先处理数据，也可以把这一步放到最后，但在导入 Neo4j 前必须确保数据库已启动。

### 2. 采集原始数据

按需运行以下脚本。它们都支持交互选择物种和参数：

```powershell
python .\part1爬取\爬取百科数据.py
python .\part1爬取\爬取新闻数据.py
python .\part1爬取\爬取知网数据.py
python .\part1爬取\爬取GBIF分布点.py
```

输出目录大致如下：

- `data/encyclopedia_texts/`
- `data/news_texts/`
- `data/cnki_texts/`
- `data/gbif_results/`

### 3. 清洗文本并切块

把百科、新闻、知网文本清洗后切块，供后续抽取使用：

```powershell
python .\part2抽取\文本清洗与切块.py
```

输出到：

- `data/triplets/chunks/`

### 4. 调用大模型抽取三元组

使用 DeepSeek 从切块文本里抽取知识图谱三元组：

```powershell
python .\part2抽取\调用deepseek抽取.py
```

运行时会让你选择：

- 提示词文件
- 物种
- 数据源前缀

抽取结果会写入：

- `data/triplets/raw_outputs/`

### 5. 合并抽取结果

把每个物种的抽取结果合并、去重，生成最终三元组文件：

```powershell
python .\part2抽取\合并CSV.py
```

输出为：

- `data/triplets/<物种>_triplets.csv`

### 6. 处理 LOCATED_IN 和 REPORTED_IN

如果你要继续做中国境内分布点解析，先把这两类关系单独拆出来：

```powershell
python .\part3抽取\汇总LOCATED_IN 和 REPORTED_IN 行并拆分成两个独立 CSV.py
```

会生成：

- `data/points/located_in_rows.csv`
- `data/points/reported_in_rows.csv`

### 7. 解析中国境内精确分布点

从上一步抽出的关系里筛选精确地点，生成可地理编码的地点表：

```powershell
python .\part3分布点数据处理\基于reported_in_rows和located_in_rows解析中国境内分布点.py
```

输出为：

- `data/points/china_distribution_points.csv`

### 8. 对精确地点做地理编码

把地点文本转换成经纬度和行政区字段：

```powershell
python .\part3分布点数据处理\对china_distribution_points中记录进行地理编码.py
```

输出为：

- `data/points/china_distribution_points_geocoded.csv`

### 9. 处理 GBIF 分布点

如果你也要使用 GBIF 分布点，按这个顺序执行：

```powershell
python .\part3分布点数据处理\合并GBIF 记录.py
python .\part3分布点数据处理\为gbif_species_merged_compact中的点位赋值.py
python .\part3分布点数据处理\合并点位并重建行政区字段.py
```

对应输出通常是：

- `data/gbif_results/gbif_species_merged_compact.csv`
- `data/points/gbif_species_merged_admin_levels.csv`

说明：该脚本会使用本地行政边界文件 `data/admin_shapefiles/AreaCity_ok_geo/ok_geo.csv` 为 GBIF 点位打上省/市/区等行政信息，输出到 `data/points/gbif_species_merged_admin_levels.csv`。如果找不到行政边界文件，脚本会报错并提示缺失。

- `data/point/china_gbif_merged_admin_levels.csv`

在第 9 步和第 10 步之间运行：

```powershell
python .\清洗并合并triplets.py
```

### 10. 导入 Neo4j

确认 `data/triplets/cleaned` 目录下放的是你想导入的最终 CSV 后，再执行：

```powershell
python .\import_to_neo4j.py
```

这个脚本会扫描 `data/triplets/cleaned` 下所有 CSV 文件并导入 Neo4j，所以导入前请先检查目录内容，避免把辅助文件也一起导入。

### 11. 启动前端界面

当 GBIF 汇总文件和 Neo4j 都准备好后，运行 Streamlit 看板：

```powershell
.
run_new.bat
```

或者直接运行：

```powershell
python .\new.py
```

## 三、最简跑通顺序

如果你想先跑一个最小闭环，建议按下面顺序：

1. `start-neo4j.bat`
2. `爬取百科数据.py`
3. `文本清洗与切块.py`
4. `调用deepseek抽取.py`
5. `合并CSV.py`
6. `汇总LOCATED_IN 和 REPORTED_IN 行并拆分成两个独立 CSV.py`
7. `基于reported_in_rows和located_in_rows解析中国境内分布点.py`
8. `对china_distribution_points中记录进行地理编码.py`
9. `import_to_neo4j.py`
10. `run_new.bat`

## 四、目录对应关系

- 原始百科文本：`data/encyclopedia_texts/`
- 原始新闻文本：`data/news_texts/`
- 原始知网文本：`data/cnki_texts/`
- GBIF 原始点位：`data/gbif_results/`
- 文本切块：`data/triplets/chunks/`
- 模型抽取结果：`data/triplets/raw_outputs/`
- 最终三元组：`data/triplets/*_triplets.csv`
- 国内地点解析：`data/points/china_distribution_points.csv`
- 地理编码结果：`data/points/china_distribution_points_geocoded.csv`
- GBIF 行政区结果：`data/points/gbif_species_merged_admin_levels.csv`

## 五、补充说明

- `run_new.bat` 只是启动 `new.py` 的包装脚本。
- `start-neo4j.bat` 只是检测并启动 Neo4j 的包装脚本。
- `new.py` 依赖 `data/points/china_gbif_merged_admin_levels.csv` 这类汇总数据；如果文件不存在，界面中的部分功能会报错或无法展示完整内容。
- `import_to_neo4j.py` 会读取 `data/triplets/cleaned` 下所有 CSV，因此导入前最好先清理目录，或者确认只保留需要导入的文件。

如果你想，我可以继续把这份 README 再整理成“可直接复制执行的命令版”，把每一步的命令按 1、2、3 连续列出来，方便你在终端里逐条跑。
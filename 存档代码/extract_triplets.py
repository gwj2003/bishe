# -*- coding: utf-8 -*-
import os
import time
import glob
import re
from io import StringIO
import pandas as pd
from openai import OpenAI
from species_config import species_names

# ================= 1. 配置区域 =================
# 建议将 KEY 和 BASE_URL 放入环境变量
API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-5e6dd505dfba4033bdfd652f00c30959")
BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

if not API_KEY:
    raise RuntimeError("未检测到环境变量 DEEPSEEK_API_KEY")

# 输入数据目录 (爬虫保存的txt文件夹)
ENCYCLOPEDIA_INPUT_DIR = "data/encyclopedia_texts"
CNKI_INPUT_DIR = "data/cnki_texts"
NEWS_INPUT_DIR = "data/news_texts"
# 输出结果目录
OUTPUT_DIR = "data/triplets"

# 文本切块的字符上限
CNKI_CHUNK_CHAR_LIMIT = 10000
NEWS_CHUNK_CHAR_LIMIT = 10000

# 目标物种列表 (和你爬虫里的保持一致)
SPECIES_LIST = species_names

# ================= 2. 提示词工程 (Schema Definition) =================
# 这里定义了你希望 AI 严格遵守的图谱结构
# 默认内嵌提示词（详尽规则）
DEFAULT_SYSTEM_PROMPT = """
# Role
你是一位资深的生态学数据分析专家和空间地理信息提取工程师。

# Task
请阅读提供的【文本内容】（可能包含中英文），从中提取与“水生入侵动物”相关的实体与关系，并构建规范的知识图谱三元组。

# Schema Definition (提取标准)
请严格基于以下定义的图谱模式进行提取：

1. 节点类型 (Entity Type):
   - Species: 物种名称（如福寿螺、鳄雀鳝）。
   - Taxonomy: 分类单元（科、属、目等）。
   - Origin: 原产地/溯源地（请细化为具体的国家、大洲或流域）。
   - Province / City / District: 省份、城市、区县的规范地名（必须带有省/市/区后缀）。
   - Habitat: 具体的生境/栖息地类型（如稻田、水库、河流）。
   - Morphology: 形态特征（如粉红色卵块、体型巨大、背甲有棱）。
   - Habit: 生活习性（如昼伏夜出、杂食性、耐低温）。
   - Pathway: 引入途径（如养殖逃逸、人为放生、随船引入）。
   - Target: 危害的目标对象，如农作物或本土物种（如水稻、莲藕、本土鲫鱼）。
   - Impact: 宏观层面的危害（如破坏生态平衡、传播疾病）。
   - Control: 防治手段（如人工捕杀、鸭子食螺）。

2. 关系类型 (Relationship):
   - HAS_ALIAS (Species -> Species/String) [Property: type=学名/俗名]
   - BELONGS_TO (Species -> Taxonomy) [Property: rank=科/属/目]
   - HAS_MORPHOLOGY (Species -> Morphology) [无Property]
   - HAS_HABIT (Species -> Habit) [无Property]
   - NATIVE_TO (Species -> Origin) [无Property]
   - LOCATED_IN (District->City, City->Province, 或 Origin->Origin) [无Property]
   - REPORTED_IN (Species -> Province/City/District) [Property: year=年份, status=状态]
   - THRIVES_IN (Species -> Habitat) [无Property]
   - INTRODUCED_VIA (Species -> Pathway) [无Property]
   - PREYS_ON (Species -> Target) [Property: severity=危害程度]
   - COMPETES_WITH (Species -> Target) [Property: severity=危害程度]
   - CAUSES (Species -> Impact) [Property: type=危害分类]
   - SUPPRESSED_BY (Species -> Control) [Property: method=物理/化学/生物]

# Rules (核心提取规则约束)
1. 国内入侵地约束与补全（空间核心）：必须提取文中提到的【最细颗粒度行政区划】（市/区/县级优先）作为 REPORTED_IN 的终点。提取后，请利用先验知识补全完整的行政层级，并生成对应的 LOCATED_IN 包含关系（如 栖霞区,LOCATED_IN,南京市）。
2. 国内入侵地模糊泛指剥离：对于入侵发生地，若仅提到“长江中下游”、“华南地区”等宽泛地理词汇，【请绝对不要将其提取为省市区节点】，直接留空或跳过！
3. 原产地分级与多源地拆分（溯源核心）：如果文本提到多个毫无关联的原产地（如“原产于北美洲和南美洲”），必须拆分为多条 NATIVE_TO 关系。如果原产地存在明确的层级包含关系（如“南美洲的巴西”），请提取最细层级作为 NATIVE_TO 终点，并自动生成原产地之间的 LOCATED_IN 关系（如 福寿螺,NATIVE_TO,巴西 以及 巴西,LOCATED_IN,南美洲）。
4. 一对多拆分：如果文本中提到了多个具体的国内市/县分布地点、多种生境或危害多个目标，【必须】将其拆分为多行独立的三元组输出。确保每次 REPORTED_IN 或 NATIVE_TO 关系只指向一个明确的地点实体。
5. 生态与交互提取：务必提取物种的原产地 (Origin)、生境 (Habitat)、引入途径 (Pathway) 以及物种与目标对象之间的交互关系 (PREYS_ON/COMPETES_WITH)。若文本未提及则跳过。
6. Property 列的使用：格式为 `key=value`。若有多个属性用分号隔开。若文本未提及属性值，填 `null` 或跳过。
7. 格式红线：严格遵守 CSV 格式，包含表头 `Entity1,Relationship,Entity2,Property`。绝对不要包含任何 Markdown 标记（如 ```csv），只输出纯文本数据。
8. 跨语言规范翻译（语言核心）：如果输入文本包含英文内容，提取出的实体名称和属性描述【必须统一翻译为精准的中文】（仅物种的拉丁学名除外，保留拉丁文字母）。
9. 目标物种主名约束：本次输入的物种名会在用户消息中单独给出。除 `HAS_ALIAS` 外，所有与该目标物种相关的关系都必须使用这个物种名作为 `Entity1`，不要改用别名、俗名、学名或其他同义名。
10. 别名使用约束：别名、俗名、学名只能出现在 `HAS_ALIAS` 的 `Entity2` 中；不要把这些别名当成其他关系的 `Entity1`。

# One-Shot Example (参考范例)
输入文本：
"2023年调研显示，Native to the Amazon River basin of South America的福寿螺（学名：Pomacea canaliculata，瓶螺科）已引入我国。它具有昼伏夜出的习性，常在植物茎秆上产下特征明显的粉红色卵块。目前在江苏省南京市栖霞区、安徽省安庆市迎江区大面积泛滥。该物种不仅会啃食水稻幼苗造成农业减产，还会竞争本土田螺。专家建议投放茶籽饼进行化学防治。"

输出:
Entity1,Relationship,Entity2,Property
福寿螺,HAS_ALIAS,Pomacea canaliculata,type=学名
福寿螺,BELONGS_TO,瓶螺科,rank=科
福寿螺,NATIVE_TO,亚马逊河流域,null
亚马逊河流域,LOCATED_IN,南美洲,null
栖霞区,LOCATED_IN,南京市,null
南京市,LOCATED_IN,江苏省,null
迎江区,LOCATED_IN,安庆市,null
安庆市,LOCATED_IN,安徽省,null
福寿螺,REPORTED_IN,栖霞区,year=2023;status=大面积泛滥
福寿螺,REPORTED_IN,迎江区,year=2023;status=大面积泛滥
福寿螺,HAS_HABIT,昼伏夜出,null
福寿螺,HAS_MORPHOLOGY,粉红色卵块,null
福寿螺,PREYS_ON,水稻幼苗,severity=啃食造成农业减产
福寿螺,COMPETES_WITH,本土田螺,severity=排挤
福寿螺,SUPPRESSED_BY,投放茶籽饼,method=化学防治

# Input Text (待处理文本)
{{TEXT_PLACEHOLDER}}
"""

# ================= 2. 提示词工程 (Schema Definition) =================
# 从 prompts 文件夹读取系统提示词：
# 支持：
#  - 环境变量 `SYSTEM_PROMPT_FILE` 指定的文件（若存在，则加入可选项）
#  - 扫描 prompts 目录下的所有 `.md` 文件并加入可选项
#  - 始终保留内嵌提示词作为第一个选项
def _available_prompts():
    opts = [("内嵌提示词", DEFAULT_SYSTEM_PROMPT)]

    # 环境变量指定的提示词文件（可选）
    env_path = os.getenv('SYSTEM_PROMPT_FILE')
    if env_path:
        try:
            if os.path.exists(env_path):
                with open(env_path, 'r', encoding='utf-8') as f:
                    opts.append((os.path.basename(env_path), f.read()))
        except Exception:
            pass

    # 扫描 prompts 目录下所有 .md 文件
    prompts_dir = 'prompts'
    try:
        if os.path.isdir(prompts_dir):
            files = sorted(glob.glob(os.path.join(prompts_dir, '*.md')))
            for p in files:
                try:
                    # 避免重复加入与 env_path 相同的文件
                    if env_path and os.path.abspath(p) == os.path.abspath(env_path):
                        continue
                    with open(p, 'r', encoding='utf-8') as f:
                        opts.append((os.path.basename(p), f.read()))
                except Exception:
                    continue
    except Exception:
        pass

    return opts

SYSTEM_PROMPT = DEFAULT_SYSTEM_PROMPT

# ================= 3. 核心功能函数 =================

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

CSV_COLUMNS = ['Entity1', 'Relationship', 'Entity2', 'Property']


NOISE_LINES = {
    # 中文导航
    '目录', '序言', '参考文献', '工具', '阅读', '查看历史', '常规', '链入页面', '相关更改',
    '上传文件', '固定链接', '页面信息', '引用此页', '获取短链接', '跨语言链接', '打印/导出',
    '在其他项目中', '维基共享资源', '维基数据项目', '条目', '讨论', '查看历史', '下载为PDF',
    '可打印版', '移至侧栏隐藏', '开关目录', '目录', '链接', '语言', '阅读', '查看', '历史',
    '工具', '页面信息', '引用此页', '相关更改', '播报',
    # 英文导航菜单
    'Toggle the table of contents', 'Edit links', 'Article', 'Talk', 'Read', 'Edit', 'View history',
    'Tools', 'move to sidebarhide', 'Actions', 'General', 'What links here', 'Related changes',
    'Upload file', 'Permanent link', 'Page information', 'Cite this page', 'Get shortened URL',
    'Edit interlanguage links', 'Print/export', 'Download as PDF', 'Printable version',
    'In other projects', 'Wikimedia Commons', 'Wikidata item', 'See also'
}

SECTION_NOISE = {
    '参考', '参考文献', '外部链接', '扩展阅读', '相关条目', '注释', '脚注', '来源', '参见', '更多阅读', '相关页面',
    'See also', 'List of'
}

# 维基百科UI元素：语言代码、导航菜单、页面设置等
WIKI_UI_ELEMENTS = {
    # 语言代码
    'Català', 'Cebuano', 'English', 'Español', 'Euskara', 'Français', 'Nederlands', 
    'Polski', 'Русский', 'ไทย', 'Українська',
    # 中文UI菜单
    '操作', '外观', '文本', '小', '标准', '大', '宽', '颜色', '此页面始终使用小字号',
    '内容会尽可能占满您的浏览器窗口宽度', '此页面始终处于浅色模式', '自动', '浅色', '深色',
    '测试版', '宽度',
    # 英文页面设置
    'Appearance', 'Text', 'Small', 'Standard', 'Large', 'Width', 'Wide', 'Color', 'Automatic', 'Light', 'Dark',
    'This page always uses small font size', 'This page is always in light mode',
    'The content is as wide as possible for your browser window.',
    # 其他页面UI
    '检索自', '隐藏分类', '物种微格式条目', '含有拉丁语的条目',
    'From Wikipedia, the free encyclopedia'
}

FACT_KEYWORDS = (
    '学名', '别名', '俗名', '科', '属', '目', '原产', '原产于', '分布', '分布于', '入侵', '引入', '逃逸',
    '放生', '养殖', '栖息', '生境', '水域', '水库', '河流', '湖泊', '稻田', '湿地', '危害', '危害到', '捕食',
    '竞争', '防治', '控制', '治理', '人工捕杀', '药物', '投放', '记录', '发现', '发生', '报道', '出现'
)

LOCATION_SUFFIXES = ('省', '市', '县', '区', '州', '盟', '镇', '乡', '村', '河', '湖', '湾', '海', '岛', '流域')


def _strip_citations(text):
    """移除百科页面里常见的引用编号和脚注痕迹。"""
    text = re.sub(r'\[[0-9]+(?:,[0-9]+)*\]', '', text)
    text = re.sub(r'\[[a-zA-Z]+\]', '', text)
    text = re.sub(r'（\s*来源：.*?）', '', text)
    return text


def _should_skip_line(line):
    """判断是否应该跳过该行（集中所有过滤逻辑）"""
    
    # 1. 元数据和URL相关
    if line.startswith(('SOURCE_TITLE:', 'http://', 'https://', '--- SOURCE:')):
        return True
    if line == 'URL:' or line.startswith('URL:'):
        return True
    if 'kns.cnki.net' in line:
        return True
    
    # 2. 新闻爬虫元数据
    NEWS_METADATA_PREFIXES = ('来源URL:', '保存时间:', '搜索词:', '标题:', '物种:', '本文作者:')
    if any(line.startswith(prefix) for prefix in NEWS_METADATA_PREFIXES):
        return True

    if line.startswith('维基共享资源中相关的多媒体资源：'):
        return True
    
    # 3. 维基百科特殊标记
    if line.startswith(('==', '===')):
        return True
    
    # 4. 噪声集合检查
    if line in SECTION_NOISE or line in NOISE_LINES:
        return True
    
    # 5. 短行且在NOISE_LINES中
    if len(line) <= 4 and line in NOISE_LINES:
        return True
    
    # 6. 百科特定的行
    if line.startswith('11种语言') or line.endswith('自由的百科全书'):
        return True
    
    if line in {'大陆简体', '不转换', '简体', '繁體', '香港繁體', '澳門繁體', '大马简体', '新加坡简体', '臺灣正體'}:
        return True
    
    # 7. 维基百科UI元素（处理末尾句号）
    line_without_punct = line.rstrip('.')
    if line in WIKI_UI_ELEMENTS or line_without_punct in WIKI_UI_ELEMENTS:
        return True
    
    # 8. 语言代码
    if line in {'中文', 'English', 'العربية', 'مصرى', 'Español', 'Français'}:
        return True
    
    # 9. "数字 languages"模式
    if re.match(r'^\d+\s+languages?$', line):
        return True
    
    # 10. 新闻页面UI元素
    if ('English' in line and '无障碍' in line) or \
       ('本月' in line and any(term in line for term in ('立夏', '立春', '立秋', '立冬'))):
        return True
    
    # 11. 页面设置说明
    if line.startswith('此页面'):
        return True
    
    # 12. 消歧义和重定向
    if line.startswith(('Not to be confused with', '(Redirected from')):
        return True
    
    # 13. 参考文献标记
    if line.startswith(('^', 'Jump up to:')):
        return True
    
    # 14. 标识符行
    IDENTIFIERS = ('ADW', 'BOLD', 'CoL', 'EoL', 'FishBase', 'GBIF', 'GISD', 'iNaturalist', 
                   'IRMNG', 'ISC', 'ITIS', 'NAS', 'NatureServe', 'NCBI', 'OTL', 'WoRMS',
                   'Wikidata', 'BioLib', 'EUNIS', 'OBIS', 'TaiCOL', 'IUCN', 'PMID', 'doi', 
                   'Taxon', 'AFD')
    if any(line.startswith(f'{prefix}:') for prefix in IDENTIFIERS):
        return True
    
    return False


def clean_text_for_llm(text, species_name=None, source_name=None):
    """清理来源文本：去掉元数据、导航目录、重复行和明显噪声。"""
    if not text:
        return ''

    cleaned_lines = []
    seen_lines = set()
    skip_next_url_line = False
    skip_section = False
    skip_language_bar = False
    
    # 后续部分（应该跳过的章节标题）
    SKIP_SECTION_MARKERS = ('References', '参考', 'Categories', 'Hidden categories:', 'Taxon identifiers')
    SKIP_SECTION_PREFIXES = ('Articles with', 'Commons category', 'Retrieved from', 'See also', 'List of')
    
    # 内容恢复关键词（用于从跳过部分恢复）
    CONTENT_KEYWORDS = ('Scientific classification', 'Habitat', 'Distribution', 'Behavior', 'Conservation', '科学分类')
    LANGUAGE_BAR_STARTS = ('保护状况', '科学分类', '特征', '分布及栖息地', '食性', '繁殖及寿命', '饲养', '保育状况')

    for raw_line in str(text).splitlines():
        line = _strip_citations(raw_line.strip())
        if not line:
            continue

        if skip_language_bar:
            if any(line.startswith(marker) for marker in LANGUAGE_BAR_STARTS):
                skip_language_bar = False
            else:
                continue

        if re.fullmatch(r'\d+\s*种语言', line) or re.fullmatch(r'\d+\s+languages?', line):
            skip_language_bar = True
            continue
        
        # 检查是否进入应该跳过的后续部分
        if line in SKIP_SECTION_MARKERS or any(line.startswith(p) for p in SKIP_SECTION_PREFIXES):
            skip_section = True
            continue
        
        # 如果在跳过部分中，检查是否恢复
        if skip_section:
            if any(keyword in line for keyword in CONTENT_KEYWORDS):
                skip_section = False
            else:
                continue
        
        # 处理URL跳过逻辑
        if skip_next_url_line:
            if line.startswith(('http://', 'https://')) or 'kns.cnki.net' in line:
                skip_next_url_line = False
            continue
        
        if line == 'URL:' or line.startswith('URL:'):
            skip_next_url_line = True
            continue
        
        # 使用统一的过滤函数
        if _should_skip_line(line):
            continue
        
        # 去重和保存
        if line in seen_lines:
            continue

        seen_lines.add(line)
        cleaned_lines.append(re.sub(r'[ \t]+', ' ', line).strip())

    # 保留换行，方便后续按段落边界切块，避免把同一段文字硬切到两个文件里。
    return '\n'.join(cleaned_lines)


def read_species_files(species_name, sources=None):
    """读取该物种的来源文本并合并。

    sources: 列表，示例 ['baidu','cnki','zh_wiki','en_wiki']。默认读取 baidu/zh_wiki/en_wiki 和 cnki（若存在）。
    对于每个来源会截取有限长度以节省 token。
    """
    if sources is None:
        # 默认顺序：百度百科 -> 中文维基 -> 英文维基 -> CNKI -> 新闻
        sources = ['baidu', 'zh_wiki', 'en_wiki', 'cnki', 'news']

    content_buffer = []
    
    # 本地百科/爬虫命名约定
    suffix_map = {
        'baidu': f"{species_name}_baidu.txt",
        'zh_wiki': f"{species_name}_zh_wiki.txt",
        'en_wiki': f"{species_name}_en_wiki.txt",
    }

    for src in sources:
        if src == 'cnki':
            # CNKI 可能有多个文件：species_cnki_*.txt
            pattern = os.path.join(CNKI_INPUT_DIR, species_name, f"{species_name}_cnki_*.txt")
            files = sorted(glob.glob(pattern))
            for p in files:
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        text = f.read()
                        text = clean_text_for_llm(text, species_name=species_name, source_name='cnki')
                        if not text:
                            continue
                        content_buffer.append(f"\n--- SOURCE: CNKI ({os.path.basename(p)}) ---\n{text[:6000]}")
                except Exception as e:
                    print(f"⚠️ 读取 CNKI 文件 {p} 失败: {e}")
        else:
            fname = suffix_map.get(src)
            if not fname:
                continue
            filepath = os.path.join(ENCYCLOPEDIA_INPUT_DIR, fname)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        text = f.read()
                        source_name = src.upper()
                        text = clean_text_for_llm(text, species_name=species_name, source_name=src)
                        if not text:
                            continue
                        content_buffer.append(f"\n--- SOURCE: {source_name} ---\n{text[:4000]}")
                except Exception as e:
                    print(f"⚠️ 读取文件 {filepath} 失败: {e}")

    # 合并时限制总长度，避免超出 token
    merged = "\n".join(content_buffer)
    if len(merged) > 12000:
        merged = merged[:12000]
    return merged


def split_text_into_chunks(text, max_chars=CNKI_CHUNK_CHAR_LIMIT):
    """按段落优先进行切块，尽量避免把同一段拆到两个文件里。"""
    if not text:
        return []

    text = str(text).strip()
    if len(text) <= max_chars:
        return [text]

    chunks = []
    paragraphs = [p.strip() for p in re.split(r'\n\s*\n+', text) if p.strip()]
    current_parts = []
    current_length = 0

    def flush_current():
        nonlocal current_parts, current_length
        if current_parts:
            chunks.append('\n\n'.join(current_parts).strip())
            current_parts = []
            current_length = 0

    for paragraph in paragraphs:
        paragraph_length = len(paragraph)

        if paragraph_length > max_chars:
            flush_current()
            sentence_parts = [part.strip() for part in re.split(r'(?<=[。！？!?；;.!?])\s*', paragraph) if part.strip()]
            if not sentence_parts:
                sentence_parts = [paragraph]

            sentence_buffer = []
            sentence_length = 0

            def flush_sentence_buffer():
                nonlocal sentence_buffer, sentence_length
                if sentence_buffer:
                    chunks.append(' '.join(sentence_buffer).strip())
                    sentence_buffer = []
                    sentence_length = 0

            for sentence in sentence_parts:
                sentence_len = len(sentence)
                if sentence_len > max_chars:
                    flush_sentence_buffer()
                    start = 0
                    while start < sentence_len:
                        end = min(start + max_chars, sentence_len)
                        piece = sentence[start:end].strip()
                        if piece:
                            chunks.append(piece)
                        start = end
                    continue

                if sentence_buffer and sentence_length + 1 + sentence_len > max_chars:
                    flush_sentence_buffer()

                sentence_buffer.append(sentence)
                sentence_length += sentence_len + (1 if len(sentence_buffer) > 1 else 0)

            flush_sentence_buffer()
            continue

        separator_cost = 2 if current_parts else 0
        if current_parts and current_length + separator_cost + paragraph_length > max_chars:
            flush_current()

        current_parts.append(paragraph)
        current_length += paragraph_length + (2 if len(current_parts) > 1 else 0)

    flush_current()
    return chunks


def pack_file_texts_into_chunks(file_texts, max_chars):
    """按文件边界打包文本块，避免一个原始文件被切到两个输出块里。"""
    chunks = []
    current_lines = []
    current_length = 0

    def flush_current():
        nonlocal current_lines, current_length
        if current_lines:
            chunks.append('\n\n'.join(current_lines).strip())
            current_lines = []
            current_length = 0

    for file_label, file_text in file_texts:
        if not file_text:
            continue

        block_text = f"--- SOURCE: {file_label} ---\n{file_text}".strip()
        block_length = len(block_text)

        if current_lines and current_length + 2 + block_length > max_chars:
            flush_current()

        if block_length > max_chars and not current_lines:
            # 单个文件本身就超过上限时，保留为一个完整块，避免拆开同一文件。
            chunks.append(block_text)
            continue

        current_lines.append(block_text)
        current_length += block_length + (2 if len(current_lines) > 1 else 0)

    flush_current()
    return chunks


def collect_species_chunks(species_name, sources=None):
    """读取一个物种的所有来源文件。

    规则：
    - 百度/中文维基/英文维基：各自作为一个整体段发送
    - CNKI/NEWS：每个原始 txt 独立切块，切块时优先按段落边界
    """
    if sources is None:
        # 默认顺序：百度百科 -> 中文维基 -> 英文维基 -> CNKI -> 新闻
        sources = ['baidu', 'zh_wiki', 'en_wiki', 'cnki', 'news']

    chunks = []

    suffix_map = {
        'baidu': f"{species_name}_baidu.txt",
        'zh_wiki': f"{species_name}_zh_wiki.txt",
        'en_wiki': f"{species_name}_en_wiki.txt",
    }

    for src in sources:
        if src == 'cnki':
            pattern = os.path.join(CNKI_INPUT_DIR, species_name, f"{species_name}_cnki_*.txt")
            files = sorted(glob.glob(pattern))
            cnki_file_texts = []
            for p in files:
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        text = clean_text_for_llm(f.read(), species_name=species_name, source_name='cnki')
                        if not text:
                            continue
                        cnki_file_texts.append((os.path.basename(p), text))
                except Exception as e:
                    print(f"⚠️ 读取 CNKI 文件 {p} 失败: {e}")

            if cnki_file_texts:
                cnki_chunks = pack_file_texts_into_chunks(cnki_file_texts, CNKI_CHUNK_CHAR_LIMIT)
                for idx, chunk_text in enumerate(cnki_chunks, start=1):
                    chunks.append(("CNKI", idx, chunk_text))
        elif src == 'news':
            # 新闻文本目录： NEWS_INPUT_DIR/<species_name>/*.txt
            pattern = os.path.join(NEWS_INPUT_DIR, species_name, "*.txt")
            files = sorted(glob.glob(pattern))
            news_file_texts = []
            for p in files:
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        text = clean_text_for_llm(f.read(), species_name=species_name, source_name='news')
                        if not text:
                            continue
                        news_file_texts.append((os.path.basename(p), text))
                except Exception as e:
                    print(f"⚠️ 读取 NEWS 文件 {p} 失败: {e}")

            if news_file_texts:
                news_chunks = pack_file_texts_into_chunks(news_file_texts, NEWS_CHUNK_CHAR_LIMIT)
                for idx, chunk_text in enumerate(news_chunks, start=1):
                    chunks.append(("NEWS", idx, chunk_text))
        else:
            fname = suffix_map.get(src)
            if not fname:
                continue
            filepath = os.path.join(ENCYCLOPEDIA_INPUT_DIR, fname)
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        text = clean_text_for_llm(f.read(), species_name=species_name, source_name=src)
                        if not text:
                            continue
                        source_label = src.upper()
                        chunks.append((source_label, 1, text))
                except Exception as e:
                    print(f"⚠️ 读取文件 {filepath} 失败: {e}")

    return chunks


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

    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return ""

    header_index = 0
    for idx, line in enumerate(lines):
        parts = [part.strip() for part in line.split(',')]
        if len(parts) >= 4 and parts[:4] == CSV_COLUMNS:
            header_index = idx
            break

    normalized_rows = []
    for line in lines[header_index + 1:]:
        parts = line.split(',', 3)
        if len(parts) < 4:
            # 模型偶尔会在最后一行截断，直接丢弃尾部半行，避免破坏 CSV 预览和解析。
            break
        normalized_rows.append([part.strip() for part in parts[:4]])

    if not normalized_rows:
        return ""

    df = pd.DataFrame(normalized_rows, columns=CSV_COLUMNS)
    return df.to_csv(index=False, lineterminator='\n')


def merge_and_deduplicate_csv_texts(species_name, raw_outputs):
    """合并多个 CSV 文本，并按整行去重后输出标准 CSV。"""
    frames = []

    for raw_output in raw_outputs:
        csv_text = clean_csv_output(raw_output)
        if not csv_text:
            continue

        try:
            df = pd.read_csv(StringIO(csv_text), dtype=str, keep_default_na=False)
        except Exception as e:
            print(f"  ⚠️ 跳过一段无法解析的 CSV 输出: {e}")
            continue

        df.columns = [c.strip() for c in df.columns]
        if not set(CSV_COLUMNS).issubset(df.columns):
            print(f"  ⚠️ 跳过一段表头不完整的输出: {df.columns.tolist()}")
            continue

        frames.append(df[CSV_COLUMNS])

    if not frames:
        return ""

    merged = pd.concat(frames, ignore_index=True)
    merged = merged.fillna('').astype(str)
    # 避免使用已弃用的 applymap，使用更兼容的列映射
    merged = merged.apply(lambda col: col.map(lambda v: v.strip() if isinstance(v, str) else v))

    # 统一当前物种的主名，避免模型把别名写到 species-centric 关系的 Entity1 上。
    species_aliases = {species_name}
    alias_rows = merged[merged['Relationship'] == 'HAS_ALIAS']
    for _, row in alias_rows.iterrows():
        e1 = str(row['Entity1']).strip()
        e2 = str(row['Entity2']).strip()
        if e1 == species_name and e2:
            species_aliases.add(e2)
        if e2 == species_name and e1:
            species_aliases.add(e1)

    species_centric_relations = {
        'HAS_ALIAS', 'BELONGS_TO', 'NATIVE_TO', 'REPORTED_IN', 'THRIVES_IN',
        'INTRODUCED_VIA', 'PREYS_ON', 'COMPETES_WITH', 'CAUSES', 'SUPPRESSED_BY',
        'HAS_MORPHOLOGY', 'HAS_HABIT'
    }

    def normalize_row(row):
        relation = str(row['Relationship']).strip()
        entity1 = str(row['Entity1']).strip()
        entity2 = str(row['Entity2']).strip()

        if relation == 'HAS_ALIAS':
            if entity2 == species_name and entity1 != species_name:
                row['Entity1'], row['Entity2'] = species_name, entity1
            elif entity1 in species_aliases and entity1 != species_name and entity2:
                row['Entity1'] = species_name
            elif entity1 != species_name and entity2 in species_aliases and entity2 != species_name:
                row['Entity1'] = species_name
            return row

        if relation in species_centric_relations and entity1 in species_aliases and entity1 != species_name:
            row['Entity1'] = species_name
        return row

    merged = merged.apply(normalize_row, axis=1)
    merged = merged[(merged['Entity1'] != '') | (merged['Relationship'] != '') | (merged['Entity2'] != '') | (merged['Property'] != '')]
    merged = merged.drop_duplicates(subset=['Entity1', 'Relationship', 'Entity2', 'Property'])
    return merged.to_csv(index=False, lineterminator='\n')


def save_text_document(directory, filename, content):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    return path


def load_saved_chunks(species_name):
    chunk_dir = os.path.join(OUTPUT_DIR, 'chunks', species_name)
    if not os.path.isdir(chunk_dir):
        return []

    loaded_chunks = []
    for filename in sorted(glob.glob(os.path.join(chunk_dir, '*.txt'))):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                chunk_text = f.read().strip()
            if not chunk_text:
                continue

            stem = os.path.splitext(os.path.basename(filename))[0]
            parts = stem.split('_', 2)
            if len(parts) >= 3:
                source_label = parts[1]
                part_token = parts[2]
            elif len(parts) == 2:
                source_label = parts[1]
                part_token = '1'
            else:
                source_label = 'SAVED'
                part_token = '1'

            match = re.search(r'(\d+)$', str(part_token))
            part_index = int(match.group(1)) if match else 1
            loaded_chunks.append((source_label, part_index, chunk_text))
        except Exception as e:
            print(f"⚠️ 读取历史 chunk {filename} 失败: {e}")

    return loaded_chunks


# ================= 4. 主程序 =================

def main():
    # 允许用户在运行前选择提示词
    prompt_opts = _available_prompts()
    if len(prompt_opts) > 1:
        print('\n可用提示词（选择一个）:')
        for i, (name, _) in enumerate(prompt_opts, start=1):
            print(f"  {i}. {name}")
        p_choice = input('输入提示词编号（回车使用第1个/内嵌提示词）: ').strip()
        try:
            if p_choice:
                idx = int(p_choice)
                if 1 <= idx <= len(prompt_opts):
                    global SYSTEM_PROMPT
                    SYSTEM_PROMPT = prompt_opts[idx-1][1]
        except Exception:
            pass

    # 确保至少有一个输入目录存在
    if not (os.path.exists(ENCYCLOPEDIA_INPUT_DIR) or os.path.exists(CNKI_INPUT_DIR) or os.path.exists(NEWS_INPUT_DIR)):
        print(f"❌ 错误: 找不到输入目录 {ENCYCLOPEDIA_INPUT_DIR} 或 {CNKI_INPUT_DIR} 或 {NEWS_INPUT_DIR}，请先运行爬虫脚本！")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    total_triplets = 0

    # 交互选择物种与数据源
    print('\n可选物种：')
    for i, s in enumerate(SPECIES_LIST, start=1):
        print(f"  {i}. {s}")
    print("  0. 全部")
    choice = input('输入物种编号（逗号分隔）或按回车处理全部: ').strip()
    if not choice:
        selected_species = SPECIES_LIST
    else:
        selected_species = []
        for part in choice.replace('，',',').split(','):
            part = part.strip()
            if not part:
                continue
            if part == '0':
                selected_species = SPECIES_LIST
                break
            if part.isdigit():
                idx = int(part)
                if 1 <= idx <= len(SPECIES_LIST):
                    selected_species.append(SPECIES_LIST[idx-1])

    # 选择数据源，默认顺序：百科 -> CNKI -> 新闻
    default_sources = ['baidu', 'zh_wiki', 'en_wiki', 'cnki', 'news']
    print('\n可选数据源（按顺序执行）：')
    for i, src in enumerate(default_sources, start=1):
        print(f"  {i}. {src}")
    src_choice = input('输入数据源编号（逗号分隔），或按回车使用默认全部: ').strip()
    if not src_choice:
        selected_sources = default_sources
    else:
        selected_sources = []
        for part in src_choice.replace('，',',').split(','):
            part = part.strip()
            if not part:
                continue
            if part.isdigit():
                idx = int(part)
                if 1 <= idx <= len(default_sources):
                    selected_sources.append(default_sources[idx-1])

    for species in selected_species:
        print(f"\n🔵 开始处理: {species}")

        # 1. 优先读取历史 chunks；如果没有，再按用户选择的数据源重新分块
        species_chunks = load_saved_chunks(species)
        if species_chunks:
            print(f"  📂 已找到 {len(species_chunks)} 个历史文本块")
        else:
            species_chunks = collect_species_chunks(species, sources=selected_sources)
            if not species_chunks:
                print(f"  ⚠️ 跳过: 没有找到 {species} 的任何文本文件")
                continue

        print(f"  📚 共拆分出 {len(species_chunks)} 个文本块")

        # 2. 分块 AI 抽取
        raw_results = []
        chunk_dir = os.path.join(OUTPUT_DIR, 'chunks', species)
        raw_dir = os.path.join(OUTPUT_DIR, 'raw_outputs', species)
        for chunk_index, (source_label, part_index, chunk_text) in enumerate(species_chunks, start=1):
            part_suffix = '' if int(part_index) == 1 else f"_part{part_index}"
            print(f"  🧩 抽取第 {chunk_index}/{len(species_chunks)} 块: {source_label}{part_suffix} (文本长度: {len(chunk_text)})")
            chunk_file = save_text_document(
                chunk_dir,
                f"{chunk_index:03d}_{source_label}{part_suffix}.txt",
                chunk_text,
            )
            print(f"    📝 原始文本已保存: {chunk_file}")
            raw_result = extract_knowledge(species, chunk_text)
            csv_result = clean_csv_output(raw_result)
            if csv_result:
                raw_results.append(csv_result)
                csv_raw_file = save_text_document(
                    raw_dir,
                    f"{chunk_index:03d}_{source_label}{part_suffix}.csv",
                    csv_result,
                )
                print(f"    📄 CSV 抽取结果已保存: {csv_raw_file}")
            elif raw_result:
                raw_file = save_text_document(
                    raw_dir,
                    f"{chunk_index:03d}_{source_label}{part_suffix}.txt",
                    raw_result,
                )
                print(f"    📄 原始抽取结果已保存: {raw_file}")
            time.sleep(1)

        # 3. 数据合并、去重与保存
        csv_content = merge_and_deduplicate_csv_texts(species, raw_results)
        if csv_content:

            # 保存文件
            save_path = os.path.join(OUTPUT_DIR, f"{species}_triplets.csv")
            with open(save_path, "w", encoding="utf-8", newline="") as f:
                f.write(csv_content)

            # 统计行数（减去表头）
            count = max(0, len(csv_content.split('\n')) - 1)
            total_triplets += count
            print(f"  ✅ 提取成功! 已保存至 {save_path} (约 {count} 条关系)")

            # 打印前几行看看效果
            print("  👀 数据预览:")
            print("\n".join(csv_content.split('\n')[:3]))
        else:
            print("  ❌ 提取失败，所有分块都没有得到可用结果")

    print(f"\n🏁 所有任务完成。共提取约 {total_triplets} 条三元组数据。")
    print(f"📂 结果保存在: {os.path.abspath(OUTPUT_DIR)}")


if __name__ == "__main__":
    main()
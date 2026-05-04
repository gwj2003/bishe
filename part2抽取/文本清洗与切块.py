# -*- coding: utf-8 -*-
"""
文本清洗与切块模块。

当前策略：
1. 针对 CNKI 和新闻文本，仅移除 URL 相关行，保留其他所有内容。
2. 针对 Baike 文本，剔除维基/百科特有的UI导航、引用标记，并截断底部的参考文献和外部链接。
"""

import os
import glob
import re

try:
    from species_config import species_names
except ImportError:
    species_names = ["豹纹翼甲鲶", "大鳄龟", "鳄雀鳝"]

CNKI_INPUT_DIR = "data/cnki_texts"
NEWS_INPUT_DIR = "data/news_texts"
BAIKE_INPUT_DIR = "data/encyclopedia_texts"
OUTPUT_DIR = "data/triplets"

CNKI_CHUNK_CHAR_LIMIT = 30000
NEWS_CHUNK_CHAR_LIMIT = 30000
BAIKE_CHUNK_CHAR_LIMIT = 30000

SPECIES_LIST = species_names

# ==========================================
# 百科数据专属清洗规则 (Baike Cleaning Rules)
# ==========================================

# 百科常见 UI 噪声（精确匹配删除）
ENCYCLOPEDIA_NOISE_EXACT = {
    # 英文维基
    "Toggle the table of contents", "Article", "Talk", "Read", "Edit", "View history", "Tools", 
    "move to sidebarhide", "Actions", "General", "What links here", "Related changes", 
    "Upload file", "Permanent link", "Page information", "Cite this page", "Get shortened URL", 
    "Edit interlanguage links", "Print/export", "Download as PDF", "Printable version", 
    "In other projects", "Wikimedia Commons", "Wikispecies", "Wikidata item", "Appearance", 
    "Text", "Small", "Standard", "Large", "This page always uses small font size", "Width", 
    "Wide", "The content is as wide as possible for your browser window.", "Color", "Automatic", 
    "Light", "Dark", "This page is always in light mode.", "From Wikipedia, the free encyclopedia", 
    "Expand all", "Edit links", "English","汉漢", "标准", "show", "List", "⊞", "⊟", "⊞Lithobates spp.", "⊟",
    
    # 中文维基
    "开关目录", "条目", "讨论", "大陆简体", "不转换", "简体", "繁體", "香港繁體", "澳門繁體", 
    "大马简体", "新加坡简体", "臺灣正體", "阅读", "查看历史", "工具", "移至侧栏隐藏", "操作", 
    "常规", "链入页面", "相关更改", "上传文件", "固定链接", "页面信息", "引用此页", "获取短链接", 
    "跨语言链接", "打印/导出", "下载为PDF", "可打印版", "在其他项目中", "维基共享资源", 
    "维基数据项目", "维基物种", "外观", "文本", "小", "大", "此页面始终使用小字号", "宽度", "宽", 
    "内容会尽可能占满您的浏览器窗口宽度。", "颜色 （测试版）", "颜色", "自动", "浅色", "深色", 
    "此页面始终处于浅色模式。", "维基百科，自由的百科全书", "链接", "目录",
    
    # 百度百科
    "订阅", "0有用+1", "0", "播报", "编辑", "讨论", "上传视频"
}

# 百科常见噪声前缀（前缀匹配删除）
ENCYCLOPEDIA_NOISE_PREFIXES = (
    "本词条由", "同义词", "检索自“https://", "Retrieved from \"https://",
    "分类：", "隐藏分类：", "Categories:", "Hidden categories:",
    "^ Jump up to:", "^ 跳转到：", "此条目的语调或风格", "请根据指南协助改善",
    "此条目需要", "请邀请适合的人士","提示：此条目的主题", "关于另", "此条目介绍的是",
    "This article is about", "For the ", "This article may require", "The specific problem is:", 
    "Please help improve", "This section needs", "Unsourced material may be",
    "(Redirected from", "（重定向自", "^"
)

# 遇到这些标题，直接丢弃后面的所有内容（通常是页面底部的参考文献和标识码）
TRUNCATE_TRIGGERS = {
    "Taxon identifiers", "分类单元识别码", "Authority control databases",
    "References", "参考文献", "External links", "外部链接", "Further reading", "参考资料","参考"
}


def clean_baike_text(text: str) -> str:
    """百科文本专属清洗逻辑。"""
    if not text:
        return ""

    # 1. 全局正则清洗
    # 移除类似 的检索标签
    text = re.sub(r'\\', '', text, flags=re.IGNORECASE)
    # 移除百度/维基常见的文内引用标记，如 [1], [6-7]
    text = re.sub(r'\[\d+(?:-\d+)?\s*\]', '', text)
    
    cleaned_lines = []
    lines = text.splitlines()
    
    in_language_list = False
    skip_mode = False
    prev_line = ""


    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # 2. 底部截断逻辑
        if line in TRUNCATE_TRIGGERS:
            skip_mode = True
            
        if skip_mode:
            continue

        # 3. 语言列表屏蔽逻辑 (屏蔽 "11 languages" 到 "Edit links" 之间的所有语言名称)
        if re.match(r'^(\d+\s*languages|\d+\s*种语言)$', line):
            in_language_list = True
            continue
        if in_language_list:
            if line in ("Edit links", "链接"):
                in_language_list = False
            continue

        # 4. 噪音过滤逻辑
        if line in ENCYCLOPEDIA_NOISE_EXACT:
            continue
            
        if line.startswith(ENCYCLOPEDIA_NOISE_PREFIXES):
            continue
            
        # 过滤维基百科特有的单行引用（通常以 ^ 开头）
        if line.startswith('^ ') and len(line) > 5:
            continue

        if line == prev_line:
            continue
        prev_line = line

        # 5. 合并多余空格并保存
        line = re.sub(r'[ \t]+', ' ', line)
        cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


def clean_text_for_llm(text, source_name=None):
    """
    CNKI和NEWS统一清洗逻辑：仅移除 URL 相关行，保留其他所有内容。
    """
    if not text:
        return ''

    cleaned_lines = []
    skip_next_url_line = False

    for raw_line in str(text).splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # 处理多行 URL 结构 (如上一行为 "URL:")
        if skip_next_url_line:
            if line.startswith(('http://', 'https://')) or 'kns.cnki.net' in line:
                skip_next_url_line = False
                continue
            skip_next_url_line = False

        # 匹配单独的 URL 标签
        if line == 'URL:' or line == '来源URL:':
            skip_next_url_line = True
            continue
            
        # 匹配当前行就包含 URL 或 URL 标签的情况
        if line.startswith('URL:') or line.startswith('来源URL:') or 'http://' in line or 'https://' in line or 'kns.cnki.net' in line:
            continue

        cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


def split_text_into_chunks(text, max_chars=CNKI_CHUNK_CHAR_LIMIT):
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
    """按文件边界将若干 (filename, text) 对打包成不超过 `max_chars` 的块。"""
    chunks = []
    current_blocks = []
    current_length = 0

    def flush_current():
        nonlocal current_blocks, current_length
        if current_blocks:
            chunks.append('\n\n'.join(current_blocks).strip())
            current_blocks = []
            current_length = 0

    for file_label, file_text in file_texts:
        if not file_text:
            continue

        block_text = f"--- SOURCE: {file_label} ---\n{file_text}".strip()
        block_length = len(block_text)

        if current_blocks and current_length + 2 + block_length > max_chars:
            flush_current()

        if block_length > max_chars and not current_blocks:
            chunks.append(block_text)
            continue

        current_blocks.append(block_text)
        current_length += block_length + (2 if len(current_blocks) > 1 else 0)

    flush_current()
    return chunks


def save_text_document(directory, filename, content):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, filename)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(content)
    return path


def collect_species_chunks(species_name, sources=None):
    if sources is None:
        sources = ['cnki', 'news', 'baike']

    chunks = []

    for src in sources:
        if src == 'cnki':
            pattern = os.path.join(CNKI_INPUT_DIR, species_name, f"{species_name}_cnki_*.txt")
            files = sorted(glob.glob(pattern))
            cnki_file_texts = []
            for p in files:
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        text = clean_text_for_llm(f.read(), source_name='cnki')
                        if not text:
                            continue
                        cnki_file_texts.append((os.path.basename(p), text))
                except Exception as e:
                    print(f"⚠️ 读取 CNKI 文件 {p} 失败: {e}")

            if cnki_file_texts:
                for idx, chunk_text in enumerate(pack_file_texts_into_chunks(cnki_file_texts, CNKI_CHUNK_CHAR_LIMIT), start=1):
                    chunks.append(("CNKI", idx, chunk_text))

        elif src == 'news':
            pattern = os.path.join(NEWS_INPUT_DIR, species_name, "*.txt")
            files = sorted(glob.glob(pattern))
            news_file_texts = []
            for p in files:
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        text = clean_text_for_llm(f.read(), source_name='news')
                        if not text:
                            continue
                        news_file_texts.append((os.path.basename(p), text))
                except Exception as e:
                    print(f"⚠️ 读取 NEWS 文件 {p} 失败: {e}")

            if news_file_texts:
                for idx, chunk_text in enumerate(pack_file_texts_into_chunks(news_file_texts, NEWS_CHUNK_CHAR_LIMIT), start=1):
                    chunks.append(("NEWS", idx, chunk_text))
                    
        elif src == 'baike':
            pattern = os.path.join(BAIKE_INPUT_DIR, species_name, "*.txt")
            # 兼容直接放在 baike_texts 根目录的情况
            if not glob.glob(pattern):
                pattern = os.path.join(BAIKE_INPUT_DIR, f"{species_name}_*.txt")
            
            files = sorted(glob.glob(pattern))
            baike_file_texts = []
            for p in files:
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        text = clean_baike_text(f.read())
                        if not text:
                            continue
                        baike_file_texts.append((os.path.basename(p), text))
                except Exception as e:
                    print(f"⚠️ 读取 BAIKE 文件 {p} 失败: {e}")

            if baike_file_texts:
                for idx, chunk_text in enumerate(pack_file_texts_into_chunks(baike_file_texts, BAIKE_CHUNK_CHAR_LIMIT), start=1):
                    chunks.append(("BAIKE", idx, chunk_text))

    return chunks


def main():
    if not (os.path.exists(CNKI_INPUT_DIR) or os.path.exists(NEWS_INPUT_DIR) or os.path.exists(BAIKE_INPUT_DIR)):
        print(f"❌ 错误: 找不到任何输入目录 (cnki, news, 或 baike)，请先运行爬虫脚本！")
        return

    os.makedirs(OUTPUT_DIR, exist_ok=True)

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

    default_sources = ['baike','cnki', 'news']
    print('\n可选数据源（按顺序执行）：')
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

    for species in selected_species:
        print(f"\n🔵 开始预处理: {species}")
        species_chunks = collect_species_chunks(species, sources=selected_sources)
        if not species_chunks:
            print(f"  ⚠️ 跳过: 没有找到 {species} 的任何文本文件")
            continue

        print(f"  📚 共生成 {len(species_chunks)} 个文本块")
        chunk_dir = os.path.join(OUTPUT_DIR, 'chunks', species)
        for chunk_index, (source_label, part_index, chunk_text) in enumerate(species_chunks, start=1):
            chunk_file = save_text_document(
                chunk_dir,
                f"{source_label}_{int(part_index):03d}.txt",
                chunk_text,
            )
            print(f"    📝 已保存: {chunk_file} (字数: {len(chunk_text)})")

    print(f"\n🏁 预处理完成，chunk 保存在: {os.path.abspath(os.path.join(OUTPUT_DIR, 'chunks'))}")


if __name__ == "__main__":
    main()
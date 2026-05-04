# -*- coding: utf-8 -*-
from DrissionPage import ChromiumPage
import os
import time
import re
import argparse
from species_config import DEFAULT_ENCYCLOPEDIA_TYPES, species_list, species_names


# ================= 2. 数据清洗工具 =================
def clean_text(raw_text):
    if not raw_text: return ""
    text = re.sub(r'\[.*?\]', '', raw_text)
    text = re.sub(r'\u3000', ' ', text).replace('\xa0', ' ')
    text = re.sub(r'\n{2,}', '\n', text)
    text = text.replace("编辑", "").replace("锁定", "")
    return text.strip()


def save_to_file(folder, filename, content):
    # 稍微放宽限制，方便调试
    if not content or len(content) < 50:
        print(f"    ❌ 内容过短或为空 ({len(content) if content else 0}字)，未保存: {filename}")
        return False

    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    with open(filepath, "w", encoding='utf-8') as f:
        f.write(content)
    print(f"    💾 已保存: {filename} (字数: {len(content)})")
    return True


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


def choose_encyclopedia_types(type_options):
    print('\n可选百科类型：')
    for idx, option in enumerate(type_options, start=1):
        print(f"  {idx}. {option['label']}")
    print('  0. 全部')

    while True:
        choice = input('请输入编号，多个编号用逗号分隔：').strip()
        if not choice or choice == '0':
            return [option['key'] for option in type_options]

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
            if idx == 0:
                return [option['key'] for option in type_options]
            if 1 <= idx <= len(type_options):
                key = type_options[idx - 1]['key']
                if key not in selected:
                    selected.append(key)
            else:
                valid = False
                break

        if valid and selected:
            return selected

        print('输入无效，请重新输入。')


def extract_baidu_intro(text, species_name, intro_window_chars=12000):
    if not text:
        return ''

    scan_text = text[:intro_window_chars] if intro_window_chars and len(text) > intro_window_chars else text

    section_markers = [
        '形态特征', '近种区别', '栖息环境', '生活习性', '分布范围', '繁殖方式',
        '亚种分化', '入侵物种', '防治方法', '物种管理', '目录'
    ]
    section_pattern = '|'.join(map(re.escape, section_markers))

    patterns = [
        rf'{re.escape(species_name)}[\s\S]*?(?=\n(?:{section_pattern}))',
        rf'{re.escape(species_name)}[\s\S]*?(?=\n\s*\n(?:{section_pattern}))',
    ]

    for pattern in patterns:
        match = re.search(pattern, scan_text)
        if match:
            intro = match.group(0).strip()
            if intro:
                return intro

    return ''


# ================= 3. 核心爬取逻辑 =================

def get_baidu(page, item_data, page_wait=0.6, intro_window_chars=12000):
    """百度百科爬取 - 支持自定义URL"""
    name = item_data["name"]
    # 如果指定了 url 就用指定的，否则自动拼接
    url = item_data.get("baidu_url") or f"https://baike.baidu.com/item/{name}"

    print(f"  👉 [百度] {url}")

    try:
        page.get(url)
        time.sleep(page_wait)

        # 调试信息：打印当前标题，看看是不是跳到了验证码或消歧页
        print(f"    (当前页面标题: {page.title})")

        if "安全验证" in page.title:
            print("    ⚠️ 触发验证码！请手动处理！")
            time.sleep(10)

        raw_parts = []

        # 先尝试抓导语/摘要块
        summary = page.ele('.lemma-summary') or page.ele('.lemmaDesc') or page.ele('.summary-content')
        if summary and getattr(summary, 'text', '').strip():
            raw_parts.append(summary.text.strip())

        # 某些页面导语只存在于渲染后的页面文本里，直接取 innerText 再按章节切分更稳
        try:
            body_text = page.run_js("return document.body ? document.body.innerText || '' : ''") or ''
        except Exception:
            body_ele = page.ele('body')
            body_text = (body_ele.text if body_ele else '')
        if body_text:
            intro_text = extract_baidu_intro(body_text, name, intro_window_chars=intro_window_chars)
            if intro_text:
                raw_parts.append(intro_text)

        # 追加正文主体，保证目录后的完整内容不会丢失
        content_ele = page.ele('.main-content') or page.ele('.lemma-main-content') or page.ele('.J-lemma-content')
        if content_ele and (content_ele.text or '').strip():
            raw_parts.append(content_ele.text.strip())

        # 最后保底抓整个内容
        if not raw_parts:
            fallback_ele = page.ele('body')
            raw_parts.append(fallback_ele.text if fallback_ele else '')

        # 去重并保持顺序
        unique_parts = []
        for part in raw_parts:
            if part and part not in unique_parts:
                unique_parts.append(part)

        raw_text = '\n\n'.join(unique_parts)

        lead_markers = [
            f'{name}，是',
            f'{name}是',
            f'{name}（学名：',
            f'{name}（学名:'
        ]
        lead_start = None
        for marker in lead_markers:
            pos = raw_text.find(marker)
            if pos != -1 and (lead_start is None or pos < lead_start):
                lead_start = pos
        if lead_start is not None and lead_start > 0:
            raw_text = raw_text[lead_start:]

        return clean_text(raw_text)

    except Exception as e:
        print(f"    ❌ 百度出错: {e}")
        return None


def get_zh_wiki(page, item_data):
    url = item_data.get('zh_wiki_url') or f"https://zh.wikipedia.org/wiki/{item_data['name']}"
    print(f"  👉 [中维] {url}")
    try:
        page.get(url)
        if page.ele('#content', timeout=3):
            return clean_text(page.ele('#content').text)
    except Exception as e:
        print(f"    ⚠️ 中维跳过: {str(e)[:50]}")
    return None


def get_en_wiki(page, scientific_name):
    formatted_name = scientific_name.replace(" ", "_")
    url = f"https://en.wikipedia.org/wiki/{formatted_name}"
    print(f"  👉 [英维] {url}")
    try:
        page.get(url)
        if page.ele('#content', timeout=3):
            return clean_text(page.ele('#content').text)
    except Exception as e:
        print(f"    ⚠️ 英维跳过: {str(e)[:50]}")
    return None


# ================= 4. 主程序 =================

def main():
    parser = argparse.ArgumentParser(description='百科抓取脚本')
    parser.add_argument('--page-wait', type=float, default=0.6, help='每次打开页面后的等待秒数，默认 0.6')
    parser.add_argument('--item-delay', type=float, default=0.5, help='每个物种抓取完后的等待秒数，默认 0.5')
    parser.add_argument('--intro-window', type=int, default=12000, help='导语匹配时只扫描页面前多少字符，默认 12000')
    args = parser.parse_args()

    page = ChromiumPage()

    print('🚀 启动选择：')
    selected_species_names = choose_items(species_names, '可选物种：', allow_all=True)
    selected_types = choose_encyclopedia_types(DEFAULT_ENCYCLOPEDIA_TYPES)

    selected_species = [item for item in species_list if item['name'] in selected_species_names]
    print(f"\n开始任务，物种 {len(selected_species)} 个，百科类型 {len(selected_types)} 个...\n")

    save_dir = os.path.join("data", "encyclopedia_texts")

    for item in selected_species:
        cn_name = item["name"]
        print(f"🔵 正在处理: 【{cn_name}】")

        if 'baidu' in selected_types:
            content = get_baidu(page, item, page_wait=args.page_wait, intro_window_chars=args.intro_window)
            save_to_file(save_dir, f"{cn_name}_baidu.txt", content)

        if 'zh_wiki' in selected_types:
            content = get_zh_wiki(page, item)
            save_to_file(save_dir, f"{cn_name}_zh_wiki.txt", content)

        if 'en_wiki' in selected_types:
            content = get_en_wiki(page, item["latin"])
            save_to_file(save_dir, f"{cn_name}_en_wiki.txt", content)

        print("-" * 40)
        time.sleep(args.item_delay)

    print(f"\n🏁 全部完成！请查看 {save_dir} 文件夹。")


if __name__ == "__main__":
    main()
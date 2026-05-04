# -*- coding: utf-8 -*-
import argparse
import csv
import os
import re
import sys
import time
from datetime import datetime
from urllib.parse import quote_plus

from DrissionPage import ChromiumPage
from species_config import species_names

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


DEFAULT_OUTPUT_DIR = os.path.join("data", "news_texts")


def clean_filename(value, max_len=60):
    value = re.sub(r'[\\/:*?"<>|]+', "_", value)
    value = re.sub(r"\s+", "_", value).strip("._ ")
    return value[:max_len] or "untitled"


def clean_text(text):
    if not text:
        return ""

    text = text.replace("\xa0", " ").replace("\u3000", " ")
    lines = []
    seen = set()
    noise_keywords = (
        "版权", "ICP备", "登录", "注册", "分享", "扫一扫", "客户端",
        "广告", "免责声明", "友情链接", "网站地图", "返回首页",
    )

    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if len(line) < 12:
            continue
        if any(keyword in line for keyword in noise_keywords):
            continue
        if line in seen:
            continue
        seen.add(line)
        lines.append(line)

    return "\n".join(lines).strip()


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


def get_page_text_by_js(page_tab):
    try:
        return page_tab.run_js(
            """
            const selectors = [
                'article', '.article', '.article-content', '.content',
                '.main', '.main-content', '.TRS_Editor', '.pages_content',
                '.con', '.detail', '#content', '#article'
            ];
            const parts = [];
            for (const selector of selectors) {
                for (const node of document.querySelectorAll(selector)) {
                    const text = (node.innerText || '').trim();
                    if (text.length > 80) parts.push(text);
                }
            }
            const bodyText = document.body ? (document.body.innerText || '').trim() : '';
            if (bodyText) parts.push(bodyText);
            return parts.join('\\n\\n');
            """
        ) or ""
    except Exception:
        return ""


def load_existing_urls(output_dir, species_name):
    species_dir = os.path.join(output_dir, clean_filename(species_name))
    urls = set()
    if not os.path.isdir(species_dir):
        return urls

    # 尝试从 manifest.csv 中读取
    manifest_path = os.path.join(output_dir, "manifest.csv")
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8-sig", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("species") == species_name and row.get("url"):
                        urls.add(row.get("url"))
        except Exception:
            pass

    # 保险：也从已有文本文件中解析 "来源URL:" 行
    for fname in os.listdir(species_dir):
        if not fname.lower().endswith('.txt'):
            continue
        try:
            with open(os.path.join(species_dir, fname), "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("来源URL:"):
                        url = line.split("来源URL:", 1)[1].strip()
                        if url:
                            urls.add(url)
                        break
        except Exception:
            continue

    return urls


def show_existing_texts(output_dir, species_name, preview_chars=300):
    species_dir = os.path.join(output_dir, clean_filename(species_name))
    if not os.path.isdir(species_dir):
        print("    （尚无已保存文本）")
        return

    files = sorted([f for f in os.listdir(species_dir) if f.lower().endswith('.txt')])
    if not files:
        print("    （尚无已保存文本）")
        return

    print(f"    已保存 {len(files)} 篇：")
    for fname in files:
        path = os.path.join(species_dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                head = f.read(preview_chars)
                head = head.replace('\n', ' ')[:preview_chars]
                print(f"      - {fname} -> {head[:preview_chars]}{'...' if len(head)==preview_chars else ''}")
        except Exception:
            print(f"      - {fname} -> （读取失败）")


def wait_for_page_text(page_tab, min_chars=80, timeout=8):
    deadline = time.time() + timeout
    best_text = ""

    while time.time() < deadline:
        text = get_page_text_by_js(page_tab)
        if len(text) > len(best_text):
            best_text = text
        if len(clean_text(text)) >= min_chars:
            break
        time.sleep(0.5)

    return best_text


def extract_main_text(page_tab, max_chars=8000):
    selectors = [
        "tag:article",
        ".article",
        ".article-content",
        ".content",
        ".main",
        ".main-content",
        ".TRS_Editor",
        ".pages_content",
        ".con",
        ".detail",
        "#content",
        "#article",
        "tag:body",
    ]

    candidates = []
    for selector in selectors:
        try:
            elements = page_tab.eles(selector, timeout=1)
        except Exception:
            elements = []
        for ele in elements:
            text = clean_text(getattr(ele, "text", ""))
            if text:
                candidates.append(text)

    js_text = clean_text(wait_for_page_text(page_tab))
    if js_text:
        candidates.append(js_text)

    if not candidates:
        return ""

    main_text = max(candidates, key=len)
    return main_text[:max_chars]


def build_search_queries(species_name):
    return [
        f"{species_name} 发现 OR 捕获 site:gov.cn",
        f"{species_name} 入侵 OR 泛滥 农业农村局",
        f"{species_name} 现身 OR 抓获 新闻",
    ]


def save_article(output_dir, species_name, index, title, url, query, article_text):
    species_dir = os.path.join(output_dir, clean_filename(species_name))
    os.makedirs(species_dir, exist_ok=True)
    filename = f"{index:03d}_{clean_filename(title)}.txt"
    path = os.path.join(species_dir, filename)
    saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    content = (
        f"物种: {species_name}\n"
        f"标题: {title}\n"
        f"来源URL: {url}\n"
        f"搜索词: {query}\n"
        f"保存时间: {saved_at}\n"
        f"{'-' * 60}\n\n"
        f"{article_text}\n"
    )

    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(content)

    return path


def save_article_if_new(output_dir, species_name, index, title, url, query, article_text, existing_urls=None):
    if existing_urls is None:
        existing_urls = set()

    if url in existing_urls:
        print(f"    已跳过：URL 已存在 -> {url}")
        return None

    path = save_article(output_dir, species_name, index, title, url, query, article_text)
    if path:
        existing_urls.add(url)
    return path


def scrape_news_and_gov(page, species_name, output_dir, max_pages=1, max_results_per_query=3, min_chars=120, queries=None, existing_urls=None):
    saved_records = []
    article_index = 1
    visited_urls = set()
    if existing_urls is None:
        existing_urls = set()

    # 如果传入了已有记录，从中计算下一个序号
    species_dir = os.path.join(output_dir, clean_filename(species_name))
    if os.path.isdir(species_dir):
        existing_files = [f for f in os.listdir(species_dir) if f.lower().endswith('.txt')]
        if existing_files:
            try:
                max_idx = max(int(f.split('_', 1)[0]) for f in existing_files if f.split('_', 1)[0].isdigit())
                article_index = max_idx + 1
            except Exception:
                pass

    if queries is None:
        queries = build_search_queries(species_name)

    for query in queries:
        print(f"\n正在百度搜索：{query}")

        try:
            page.get(f"https://www.baidu.com/s?wd={quote_plus(query)}")
            time.sleep(3)

            for current_page in range(1, max_pages + 1):
                results = page.eles("xpath://h3//a")
                print(f"  第 {current_page} 页找到 {len(results)} 个结果，处理前 {min(len(results), max_results_per_query)} 个")

                for link_ele in results[:max_results_per_query]:
                    detail_page = None
                    try:
                        title = (link_ele.text or "").strip()
                        link = link_ele.attr("href")
                        if not title or not link or link in visited_urls or link in existing_urls:
                            continue
                        visited_urls.add(link)

                        print(f"  打开：{title[:35]}...")
                        detail_page = page.new_tab(link)
                        time.sleep(2)

                        final_url = detail_page.url
                        if final_url.startswith(("chrome://", "devtools://", "edge://")):
                            print(f"    跳过：浏览器内部页 {final_url}")
                            continue

                        article_text = extract_main_text(detail_page)
                        if len(article_text) < min_chars:
                            page_title = getattr(detail_page, "title", "") or ""
                            print(f"    跳过：正文过短 ({len(article_text)} 字)，页面标题：{page_title[:40]}，URL：{final_url}")
                            continue
                        path = save_article_if_new(output_dir, species_name, article_index, title, final_url, query, article_text, existing_urls=existing_urls)
                        if path:
                            saved_records.append({
                            "species": species_name,
                            "title": title,
                            "url": final_url,
                            "query": query,
                            "chars": len(article_text),
                            "path": path,
                        })
                            article_index += 1
                            print(f"    已保存：{path}")

                    except Exception as exc:
                        print(f"    当前结果处理失败：{exc}")
                    finally:
                        if detail_page is not None:
                            try:
                                detail_page.close()
                            except Exception:
                                pass
                        elif len(page.tab_ids) > 1:
                            try:
                                page.get_tab(page.tab_ids[-1]).close()
                            except Exception:
                                pass
                        time.sleep(1)

                if current_page < max_pages:
                    next_btn = page.ele("text=下一页", timeout=2)
                    if not next_btn:
                        break
                    next_href = next_btn.attr("href")
                    if next_href:
                        page.get(next_href)
                    else:
                        next_btn.click()
                    time.sleep(3)

        except Exception as exc:
            print(f"搜索失败：{query} -> {exc}")

    return saved_records


def write_manifest(output_dir, records):
    if not records:
        return None

    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "manifest.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["species", "title", "url", "query", "chars", "path"])
        writer.writeheader()
        writer.writerows(records)
    return path


def parse_args():
    parser = argparse.ArgumentParser(description="抓取新闻/政府网页正文并保存为文本")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="文本保存目录")
    parser.add_argument("--max-pages", type=int, default=1, help="每个搜索词最多翻页数")
    parser.add_argument("--max-results", type=int, default=10, help="每页最多处理多少个搜索结果")
    parser.add_argument("--min-chars", type=int, default=120, help="正文少于该字数时跳过")
    parser.add_argument('--select', action='store_true', help='交互选择要处理的物种')
    return parser.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    print("开始抓取新闻/政府网页正文...")
    page = ChromiumPage(timeout=8)
    page.set.timeouts(base=8, page_load=15, script=8)
    page.set.load_mode.eager()

    all_records = []

    # 交互选择物种（参考爬取百科数据的交互）
    print('🚀 启动选择：')
    selected_species = choose_items(species_names, '可选物种：', allow_all=True)

    # 交互设置运行参数（回车使用默认）
    print('\n运行参数设置（回车使用默认当前值）:')
    mp = input(f"每个搜索词最多翻页数 (当前 {args.max_pages}): ").strip()
    if mp.isdigit() and int(mp) > 0:
        args.max_pages = int(mp)
    mr = input(f"每页最多处理多少个搜索结果 (当前 {args.max_results}): ").strip()
    if mr.isdigit() and int(mr) > 0:
        args.max_results = int(mr)

    for species in selected_species:
        print(f"\n处理物种：{species}")

        # 展示已有文本
        show_existing_texts(args.output_dir, species)

        # 加载已有 URL 用于去重
        existing_urls = load_existing_urls(args.output_dir, species)

        # 交互选择搜索词（可选默认词或自定义）
        default_queries = build_search_queries(species)
        print('\n请选择要使用的搜索词（默认按回车全部）：')
        selected_queries = choose_items(default_queries, '可选搜索词：', allow_all=True)
        custom = input('输入自定义搜索词（逗号分隔），或回车跳过：').strip()
        if custom:
            for q in re.split('[,，]', custom):
                q = q.strip()
                if q and q not in selected_queries:
                    selected_queries.append(q)

        records = scrape_news_and_gov(
            page,
            species,
            args.output_dir,
            max_pages=args.max_pages,
            max_results_per_query=args.max_results,
            min_chars=args.min_chars,
            queries=selected_queries,
            existing_urls=existing_urls,
        )
        all_records.extend(records)
        time.sleep(3)

    manifest_path = write_manifest(args.output_dir, all_records)
    print(f"\n完成，共保存 {len(all_records)} 篇正文。")
    print(f"文本目录：{os.path.abspath(args.output_dir)}")
    if manifest_path:
        print(f"索引文件：{os.path.abspath(manifest_path)}")


if __name__ == "__main__":
    main()

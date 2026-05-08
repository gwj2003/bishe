# -*- coding: utf-8 -*-
import os
import time
import argparse
import re
from DrissionPage import ChromiumPage
from species_config import species_names


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

# 简化版的知网爬虫：仅负责检索并保存原文为 txt 文件，供后续抽取使用

def safe_filename(s):
    return ''.join(c for c in s if c.isalnum() or c in ' _-').strip()[:100]


def extract_result_link(item):
    link = item.attr('href')
    if link:
        return link

    try:
        anchor = item.ele('a', timeout=1)
        if anchor:
            link = anchor.attr('href')
            if link:
                return link
    except Exception:
        pass

    return None


def extract_abstract(detail_page, wait_seconds=10):
    selectors = ['#ChDivSummary', '.abstract-text', '.brief', '.summary', '.dataSummary']
    deadline = time.time() + wait_seconds
    best_text = ''

    def is_truncated(text):
        text = (text or '').strip()
        return text.endswith('...') or text.endswith('……') or text.endswith('…')

    def try_expand():
        expand_selectors = [
            'text=展开',
            'text=显示全部',
            'text=更多',
            '.read-more',
            '.expand',
        ]
        for selector in expand_selectors:
            try:
                btn = detail_page.ele(selector, timeout=1)
            except Exception:
                btn = None
            if btn:
                try:
                    btn.click()
                    time.sleep(1)
                    return True
                except Exception:
                    continue
        return False

    try_expand()

    while time.time() < deadline:
        for selector in selectors:
            try:
                abstract_eles = detail_page.eles(selector, timeout=1)
            except Exception:
                abstract_eles = []

            for abstract_ele in abstract_eles:
                abstract = (abstract_ele.text or '').strip()
                if abstract and len(abstract) > len(best_text):
                    best_text = abstract

        time.sleep(1)

    if best_text:
        if is_truncated(best_text):
            try:
                body_text = (detail_page.ele('body').text or '').strip()
                if len(body_text) > len(best_text):
                    return body_text
            except Exception:
                pass
        return best_text

    try:
        body_text = (detail_page.ele('body').text or '').strip()
        return body_text
    except Exception:
        return ''


def load_existing_urls_cnki(raw_dir):
    urls = set()
    if not os.path.isdir(raw_dir):
        return urls
    for fn in os.listdir(raw_dir):
        if not fn.lower().endswith('.txt'):
            continue
        try:
            with open(os.path.join(raw_dir, fn), 'r', encoding='utf-8') as f:
                for line in f:
                    if line.startswith('URL:'):
                        url = line.split('URL:', 1)[1].strip()
                        if url:
                            urls.add(url)
                        break
        except Exception:
            continue
    return urls


def show_existing_texts_cnki(raw_dir, species_name, preview_chars=200):
    if not os.path.isdir(raw_dir):
        print('    （尚无已保存摘要）')
        return
    files = sorted([f for f in os.listdir(raw_dir) if f.lower().endswith('.txt') and f.startswith(species_name+'_cnki_')])
    if not files:
        print('    （尚无已保存摘要）')
        return
    print(f"    已保存 {len(files)} 篇摘要：")
    for fn in files[:10]:
        path = os.path.join(raw_dir, fn)
        try:
            with open(path, 'r', encoding='utf-8') as f:
                head = f.read(preview_chars).replace('\n',' ')
                print(f"      - {fn} -> {head[:preview_chars]}{'...' if len(head)>=preview_chars else ''}")
        except Exception:
            print(f"      - {fn} -> （读取失败）")


def scrape_cnki_for_term(page, term, species_name, max_pages=1, max_results=10, interactive=False, existing_urls=None):
    """检索知网并把每篇摘要保存为 data/cnki_texts/{species}/{species}_cnki_{title}.txt"""
    search_keyword = f"{term} 分布"
    print(f"\n🔵 检索: {search_keyword}")

    try:
        page.get('https://www.cnki.net/')
        time.sleep(2)
        main_tab_id = page.tab_id

        search_box = page.ele('#txt_SearchText')
        search_box.clear()
        search_box.input(search_keyword)
        page.ele('.search-btn').click()
        time.sleep(4)

        saved = 0
        for current_page in range(1, max_pages + 1):
            print(f"  📄 第 {current_page} 页")
            results = page.eles('.fz14')
            print(f"    🔎 找到 {len(results)} 个候选结果")
            for item in results[:max_results]:
                detail_page = None
                try:
                    title = item.text or 'untitled'
                    link = extract_result_link(item)
                    if not link:
                        print(f"    ⚠️ 跳过无链接结果: {title}")
                        continue
                    if existing_urls and link in existing_urls:
                        print(f"    跳过已存在 URL: {link}")
                        continue
                    detail_page = page.new_tab(link)
                    time.sleep(2)

                    abstract = extract_abstract(detail_page)

                    # 保存原文（按物种子文件夹）
                    if abstract:
                        raw_dir = os.path.join('data', 'cnki_texts', species_name)
                        os.makedirs(raw_dir, exist_ok=True)
                        fname = f"{species_name}_cnki_{safe_filename(title)}.txt"
                        out_path = os.path.join(raw_dir, fname)
                        with open(out_path, 'w', encoding='utf-8') as f:
                            f.write(f"SOURCE_TITLE: {title}\nURL: {link}\n\n")
                            f.write(abstract)
                        if existing_urls is not None:
                            existing_urls.add(link)
                        saved += 1
                        print(f"    ✅ 已保存: {title}")
                    else:
                        print(f"    ⚠️ 未找到摘要: {title}")

                    if detail_page and detail_page.tab_id != main_tab_id:
                        detail_page.close()
                    page.get_tab(main_tab_id)
                    time.sleep(1)
                except Exception as e:
                    print(f"    ❌ 单篇保存失败: {e}")
                    try:
                        if detail_page and detail_page.tab_id in page.tab_ids and detail_page.tab_id != main_tab_id:
                            detail_page.close()
                        if main_tab_id in page.tab_ids:
                            page.get_tab(main_tab_id)
                    except Exception:
                        raise

            # 翻页
            if current_page < max_pages:
                if interactive:
                    ans = input("  是否继续到下一页？(Y/n): ").strip().lower()
                    if ans and ans.startswith('n'):
                        break
                next_btn = page.ele('text=下一页', timeout=2)
                if next_btn:
                    next_btn.click()
                    time.sleep(3)

        print(f"  ✅ 本次检索保存 {saved} 篇摘要到 data/cnki_texts/{species_name}/")
        return saved

    except Exception as e:
        print(f"❌ 检索异常: {e}")
        return 0


def load_alias_map(triplets_dir='data/triplets'):
    import os
    import pandas as pd
    alias_map = {}
    if not os.path.exists(triplets_dir):
        return alias_map
    for fn in os.listdir(triplets_dir):
        if not fn.lower().endswith('.csv'):
            continue
        path = os.path.join(triplets_dir, fn)
        try:
            df = pd.read_csv(path, dtype=str, keep_default_na=False)
        except Exception:
            continue
        if {'Entity1', 'Relationship', 'Entity2'}.issubset(df.columns):
            rows = df[df['Relationship'] == 'HAS_ALIAS']
            for _, r in rows.iterrows():
                e1 = str(r['Entity1']).strip()
                e2 = str(r['Entity2']).strip()
                if not e1 or not e2:
                    continue
                alias_map.setdefault(e1, set()).add(e2)
    return alias_map


def main():
    parser = argparse.ArgumentParser(description='CNKI 爬虫：只保存摘要为 txt')
    parser.add_argument('--mode', choices=['auto','semi'], default='auto')
    parser.add_argument('--max-pages', type=int, default=1)
    parser.add_argument('--max-results', type=int, default=10)
    parser.add_argument('--select', action='store_true', help='保留兼容：已不再需要，仅用于显式强调交互')
    args = parser.parse_args()

    alias_map = load_alias_map()
    page = ChromiumPage()

    # 交互选择物种
    print('🚀 启动选择：')
    selected_species = choose_items(species_names, '可选物种：', allow_all=True)

    # 交互设置运行参数（回车使用默认）
    print('\n运行参数设置（回车使用默认当前值）:')
    mp = input(f"每个搜索词最多翻页数 (当前 {args.max_pages}): ").strip()
    if mp.isdigit() and int(mp) > 0:
        args.max_pages = int(mp)
    mr = input(f"每页最多处理多少个结果 (当前 {args.max_results}): ").strip()
    if mr.isdigit() and int(mr) > 0:
        args.max_results = int(mr)

    for sp in selected_species:
        raw_dir = os.path.join('data', 'cnki_texts', sp)
        # 展示已有文本
        show_existing_texts_cnki(raw_dir, sp)

        # 加载已有 URL 去重
        existing_urls = load_existing_urls_cnki(raw_dir)

        terms = [sp]
        if sp in alias_map:
            terms.extend(sorted(alias_map[sp]))

        # 交互选择要处理的检索词
        terms = choose_items(terms, f"可选检索词（物种 {sp}）：", allow_all=True)
        custom = input('输入自定义检索词（逗号分隔），或回车跳过：').strip()
        if custom:
            for q in re.split('[,，]', custom):
                q = q.strip()
                if q and q not in terms:
                    terms.append(q)

        for t in terms:
            if args.mode == 'semi':
                ans = input(f"是否对检索词 '{t}' 保存摘要？(Y/n): ").strip().lower()
                if ans and ans.startswith('n'):
                    continue
            scrape_cnki_for_term(page, t, sp, max_pages=args.max_pages, max_results=args.max_results, interactive=(args.mode=='semi'), existing_urls=existing_urls)
            time.sleep(3)


if __name__ == '__main__':
    main()

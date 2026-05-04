from DrissionPage import ChromiumPage
import os
import time

# ================= 1. 数据准备 =================
# 定义要爬取的物种，包含百度和维基的链接
# 注意：维基百科在中国大陆可能需要科学上网环境才能访问
tasks = [
    {
        "name": "福寿螺",
        "baidu": "https://baike.baidu.com/item/%E7%A6%8F%E5%AF%BF%E8%9E%BA/4201051?fromModule=disambiguation",
        "wiki": "https://zh.wikipedia.org/wiki/福寿螺"
    },
    {
        "name": "鳄雀鳝",
        "baidu": "https://baike.baidu.com/item/鳄雀鳝",
        "wiki": "https://zh.wikipedia.org/wiki/鳄雀鳝"
    }
]


# ================= 2. 核心逻辑 =================

def save_to_file(folder, filename, content):
    """辅助函数：保存文件，无长度限制"""
    if not content:
        return False

    filepath = os.path.join(folder, filename)
    with open(filepath, "w", encoding='utf-8') as f:
        f.write(content)
    return filepath


def crawl_baidu(page, url):
    """百度百科提取逻辑"""
    print(f"  👉 正在访问百度百科...")
    page.get(url)

    # 策略1: 标准摘要框
    if page.ele('.lemma-summary', timeout=2):
        return page.ele('.lemma-summary').text

    # 策略2: Meta标签 (针对特殊页面)
    elif page.ele('@name=description'):
        return page.ele('@name=description').attr('content')

    return None


def crawl_wiki(page, url):
    """维基百科提取逻辑"""
    print(f"  👉 正在访问维基百科...")
    page.get(url)

    # 维基百科的摘要通常是目录(toc)之前的段落
    # 我们提取 .mw-parser-output 下的前几个 <p> 标签
    summary_content = ""

    # 等待页面加载
    if page.ele('#mw-content-text', timeout=5):
        # 获取所有段落对象
        paragraphs = page.eles('css:.mw-parser-output > p')

        count = 0
        for p in paragraphs:
            text = p.text.strip()
            # 跳过空段落
            if not text:
                continue

            summary_content += text + "\n"
            count += 1
            # 维基摘要通常提取前3-5段就够了，太多会把正文也抓进去
            if count >= 5:
                break

        return summary_content

    return None


# ================= 3. 主程序 =================

def main():
    # 确保保存目录存在
    os.makedirs("../data/encyclopedia", exist_ok=True)

    # 启动浏览器
    page = ChromiumPage()

    print("🚀 开始双源爬取任务...\n")

    for item in tasks:
        name = item['name']
        print(f"🔵 开始处理物种: 【{name}】")

        # --- 1. 爬取百度百科 ---
        try:
            baidu_text = crawl_baidu(page, item['baidu'])
            if baidu_text:
                path = save_to_file("data/encyclopedia", f"{name}_baidu.txt", baidu_text)
                print(f"    ✅ 百度数据已保存 (字数: {len(baidu_text)})")
            else:
                print(f"    ❌ 百度数据提取失败")
        except Exception as e:
            print(f"    ❌ 百度爬取报错: {e}")

        # --- 2. 爬取维基百科 ---
        try:
            wiki_text = crawl_wiki(page, item['wiki'])
            if wiki_text:
                path = save_to_file("data/encyclopedia", f"{name}_wiki.txt", wiki_text)
                print(f"    ✅ 维基数据已保存 (字数: {len(wiki_text)})")
            else:
                print(f"    ⚠️ 维基数据提取失败 (可能连接超时或页面不存在)")
        except Exception as e:
            print(f"    ⚠️ 维基爬取跳过 (网络或元素未找到): {e}")

        print("-" * 40)
        time.sleep(2)  # 稍微休息

    print("\n🏁 所有任务结束。")


if __name__ == "__main__":
    main()
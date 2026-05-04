from DrissionPage import ChromiumPage
import os
import time
import re

# ================= 1. 目标动物清单 (数据结构升级) =================
# 格式: {"name": 中文名, "latin": 学名, "baidu_url": (选填)特定链接}
# 如果 baidu_url 为 None，代码会自动拼凑 /item/中文名
species_list = [
    {
        "name": "非洲大蜗牛",
        "latin": "Achatina fulica",
        "baidu_url": None
    },
    {
        "name": "福寿螺",
        "latin": "Pomacea canaliculata",
        # 👇 关键修改：手动指定带有 ID 的链接，直达动物详情页，跳过多义词选择
        "baidu_url": "https://baike.baidu.com/item/福寿螺/4201051"
    },
    {
        "name": "鳄雀鳝",
        "latin": "Atractosteus spatula",
        "baidu_url": None
    },
    {
        "name": "豹纹翼甲鲶",
        "latin": "Pterygoplichthys pardalis",
        "baidu_url": None
    },
    {
        "name": "齐氏罗非鱼",
        "latin": "Coptodon zillii",
        "baidu_url": None
    },
    {
        "name": "美洲牛蛙",
        "latin": "American bullfrog",
        "baidu_url": None
    },
    {
        "name": "大鳄龟",
        "latin": "Macrochelys temminckii",
        "baidu_url": None
    },
    {
        "name": "红耳彩龟",
        "latin": "Trachemys scripta elegans",
        "baidu_url": None
    },
]


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


# ================= 3. 核心爬取逻辑 =================

def get_baidu(page, item_data):
    """百度百科爬取 - 支持自定义URL"""
    name = item_data["name"]
    # 如果指定了 url 就用指定的，否则自动拼接
    url = item_data.get("baidu_url") or f"https://baike.baidu.com/item/{name}"

    print(f"  👉 [百度] {url}")

    try:
        page.get(url)
        time.sleep(1.5)

        # 调试信息：打印当前标题，看看是不是跳到了验证码或消歧页
        print(f"    (当前页面标题: {page.title})")

        if "安全验证" in page.title:
            print("    ⚠️ 触发验证码！请手动处理！")
            time.sleep(10)

        raw_text = ""
        # 策略A: 新版
        if page.ele('.main-content'):
            raw_text = page.ele('.main-content').text
        # 策略B: 旧版
        elif page.ele('.lemma-main-content'):
            raw_text = page.ele('.lemma-main-content').text
        # 策略C: J-content (你上次命中的就是这个)
        elif page.ele('.J-lemma-content'):
            raw_text = page.ele('.J-lemma-content').text
        # 策略D: 保底
        else:
            raw_text = page.ele('body').text

        return clean_text(raw_text)

    except Exception as e:
        print(f"    ❌ 百度出错: {e}")
        return None


def get_zh_wiki(page, name):
    url = f"https://zh.wikipedia.org/wiki/{name}"
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
    page = ChromiumPage()
    print(f"🚀 开始任务，共 {len(species_list)} 个物种...\n")

    save_dir = "data/animals"

    for item in species_list:
        cn_name = item["name"]
        print(f"🔵 正在处理: 【{cn_name}】")

        # 1. 百度
        content = get_baidu(page, item)
        save_to_file(save_dir, f"{cn_name}_baidu.txt", content)

        # 2. 中维
        content = get_zh_wiki(page, cn_name)
        save_to_file(save_dir, f"{cn_name}_zh_wiki.txt", content)

        # 3. 英维
        content = get_en_wiki(page, item["latin"])
        save_to_file(save_dir, f"{cn_name}_en_wiki.txt", content)

        print("-" * 40)
        time.sleep(2)

    print(f"\n🏁 全部完成！请查看 {save_dir} 文件夹。")


if __name__ == "__main__":
    main()
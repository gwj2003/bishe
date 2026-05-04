from DrissionPage import ChromiumPage
import os
import time
import re

# ================= 1. 目标动物清单 =================
species_list = [
    ("非洲大蜗牛", "Achatina fulica"),
    ("福寿螺", "Pomacea canaliculata"),
    ("鳄雀鳝", "Atractosteus spatula"),
    ("豹纹翼甲鲶", "Pterygoplichthys pardalis"),
    ("齐氏罗非鱼", "Coptodon zillii"),
    ("美洲牛蛙", "American bullfrog"),
    ("大鳄龟", "Macrochelys temminckii"),
    ("红耳彩龟", "Trachemys scripta elegans"),
]


# ================= 2. 数据清洗工具 =================
def clean_text(raw_text):
    if not raw_text: return ""
    text = re.sub(r'\[.*?\]', '', raw_text)  # 去角标
    text = re.sub(r'\u3000', ' ', text).replace('\xa0', ' ')
    text = re.sub(r'\n{2,}', '\n', text)  # 去空行
    text = text.replace("编辑", "").replace("锁定", "")
    return text.strip()


def save_to_file(folder, filename, content):
    # 降低保存门槛，只要有内容就存，方便调试
    if not content or len(content) < 10:
        print(f"    ❌ 内容过短或为空，未保存: {filename}")
        return False

    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    with open(filepath, "w", encoding='utf-8') as f:
        f.write(content)
    print(f"    💾 已保存: {filename} (字数: {len(content)})")
    return True


# ================= 3. 核心修复逻辑 =================

def get_baidu(page, name):
    """百度百科爬取 - 增强兼容版"""
    url = f"https://baike.baidu.com/item/{name}"
    print(f"  👉 [百度] {url}")

    try:
        page.get(url)
        time.sleep(1.5)  # 给它一点时间渲染

        # 1. 检查是不是遇到了安全验证
        if "安全验证" in page.title or "验证" in page.title:
            print("    ⚠️ 触发了百度验证码，请手动在浏览器中完成验证！")
            time.sleep(10)  # 给你10秒时间手动滑块

        # 2. 依次尝试不同的正文容器 (这是解决保存失败的关键)
        raw_text = ""

        # 策略A: 新版百科容器
        if page.ele('.main-content'):
            print("    (命中: 新版结构)")
            raw_text = page.ele('.main-content').text

        # 策略B: 旧版百科容器
        elif page.ele('.lemma-main-content'):
            print("    (命中: 旧版结构)")
            raw_text = page.ele('.lemma-main-content').text

        # 策略C: 很多多义词页面的结构
        elif page.ele('.J-lemma-content'):
            print("    (命中: J-content结构)")
            raw_text = page.ele('.J-lemma-content').text

        # 策略D: 终极保底 - 只要是 body 里的字都抓下来
        else:
            print("    (命中: 保底模式-全页抓取)")
            raw_text = page.ele('body').text

        # 3. 清洗并返回
        return clean_text(raw_text)

    except Exception as e:
        print(f"    ❌ 百度出错: {e}")
        return None


def get_zh_wiki(page, name):
    url = f"https://zh.wikipedia.org/wiki/{name}"
    print(f"  👉 [中维] {url}")
    try:
        page.get(url)
        # 维基比较标准，一般不会变
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

    save_dir = "../data/animals"

    for cn_name, latin_name in species_list:
        print(f"🔵 正在处理: 【{cn_name}】")

        # 1. 百度 (重点修复)
        content = get_baidu(page, cn_name)
        save_to_file(save_dir, f"{cn_name}_baidu.txt", content)

        # 2. 中维
        content = get_zh_wiki(page, cn_name)
        save_to_file(save_dir, f"{cn_name}_zh_wiki.txt", content)

        # 3. 英维
        content = get_en_wiki(page, latin_name)
        save_to_file(save_dir, f"{cn_name}_en_wiki.txt", content)

        print("-" * 40)
        time.sleep(2)

    print(f"\n🏁 全部完成！请查看 {save_dir} 文件夹。")


if __name__ == "__main__":
    main()
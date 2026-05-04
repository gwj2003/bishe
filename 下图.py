import os
import requests
from bs4 import BeautifulSoup
import time

# 1. 配置物种列表
TARGET_SPECIES = ["非洲大蜗牛", "福寿螺", "鳄雀鳝", "豹纹翼甲鲶", "齐氏罗非鱼", "美洲牛蛙", "大鳄龟", "红耳彩龟"]


def download_species_images(species_list, save_dir="data/images"):
    # 创建保存目录
    if not os.path.exists(save_dir):
        os.makedirs(save_dir)
        print(f"📁 已创建目录: {save_dir}")

    # 模拟浏览器请求头，防止被拦截
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    for name in species_list:
        print(f"🔎 正在搜索并下载: {name}...")
        try:
            # 使用必应图片搜索
            search_url = f"https://www.bing.com/images/search?q={name}&form=HDRSC2"
            response = requests.get(search_url, headers=headers, timeout=10)
            soup = BeautifulSoup(response.text, "html.parser")

            # 提取图片链接 (必应的图片地址通常在 mimg 类的 src 中)
            img_tag = soup.find("img", class_="mimg")

            if img_tag:
                img_url = img_tag.get("src") or img_tag.get("data-src")

                # 如果是 base64 数据则跳过，寻找真实 url
                if not img_url or img_url.startswith('data:image'):
                    # 尝试寻找更原始的链接
                    img_tag = soup.find_all("img", class_="mimg")[1]  # 找第二张
                    img_url = img_tag.get("src") or img_tag.get("data-src")

                # 下载图片
                img_response = requests.get(img_url, headers=headers, timeout=10)
                file_path = os.path.join(save_dir, f"{name}.jpg")

                # --- 修正点：去掉多余的 f. ---
                with open(file_path, "wb") as f:
                    f.write(img_response.content)
                print(f"  ✅ 已成功保存: {file_path}")
            else:
                print(f"  ⚠️ 未找到 {name} 的有效预览图")

            # 适当等待，防止被封
            time.sleep(1.2)

        except Exception as e:
            print(f"  ❌ 下载 {name} 失败: {e}")


if __name__ == "__main__":
    download_species_images(TARGET_SPECIES)
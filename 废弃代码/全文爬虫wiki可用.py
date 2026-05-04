from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager  # 👈 关键库
import time
import os

# ================= 1. 数据准备 =================
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


def save_text(folder, filename, text):
    if not text or len(text) < 10: return False
    path = os.path.join(folder, filename)
    with open(path, "w", encoding='utf-8') as f:
        f.write(text)
    return True


def main():
    os.makedirs("../data/encyclopedia", exist_ok=True)

    # === 浏览器配置 ===
    chrome_options = Options()
    # 防止被检测 (去头与去指纹)
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    # chrome_options.add_argument("--headless") # 调试时不要开启无头模式，让我们看到浏览器

    print("🚀 正在自动匹配驱动并启动浏览器...")

    try:
        # 🌟🌟🌟 核心修改：使用 ChromeDriverManager 自动安装驱动 🌟🌟🌟
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)

        # 设置页面加载超时 (防止维基百科卡死)
        driver.set_page_load_timeout(20)

    except Exception as e:
        print(f"❌ 浏览器启动严重失败: {e}")
        print("💡 建议：请确保您电脑上安装了 Google Chrome 浏览器。")
        return

    try:
        for item in tasks:
            name = item['name']
            print(f"\n🔵 正在处理: 【{name}】")

            # --- 1. 爬取百度百科 ---
            print(f"  👉 访问百度百科...")
            try:
                driver.get(item['baidu'])
                time.sleep(2)  # 等待加载

                full_text = ""

                # 尝试抓取正文主体
                try:
                    # 百度百科正文容器通常是 .main-content
                    # 我们先抓标题，再抓正文
                    title = driver.find_element(By.TAG_NAME, "h1").text
                    full_text += f"【{title}】\n"

                    content = driver.find_element(By.CLASS_NAME, "main-content").text
                    full_text += content
                except:
                    # 备用：抓整个 body
                    full_text += driver.find_element(By.TAG_NAME, "body").text

                if save_text("data/encyclopedia", f"{name}_baidu.txt", full_text):
                    print(f"    ✅ 百度全文保存成功 (约 {len(full_text)} 字)")
                else:
                    print(f"    ❌ 提取内容过短")

            except Exception as e:
                print(f"    ❌ 百度失败: {e}")

            # --- 2. 爬取维基百科 ---
            print(f"  👉 访问维基百科...")
            try:
                driver.get(item['wiki'])
                time.sleep(2)

                # 维基百科的内容容器
                content = driver.find_element(By.ID, "content").text

                if save_text("data/encyclopedia", f"{name}_wiki.txt", content):
                    print(f"    ✅ 维基全文保存成功 (约 {len(content)} 字)")

            except Exception as e:
                # 维基百科在国内连不上是正常的，捕捉异常不报错
                print(f"    ⚠️ 维基访问跳过 (网络原因): {str(e)[:50]}")

    except Exception as e:
        print(f"❌ 运行时发生错误: {e}")

    finally:
        # 任务结束，关闭浏览器
        print("\n🏁 任务结束，正在关闭浏览器...")
        if 'driver' in locals():
            driver.quit()
        input("按回车键退出程序...")  # 保持窗口打开让你看结果


if __name__ == "__main__":
    main()
"""
企业微信消息发送模块
点击左上角搜索框 → 输入用户名 → 搜索 → 发送消息
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import uiautomation as auto
except ImportError:
    print(json.dumps({
        "success": False, "stage": "init",
        "error": "uiautomation 模块未安装"
    }))
    sys.exit(1)

# ============================================================
# 配置
# ============================================================
WECOM_PATHS = [
    r"D:\Software\WXWork\WXWork.exe",
    r"C:\Program Files (x86)\WXWork\WXWork.exe",
    r"C:\Program Files\WXWork\WXWork.exe",
]
WECOM_CLASS_NAME = "WeWorkWindow"
SCREENSHOT_DIR = Path(__file__).parent / "screenshots"

T = 0.3
TM = 0.8
TL = 1.5


# ============================================================
# 截图
# ============================================================
def screenshot(tag=""):
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    fp = SCREENSHOT_DIR / f"wecom_{tag}_{datetime.now().strftime('%H%M%S')}.png"
    try:
        from PIL import ImageGrab
        ImageGrab.grab().save(str(fp))
        return str(fp)
    except:
        return ""


# ============================================================
# 核心：点击搜索框+键盘输入
# ============================================================
def send_to_user(username: str, message: str) -> dict:
    steps = []
    imgs = []
    result = {"success": False, "stage": "init", "steps": steps, "screenshots": imgs}

    def add_step(name, status, detail=""):
        steps.append({"name": name, "status": status, "detail": detail})

    # ---- 1. 激活窗口 ----
    add_step("activate", "running", "激活企业微信...")
    w = auto.WindowControl(searchDepth=1, ClassName=WECOM_CLASS_NAME)
    if not w.Exists(maxSearchSeconds=1):
        launched = False
        for p in WECOM_PATHS:
            if os.path.exists(p):
                subprocess.Popen([p], shell=True)
                launched = True
                break
        if not launched:
            add_step("activate", "failed", "未找到企业微信")
            result["error"] = "企业微信未安装"
            return result
        deadline = time.time() + 15
        while time.time() < deadline:
            w = auto.WindowControl(searchDepth=1, ClassName=WECOM_CLASS_NAME)
            if w.Exists(maxSearchSeconds=1):
                break
            time.sleep(0.5)

    w.SetActive()
    w.SetTopmost(True)
    time.sleep(TM)
    try:
        r = w.BoundingRectangle
        auto.Click(r.left + 50, r.top + 10)  # 点击标题栏获取焦点
        time.sleep(T)
    except:
        pass
    add_step("activate", "success", "企业微信已激活")
    time.sleep(TL)

    # ---- 2. 点击搜索框 ----
    # 搜索框在窗口左上角，标题栏下方、左侧栏顶部
    add_step("click_search", "running", "点击搜索框...")
    try:
        r = w.BoundingRectangle
        # 左侧栏约 280px 宽，搜索框在顶部居中
        search_x = r.left + 140   # 左侧栏中间
        search_y = r.top + 75     # 标题栏(56px) + 留白
        auto.Click(search_x, search_y)
        time.sleep(TM)
    except Exception as e:
        add_step("click_search", "failed", f"点击搜索框失败: {e}")
        result["error"] = f"无法点击搜索框: {e}"
        result["stage"] = "click_search"
        return result
    add_step("click_search", "success", "已点击搜索框")

    # ---- 3. 输入用户名 ----
    add_step("type_username", "running", f"输入用户名: {username}")
    auto.SendKeys(username, waitTime=0)
    time.sleep(TL)

    # ---- 4. 等待搜索，选择结果 ----
    add_step("select_result", "running", "选择搜索结果...")
    auto.SendKeys("{Down}", waitTime=0)
    time.sleep(T)
    auto.SendKeys("{Enter}", waitTime=0)
    time.sleep(TL)

    img = screenshot("chat_opened")
    if img:
        imgs.append(img)
    add_step("select_result", "success", f"已打开 {username} 的聊天")

    # ---- 5. 发送消息 ----
    add_step("send", "running", f"发送: {message}")
    time.sleep(TL)
    auto.SendKeys(message, waitTime=0)
    time.sleep(T)
    auto.SendKeys("{Enter}", waitTime=0)
    time.sleep(TM)

    img = screenshot("sent")
    if img:
        imgs.append(img)
    add_step("send", "success", f"消息已发送: {message}")

    result["success"] = True
    result["stage"] = "completed"
    result["username"] = username
    result["message"] = message
    return result


# ============================================================
# CLI
# ============================================================
def main():
    p = argparse.ArgumentParser(description="企业微信消息发送")
    p.add_argument("--username", required=True)
    p.add_argument("--message", required=True)
    args = p.parse_args()

    r = send_to_user(args.username, args.message)
    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    if not r.get("success"):
        sys.exit(1)


if __name__ == "__main__":
    main()

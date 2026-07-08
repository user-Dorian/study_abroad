"""
企业微信搜索框位置智能探查
在窗口左上角区域逐点测试点击位置，
通过 Ctrl+A → Ctrl+C 读取剪贴板，判断是否击中了搜索输入框
"""
import uiautomation as auto
import time
import pyperclip  # 用于读取剪贴板

# 先确保 pyperclip 可用
try:
    import pyperclip
except ImportError:
    import subprocess
    subprocess.check_call(
        "D:\miniconda3\envs\rag_env\python.exe -m pip install pyperclip -q",
        shell=True
    )
    import pyperclip

# 激活窗口
w = auto.WindowControl(searchDepth=1, ClassName="WeWorkWindow")
if not w.Exists(maxSearchSeconds=3):
    print("企业微信未运行")
    exit(1)

w.SetActive()
w.SetTopmost(True)
time.sleep(1)

r = w.BoundingRectangle
print(f"窗口: left={r.left}, top={r.top}, right={r.right}, bottom={r.bottom}")
print(f"尺寸: {r.right-r.left} x {r.bottom-r.top}")
print()

# 测试参数：在窗口左上角按网格扫描
# 标题栏约 56px，搜索框约在其下方 0-50px 范围内
# 左侧栏约 280px 宽
start_x = r.left + 20     # 距左边界
end_x = r.left + 270      # 左侧栏右边界
start_y = r.top + 30      # 从标题栏中间开始
end_y = r.top + 120       # 到标题栏下方较远处

step_x = 40   # 水平步长
step_y = 15   # 垂直步长

print("开始逐点测试...")
print(f"范围: X=[{start_x},{end_x}] Y=[{start_y},{end_y}]")
print(f"步长: X={step_x}, Y={step_y}")
print()

hit_positions = []
marker_id = 0

for y in range(start_y, end_y + 1, step_y):
    for x in range(start_x, end_x + 1, step_x):
        marker_id += 1
        marker = f"MARKER_{marker_id}"

        # 点击
        auto.Click(x, y)
        time.sleep(0.2)

        # 输入标记文字
        auto.SendKeys(marker, waitTime=0)
        time.sleep(0.2)

        # Ctrl+A 全选 + Ctrl+C 复制
        auto.SendKeys("{Ctrl}a", waitTime=0)
        time.sleep(0.1)
        auto.SendKeys("{Ctrl}c", waitTime=0)
        time.sleep(0.3)

        # 读取剪贴板
        try:
            clip = pyperclip.paste()
        except:
            clip = ""

        # 如果是搜索框，剪贴板里应该有 MARKER
        if marker in clip:
            hit_positions.append((x, y, marker))
            print(f"  ✅ 命中! ({x}, {y})  剪贴板内容: {clip[:30]}")

            # Esc 清空搜索框
            auto.SendKeys("{Escape}", waitTime=0)
            time.sleep(0.2)
        else:
            # 没命中，需要清除输入的内容
            auto.SendKeys("{Escape}", waitTime=0)
            time.sleep(0.1)
            auto.SendKeys("{Escape}", waitTime=0)
            time.sleep(0.1)

# 汇报结果
print(f"\n{'='*50}")
print(f"探查完成! 共测试 {marker_id} 个位置")
if hit_positions:
    print(f"命中 {len(hit_positions)} 个位置:")
    for x, y, m in hit_positions:
        # 计算相对于窗口的偏移
        dx = x - r.left
        dy = y - r.top
        print(f"  ({x}, {y})  →  窗口内偏移: ({dx}, {dy})")
else:
    print("❌ 没有位置命中搜索框!")
    print("可能原因: 1)坐标范围不对 2)企业微信登录页/其他页面遮挡")

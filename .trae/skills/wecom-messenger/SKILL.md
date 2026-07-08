---
name: "wecom-messenger"
description: "Sends messages via WeCom (企业微信/WeWork) using Windows UI automation. Invoke when user asks to send WeCom messages, notify users, or automate Enterprise WeChat operations on Windows."
---

# WeCom Messenger (企业微信消息发送)

点击企业微信左上角搜索框 → 输入用户名 → 发送消息

---

## 使用

```bash
python wecom_messenger.py --username "用户名" --message "消息内容"
```

参数:
- `--username` — 企业微信中的用户名（必填）
- `--message` — 消息内容（必填）

---

## 执行流程

```
1. 激活企业微信窗口
2. 点击左上角搜索框（坐标定位）
3. 输入用户名
4. Down + Enter 选择第一个搜索结果
5. 输入消息 + Enter 发送
6. 截图留证
```

---

## 返回结果

```json
{
  "success": true,
  "stage": "completed",
  "username": "张三",
  "message": "你好",
  "screenshots": ["screenshots/wecom_chat_opened.png", "screenshots/wecom_sent.png"],
  "steps": [
    {"name": "activate",       "status": "success", "detail": "企业微信已激活"},
    {"name": "click_search",   "status": "success", "detail": "已点击搜索框"},
    {"name": "type_username",  "status": "running", "detail": "输入用户名"},
    {"name": "select_result",  "status": "success", "detail": "已打开聊天"},
    {"name": "send",           "status": "success", "detail": "消息已发送"}
  ]
}
```

"""
回复监控 + 对话列表解析。

- 扫描 IM 页面左侧对话列表
- 提取卖家昵称、最新回复、回复时间
- 支持进入单个对话获取完整聊天记录
"""

import time
import json
from typing import List, Optional

from .browser import BrowserManager, XIANYU_HOME_URL, _log
from .auth import ensure_logged_in


def get_conversations(bm: BrowserManager) -> dict:
    """
    扫描 IM 对话列表，返回所有对话的最新状态。

    Returns:
        dict: {success, conversations: [{sellerNick, lastMessage, timeAgo, unread}], message}
    """
    login_result = ensure_logged_in(bm)
    if not login_result["success"]:
        return {"success": False, "conversations": [], "message": login_result["message"]}

    page = bm.get_page()

    # 导航到 IM 页面
    im_url = f"{XIANYU_HOME_URL}/im"
    _log(f"导航到 IM 页面获取对话列表: {im_url}")
    page.goto(im_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)

    # 从左侧对话列表提取信息
    conversations = page.evaluate("""() => {
        const convs = [];
        // 对话列表项通常在 aside/complementary 区域
        const sidebar = document.querySelector('aside') ||
                        document.querySelector('[role="complementary"]') ||
                        document.querySelector('[class*="conversation-list"]') ||
                        document.querySelector('[class*="chat-list"]');

        if (!sidebar) {
            // fallback: 直接找所有对话项
            const items = document.querySelectorAll('[class*="conversation-item"], [class*="chat-item"], [class*="session-item"]');
            for (const item of items) {
                const text = item.innerText || '';
                convs.push({ raw: text.substring(0, 200) });
            }
            return convs;
        }

        // 获取 sidebar 的全文，用正则解析
        const fullText = sidebar.innerText || '';
        return [{ sidebarText: fullText.substring(0, 5000) }];
    }""")

    # 如果 evaluate 返回的是 sidebar 原文，用 Python 解析
    if conversations and "sidebarText" in conversations[0]:
        raw_text = conversations[0]["sidebarText"]
        parsed = _parse_sidebar_text(raw_text)
        return {
            "success": True,
            "conversations": parsed,
            "message": f"获取到 {len(parsed)} 条对话",
        }

    # 如果 evaluate 返回了结构化数据
    return {
        "success": True,
        "conversations": conversations,
        "message": f"获取到 {len(conversations)} 条对话",
    }


def _parse_sidebar_text(text: str) -> List[dict]:
    """
    解析 IM 页面左侧对话列表的原始文本。

    闲鱼 IM 对话列表的文本模式通常是：
    [卖家昵称] [最新回复内容] [时间]
    每个对话之间有一定的分隔。
    """
    conversations = []

    # 尝试按行分割，识别对话模式
    lines = [l.strip() for l in text.split('\n') if l.strip()]

    # 时间标记模式（如 "5分钟前", "7小时前", "昨天", "刚刚" 等）
    time_patterns = [
        r'\d+分钟前', r'\d+小时前', r'\d+天前',
        r'刚刚', r'昨天', r'前天',
        r'\d{1,2}:\d{2}',  # HH:MM
        r'\d{1,2}月\d{1,2}日',
    ]

    import re
    time_regex = re.compile('|'.join(time_patterns))

    i = 0
    current_nick = None
    current_msg = None
    current_time = None

    while i < len(lines):
        line = lines[i]

        # 检查是否包含时间标记
        time_match = time_regex.search(line)
        if time_match:
            current_time = time_match.group()
            # 时间之前的内容可能是消息
            msg_part = line[:time_match.start()].strip()
            if msg_part:
                current_msg = msg_part

            # 如果有累积的 nick + msg，输出一个对话
            if current_nick:
                conversations.append({
                    "sellerNick": current_nick,
                    "lastMessage": current_msg or "",
                    "timeAgo": current_time or "",
                    "unread": False,
                })
                current_nick = None
                current_msg = None
                current_time = None
        else:
            # 非时间行：可能是昵称或消息
            if not current_nick:
                current_nick = line
            elif not current_msg:
                current_msg = line

        i += 1

    # 处理最后一条
    if current_nick:
        conversations.append({
            "sellerNick": current_nick,
            "lastMessage": current_msg or "",
            "timeAgo": current_time or "",
            "unread": False,
        })

    _log(f"解析出 {len(conversations)} 条对话")
    return conversations


def get_conversation_detail(
    bm: BrowserManager,
    item_id: str,
    seller_id: str,
) -> dict:
    """
    获取单个对话的完整聊天记录。

    Args:
        bm: BrowserManager 实例
        item_id: 商品 ID
        seller_id: 卖家 ID

    Returns:
        dict: {success, messages: [{sender, content, time}], sellerNick, itemId, message}
    """
    login_result = ensure_logged_in(bm)
    if not login_result["success"]:
        return {"success": False, "messages": [], "message": login_result["message"]}

    page = bm.get_page()
    im_url = f"{XIANYU_HOME_URL}/im?itemId={item_id}&peerUserId={seller_id}"

    _log(f"获取对话详情: item={item_id}, seller={seller_id}")
    page.goto(im_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)

    # 提取聊天消息
    messages = page.evaluate("""() => {
        const msgs = [];
        // 消息容器通常在 main 区域
        const msgElements = document.querySelectorAll(
            '[class*="message-item"], [class*="chat-message"], [class*="msg-bubble"], [class*="message"]'
        );
        for (const el of msgElements) {
            const text = el.innerText || '';
            if (!text.trim()) continue;

            // 判断方向：通常自己发的在右边，对方发的在左边
            const isMine = el.classList.toString().includes('self') ||
                           el.classList.toString().includes('mine') ||
                           el.classList.toString().includes('right') ||
                           el.closest('[class*="right"]') !== null;

            msgs.push({
                sender: isMine ? 'me' : 'seller',
                content: text.substring(0, 500),
            });
        }
        return msgs;
    }""")

    # 尝试获取卖家昵称
    seller_nick = None
    try:
        nick_el = page.locator('[class*="nick"], [class*="name"], h2, h3').first
        if nick_el.is_visible(timeout=2000):
            seller_nick = nick_el.inner_text().strip()
    except Exception:
        pass

    return {
        "success": True,
        "messages": messages,
        "sellerNick": seller_nick,
        "itemId": item_id,
        "message": f"获取到 {len(messages)} 条消息",
    }

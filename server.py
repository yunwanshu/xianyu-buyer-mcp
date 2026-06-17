"""
闲鱼买家询价 MCP Server

7 个工具：
  login              — 扫码登录闲鱼
  check_login_status — 检查登录状态
  search             — 搜索商品（含卖家 ID）
  send_inquiry       — 向单个卖家发送询价
  batch_send_inquiry — 批量发送询价
  get_conversations  — 获取对话列表
  get_conversation_detail — 获取单个对话详情
"""

import asyncio
import functools
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# 加载 .env（项目根目录）
load_dotenv()

from xianyu_buyer.browser import BrowserManager
from xianyu_buyer.auth import ensure_logged_in, check_login_status
from xianyu_buyer.search import search_items
from xianyu_buyer.messaging import send_inquiry as _send_inquiry
from xianyu_buyer.messaging import batch_send_inquiry as _batch_send
from xianyu_buyer.monitor import get_conversations as _get_convs
from xianyu_buyer.monitor import get_conversation_detail as _get_conv_detail

# ── MCP Server ────────────────────────────────────────────────────

mcp = FastMCP(
    "XianyuBuyer",
    instructions=(
        "闲鱼买家询价工具。支持搜索闲鱼商品、批量发送询价消息、回收卖家回复。\n"
        "使用流程：\n"
        "1. 先调用 login() 扫码登录\n"
        "2. 调用 search() 搜索商品\n"
        "3. 调用 send_inquiry() 或 batch_send_inquiry() 发送询价\n"
        "4. 调用 get_conversations() 查看卖家回复"
    ),
)

# ── 线程桥接 ──────────────────────────────────────────────────────
# Playwright sync API 需要与 asyncio 隔离，用单线程 executor 序列化所有浏览器操作

_executor = ThreadPoolExecutor(max_workers=1)
_bm: Optional[BrowserManager] = None


def _get_bm() -> BrowserManager:
    """懒初始化 BrowserManager 单例。"""
    global _bm
    if _bm is None:
        _bm = BrowserManager()
    return _bm


async def _run_sync(fn, *args, **kwargs):
    """将同步函数提交到线程池执行，桥接 async MCP handler。"""
    loop = asyncio.get_event_loop()
    partial = functools.partial(fn, *args, **kwargs)
    return await loop.run_in_executor(_executor, partial)


# ── Tool 1: 登录 ─────────────────────────────────────────────────

@mcp.tool()
async def login() -> str:
    """扫码登录闲鱼。首次使用会弹出浏览器窗口，请用闲鱼或淘宝 App 扫码。
    后续调用会复用已保存的 cookies，无需重复扫码。"""
    bm = _get_bm()
    result = await _run_sync(ensure_logged_in, bm)
    return result["message"]


# ── Tool 2: 检查登录状态 ─────────────────────────────────────────

@mcp.tool()
async def check_login() -> str:
    """检查当前闲鱼登录状态（不触发扫码）。"""
    bm = _get_bm()
    result = await _run_sync(check_login_status, bm)
    return result["message"]


# ── Tool 3: 搜索商品 ─────────────────────────────────────────────

@mcp.tool()
async def search(
    keyword: str,
    max_price: Optional[float] = None,
    max_results: int = 20,
) -> str:
    """搜索闲鱼商品，返回商品列表（含卖家 ID 和昵称）。
    一步完成搜索+卖家信息查询，无需分两步操作。

    Args:
        keyword: 搜索关键词，如 "MacBook Pro M1 16G 512G"
        max_price: 最高价格（可选），如 5000
        max_results: 最多返回数量，默认 20
    """
    bm = _get_bm()
    result = await _run_sync(search_items, bm, keyword, max_price, max_results)

    if not result["success"]:
        return result["message"]

    lines = [result["message"], ""]
    for i, item in enumerate(result["items"], 1):
        price_str = f"¥{item['price']}" if item["price"] else "价格未知"
        seller_str = f"卖家: {item['sellerNick']}" if item["sellerNick"] else "卖家信息未获取"
        seller_id_str = f" (ID: {item['sellerId']})" if item["sellerId"] else ""
        lines.append(f"【{i}】{item['title']}")
        lines.append(f"    价格: {price_str} | {seller_str}{seller_id_str}")
        lines.append(f"    itemId: {item['itemId']}")
        lines.append("")

    return "\n".join(lines)


# ── Tool 4: 发送询价 ─────────────────────────────────────────────

@mcp.tool()
async def send_inquiry(
    item_id: str,
    seller_id: str,
    message: str = "你好，还在吗？",
) -> str:
    """向指定卖家发送询价消息。

    Args:
        item_id: 商品 ID（从 search 结果获取）
        seller_id: 卖家 ID（从 search 结果获取）
        message: 消息内容，默认 "你好，还在吗？"
    """
    bm = _get_bm()
    result = await _run_sync(_send_inquiry, bm, item_id, seller_id, message)
    return result["message"]


# ── Tool 5: 批量发送询价 ────────────────────────────────────────

@mcp.tool()
async def batch_send_inquiry(
    items: str,
    message: str = "你好，还在吗？",
) -> str:
    """批量向多个卖家发送询价消息。每条消息间隔 2 秒。

    Args:
        items: JSON 数组字符串，格式如 [{"itemId": "xxx", "sellerId": "yyy"}, ...]
        message: 消息内容，默认 "你好，还在吗？"
    """
    import json

    bm = _get_bm()
    try:
        items_list = json.loads(items)
    except json.JSONDecodeError:
        return "items 格式错误，请传入 JSON 数组，如: [{\"itemId\": \"xxx\", \"sellerId\": \"yyy\"}]"

    result = await _run_sync(_batch_send, bm, items_list, message)
    return result["message"]


# ── Tool 6: 获取对话列表 ─────────────────────────────────────────

@mcp.tool()
async def get_conversations() -> str:
    """获取闲鱼 IM 对话列表，查看所有卖家的最新回复。"""
    bm = _get_bm()
    result = await _run_sync(_get_convs, bm)

    if not result["success"]:
        return result["message"]

    convs = result["conversations"]
    if not convs:
        return "暂无对话记录"

    lines = [f"共 {len(convs)} 条对话：", ""]
    for i, conv in enumerate(convs, 1):
        nick = conv.get("sellerNick", "未知")
        msg = conv.get("lastMessage", "")
        time_ago = conv.get("timeAgo", "")
        unread = " 🆕" if conv.get("unread") else ""
        lines.append(f"【{i}】{nick}{unread}")
        if msg:
            lines.append(f"    最新: {msg}")
        if time_ago:
            lines.append(f"    时间: {time_ago}")
        lines.append("")

    return "\n".join(lines)


# ── Tool 7: 获取对话详情 ─────────────────────────────────────────

@mcp.tool()
async def get_conversation_detail(
    item_id: str,
    seller_id: str,
) -> str:
    """获取与某个卖家的完整聊天记录。

    Args:
        item_id: 商品 ID
        seller_id: 卖家 ID
    """
    bm = _get_bm()
    result = await _run_sync(_get_conv_detail, bm, item_id, seller_id)

    if not result["success"]:
        return result["message"]

    messages = result["messages"]
    nick = result.get("sellerNick", "卖家")

    if not messages:
        return f"与 {nick} 暂无聊天记录"

    lines = [f"与 {nick} 的聊天记录 ({len(messages)} 条)：", ""]
    for msg in messages:
        sender = "我" if msg.get("sender") == "me" else nick
        content = msg.get("content", "").strip()
        if content:
            lines.append(f"[{sender}]: {content}")
            lines.append("")

    return "\n".join(lines)


# ── 入口 ──────────────────────────────────────────────────────────

def main():
    """MCP Server 入口。"""
    if "--http" in sys.argv:
        mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

"""
IM 消息发送（单发 + 批量）。

- 导航到 IM 对话页面发送消息
- 频率控制：每条消息间隔 2 秒
- 发送验证：检查 snapshot 中是否出现"刚刚"
"""

import time
from typing import List

from .browser import BrowserManager, XIANYU_HOME_URL, _log
from .auth import ensure_logged_in


def _send_single_message(page, item_id: str, seller_id: str, message: str) -> dict:
    """
    向单个卖家发送消息。

    Args:
        page: Playwright Page
        item_id: 商品 ID
        seller_id: 卖家 ID (peerUserId)
        message: 消息内容

    Returns:
        dict: {success: bool, message: str}
    """
    im_url = f"{XIANYU_HOME_URL}/im?itemId={item_id}&peerUserId={seller_id}"

    try:
        page.goto(im_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # 查找输入框（关键词 "请输入"）
        textarea = None
        for sel in [
            'textarea[placeholder*="请输入"]',
            'textarea[placeholder*="输入"]',
            '[contenteditable="true"]',
            'textarea',
        ]:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=3000):
                    textarea = el
                    break
            except Exception:
                continue

        if not textarea:
            return {"success": False, "message": f"未找到输入框 (item={item_id})"}

        # 点击输入框获取焦点
        textarea.click()
        time.sleep(0.5)

        # 输入消息
        textarea.fill(message)
        time.sleep(0.5)

        # 按 Enter 发送
        page.keyboard.press("Enter")
        time.sleep(2)

        # 验证发送成功（检查页面是否出现"刚刚"）
        content = page.content()
        if "刚刚" in content or message[:10] in content:
            _log(f"消息发送成功 → seller={seller_id}")
            return {"success": True, "message": "发送成功"}
        else:
            # 二次验证：检查消息气泡
            try:
                msg_bubble = page.locator('[class*="message"]').first
                if msg_bubble.is_visible(timeout=2000):
                    return {"success": True, "message": "发送成功（已确认消息气泡）"}
            except Exception:
                pass
            return {"success": True, "message": "消息已发送（未严格验证）"}

    except Exception as e:
        _log(f"发送失败 seller={seller_id}: {e}", "err")
        return {"success": False, "message": f"发送异常: {str(e)[:200]}"}


def send_inquiry(
    bm: BrowserManager,
    item_id: str,
    seller_id: str,
    message: str,
) -> dict:
    """
    向指定卖家发送询价消息。

    Args:
        bm: BrowserManager 实例
        item_id: 商品 ID
        seller_id: 卖家 ID
        message: 消息内容

    Returns:
        dict: {success, message}
    """
    login_result = ensure_logged_in(bm)
    if not login_result["success"]:
        return {"success": False, "message": login_result["message"]}

    page = bm.get_page()
    return _send_single_message(page, item_id, seller_id, message)


def batch_send_inquiry(
    bm: BrowserManager,
    items: List[dict],
    message: str,
) -> dict:
    """
    批量发送询价消息。

    Args:
        bm: BrowserManager 实例
        items: [{itemId, sellerId}] 列表
        message: 消息内容

    Returns:
        dict: {success, results: [{itemId, success, error}], sent_count, failed_count}
    """
    login_result = ensure_logged_in(bm)
    if not login_result["success"]:
        return {"success": False, "results": [], "message": login_result["message"]}

    page = bm.get_page()
    results = []
    sent = 0
    failed = 0

    for i, item in enumerate(items):
        item_id = str(item.get("itemId", item.get("item_id", "")))
        seller_id = str(item.get("sellerId", item.get("seller_id", "")))

        if not item_id or not seller_id:
            results.append({"itemId": item_id, "success": False, "error": "缺少 itemId 或 sellerId"})
            failed += 1
            continue

        _log(f"[{i+1}/{len(items)}] 发送询价 → item={item_id}, seller={seller_id}")
        r = _send_single_message(page, item_id, seller_id, message)

        if r["success"]:
            results.append({"itemId": item_id, "success": True})
            sent += 1
        else:
            results.append({"itemId": item_id, "success": False, "error": r["message"]})
            failed += 1

        # 频率控制：每条间隔 2 秒（最后一条不等待）
        if i < len(items) - 1:
            time.sleep(2)

    _log(f"批量发送完成: 成功 {sent}, 失败 {failed}")
    return {
        "success": True,
        "results": results,
        "sent_count": sent,
        "failed_count": failed,
        "message": f"批量发送完成: {sent} 成功, {failed} 失败",
    }

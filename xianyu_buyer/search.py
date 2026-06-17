"""
闲鱼商品搜索 + 卖家信息查询（合并一步）。

关键创新：搜索结果直接附带卖家 ID，不需要用户分两步操作。
技术：在 IM 页面用 lib.mtop.request 查询卖家信息，绕过 CAPTCHA。
"""

import json
import re
import time
import urllib.parse
from typing import List, Optional

from .browser import BrowserManager, XIANYU_HOME_URL, _log
from .auth import ensure_logged_in


def _extract_item_ids_from_search(page, keyword: str, max_results: int) -> List[dict]:
    """
    在搜索页 DOM 中提取商品信息。

    Returns:
        list of {itemId, title, price, href}
    """
    search_url = f"{XIANYU_HOME_URL}/search?q={urllib.parse.quote(keyword)}"
    _log(f"导航到搜索页: {search_url}")
    page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)

    # 等待搜索结果加载
    try:
        page.wait_for_selector('a[href*="/item?id="]', timeout=8000)
    except Exception:
        pass

    # 从 DOM 提取商品信息
    results = page.evaluate(f"""() => {{
        const items = [];
        // 商品卡片链接，包含 /item?id= 的 a 标签
        const links = document.querySelectorAll('a[href*="/item?id="]');
        for (const a of links) {{
            if (items.length >= {max_results}) break;
            const href = a.getAttribute('href') || a.href || '';
            // 从 href 提取 itemId
            const idMatch = href.match(/id=(\\d+)/);
            if (!idMatch) continue;
            const itemId = idMatch[1];

            // 提取标题：取第一个非价格的文本节点
            const allText = Array.from(a.querySelectorAll('*'))
                .flatMap(el => Array.from(el.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim()))
                .filter(t => t && !t.startsWith('¥') && !/^[\\d.,]+$/.test(t));
            const title = (allText[0] || a.getAttribute('title') || '').slice(0, 100);

            // 提取价格
            const priceEl = a.querySelector('[class*="price"]') ||
                            Array.from(a.querySelectorAll('*')).find(
                                el => el.textContent.trim().startsWith('¥')
                            );
            const priceText = priceEl ? priceEl.textContent.trim() : '';
            const priceMatch = priceText.match(/[\\d,.]+/);
            const price = priceMatch ? parseFloat(priceMatch[0].replace(',', '')) : 0;

            if (title && itemId) {{
                items.push({{ itemId, title, price, href }});
            }}
        }}
        return items;
    }}""")

    _log(f"搜索提取到 {len(results)} 条商品")
    return results


def _batch_query_sellers(page, item_ids: List[str]) -> dict:
    """
    在 IM 页面批量查询卖家信息。

    使用 lib.mtop.request 在页面上下文中调用，绕过 CAPTCHA。

    Returns:
        dict: {itemId: {sellerId, nick}}
    """
    if not item_ids:
        return {}

    # 切到 IM 页面获取干净 session
    im_url = f"{XIANYU_HOME_URL}/im"
    _log(f"导航到 IM 页面查询卖家信息: {im_url}")
    page.goto(im_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(3)

    # 通过 page.evaluate 在页面上下文中调 lib.mtop.request
    ids_json = json.dumps(item_ids)
    script = f"""
    new Promise((resolve) => {{
        const items = {ids_json};
        const results = {{}};
        let done = 0;
        items.forEach(itemId => {{
            lib.mtop.request({{
                api: 'mtop.taobao.idle.pc.detail',
                v: '1.0',
                data: {{ itemId }},
                type: 'GET',
                dataType: 'json',
                timeout: 15000
            }}, function(res) {{
                const s = (res.data || {{}}).sellerDO || {{}};
                results[itemId] = {{
                    sellerId: s.sellerId || s.userId || null,
                    nick: s.nick || null
                }};
                done++;
                if (done === items.length) resolve(JSON.stringify(results));
            }}, function(err) {{
                results[itemId] = {{ sellerId: null, nick: null, error: 'query_failed' }};
                done++;
                if (done === items.length) resolve(JSON.stringify(results));
            }});
        }});
    }})
    """

    try:
        result_str = page.evaluate(script)
        sellers = json.loads(result_str)
        _log(f"批量查询完成: {len(sellers)} 个卖家")
        return sellers
    except Exception as e:
        _log(f"批量查询卖家信息失败: {e}", "err")
        return {}


def search_items(
    bm: BrowserManager,
    keyword: str,
    max_price: Optional[float] = None,
    max_results: int = 20,
) -> dict:
    """
    搜索闲鱼商品，一步返回完整信息（含卖家 ID）。

    Args:
        bm: BrowserManager 实例
        keyword: 搜索关键词
        max_price: 最高价格（可选，过滤超价商品）
        max_results: 最多返回数量

    Returns:
        dict: {success, items: [{itemId, title, price, sellerId, sellerNick, href}], message}
    """
    # 登录检查
    login_result = ensure_logged_in(bm)
    if not login_result["success"]:
        return {"success": False, "items": [], "message": login_result["message"]}

    page = bm.get_page()

    # Step 1: 搜索页提取商品信息
    items = _extract_item_ids_from_search(page, keyword, max_results * 2)  # 多取一些用于价格过滤

    if not items:
        return {"success": False, "items": [], "message": f"未找到关键词「{keyword}」的搜索结果"}

    # 价格过滤
    if max_price is not None:
        items = [it for it in items if it.get("price", 0) <= max_price and it.get("price", 0) > 0]

    # 截断
    items = items[:max_results]

    if not items:
        return {"success": False, "items": [], "message": f"筛选后无结果（价格上限 ¥{max_price}）"}

    # Step 2: 批量查询卖家信息
    item_ids = [it["itemId"] for it in items]
    sellers = _batch_query_sellers(page, item_ids)

    # Step 3: 合并结果
    results = []
    for it in items:
        iid = it["itemId"]
        seller = sellers.get(iid, {})
        results.append({
            "itemId": iid,
            "title": it["title"],
            "price": it.get("price", 0),
            "sellerId": seller.get("sellerId"),
            "sellerNick": seller.get("nick"),
            "href": it.get("href", ""),
        })

    _log(f"搜索完成: {len(results)} 条结果")
    return {
        "success": True,
        "items": results,
        "message": f"找到 {len(results)} 条「{keyword}」相关商品",
    }

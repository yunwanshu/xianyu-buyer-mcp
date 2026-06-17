"""
扫码登录 + Cookie 持久化。

- 反向检测逻辑：不找"已登录"信号，而是找"未登录"信号
- Cookie 保存到用户目录 ~/.xianyu-buyer-mcp/cookies.json
- 首次 headed 扫码，后续自动复用
"""

import json
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from .browser import BrowserManager, XIANYU_HOME_URL, _log

# ── Cookie 路径 ───────────────────────────────────────────────────

_DEFAULT_COOKIE_DIR = Path.home() / ".xianyu-buyer-mcp"
COOKIES_PATH = Path(
    os.environ.get("COOKIES_PATH", str(_DEFAULT_COOKIE_DIR / "cookies.json"))
)


# ── Cookie 读写 ───────────────────────────────────────────────────

def _save_cookies(bm: BrowserManager) -> bool:
    """保存浏览器 cookies 到本地文件。"""
    try:
        COOKIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        cookies = bm.context.cookies()
        COOKIES_PATH.write_text(
            json.dumps(cookies, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _log(f"Cookies 已保存 ({len(cookies)} 条) → {COOKIES_PATH}")
        return True
    except Exception as e:
        _log(f"保存 Cookies 失败: {e}", "err")
        return False


def _load_cookies(bm: BrowserManager) -> bool:
    """从本地文件加载 cookies 到浏览器。"""
    if not COOKIES_PATH.exists():
        return False
    try:
        data = COOKIES_PATH.read_text(encoding="utf-8")
        cookies = json.loads(data)
        bm.context.add_cookies(cookies)
        _log(f"Cookies 已加载 ({len(cookies)} 条)")
        return True
    except Exception as e:
        _log(f"加载 Cookies 失败: {e}", "warn")
        return False


# ── 登录状态检测 ──────────────────────────────────────────────────

def _is_logged_in(page) -> bool:
    """
    反向检测登录状态。

    策略：不找"已登录"的正向信号，而是找"未登录"的负向信号。
    如果没有任何负向信号，默认认为已登录。
    """
    url = page.url.lower()

    # 明确在登录页
    if "login.taobao.com" in url or "login.xianyu" in url:
        return False

    # 正向指标：个人中心链接、头像
    positive_selectors = [
        'a[href*="/personal"]',
        '[class*="user-avatar"]',
        '[class*="user-info"]',
    ]
    for sel in positive_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=1000):
                return True
        except Exception:
            continue

    # 负向指标：登录按钮/弹窗
    negative_selectors = [
        'button:has-text("登录")',
        'a:has-text("登录")',
        '[class*="login-btn"]',
        '[class*="login-button"]',
        '[class*="login-modal"]',
        'div[class*="login-popup"]',
        'span:has-text("请登录")',
    ]
    for sel in negative_selectors:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=1000):
                return False
        except Exception:
            continue

    # 无明确信号 → 默认已登录（避免反复打扰用户）
    return True


# ── 登录入口 ──────────────────────────────────────────────────────

def ensure_logged_in(bm: BrowserManager) -> dict:
    """
    确保用户已登录闲鱼。

    流程：
    1. 尝试加载已保存的 cookies
    2. 导航到闲鱼首页，检查登录状态
    3. 如未登录，触发扫码流程

    Returns:
        dict: {success: bool, message: str}
    """
    page = bm.get_page()

    # 尝试加载 cookies
    _load_cookies(bm)

    # 导航到首页检查状态
    try:
        page.goto(XIANYU_HOME_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
    except Exception as e:
        _log(f"导航到首页失败: {e}", "warn")

    if _is_logged_in(page):
        # 已登录，刷新 cookies
        _save_cookies(bm)
        return {"success": True, "message": "已登录闲鱼"}

    # 未登录，触发扫码
    return _do_qrcode_login(bm)


def _do_qrcode_login(bm: BrowserManager, timeout_seconds: int = 180) -> dict:
    """
    扫码登录流程。

    打开登录页面，等待用户用闲鱼/淘宝 App 扫码。
    每秒轮询一次登录状态，直到成功或超时。
    """
    page = bm.get_page()

    _log("=" * 50)
    _log("请在浏览器窗口中扫码登录闲鱼")
    _log(f"超时时间: {timeout_seconds} 秒")
    _log("=" * 50)

    # 尝试点击登录按钮（首页可能有）
    try:
        login_btn = page.locator('button:has-text("登录"), a:has-text("登录")').first
        if login_btn.is_visible(timeout=3000):
            login_btn.click()
            time.sleep(2)
    except Exception:
        pass

    # 轮询等待扫码
    start = time.time()
    while time.time() - start < timeout_seconds:
        if _is_logged_in(page):
            time.sleep(2)  # 等页面稳定
            _save_cookies(bm)
            _log("扫码登录成功！")
            return {"success": True, "message": "扫码登录成功，cookies 已保存"}
        time.sleep(1)

    _log("扫码登录超时", "warn")
    return {
        "success": False,
        "message": f"扫码超时 ({timeout_seconds}s)，请重试",
    }


def check_login_status(bm: BrowserManager) -> dict:
    """
    检查当前登录状态（不触发扫码）。

    Returns:
        dict: {logged_in: bool, message: str}
    """
    page = bm.get_page()
    _load_cookies(bm)

    try:
        page.goto(XIANYU_HOME_URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
    except Exception:
        pass

    logged_in = _is_logged_in(page)

    # 尝试提取用户名
    username = None
    if logged_in:
        try:
            # 个人中心链接文字
            el = page.locator('a[href*="/personal"]').first
            if el.is_visible(timeout=2000):
                username = el.inner_text().strip()
        except Exception:
            pass

    if logged_in:
        _save_cookies(bm)
        return {
            "logged_in": True,
            "message": f"已登录{(' (' + username + ')') if username else ''}",
            "username": username,
        }
    else:
        return {"logged_in": False, "message": "未登录，请调用 login() 扫码"}

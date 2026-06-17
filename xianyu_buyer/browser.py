"""
Playwright 浏览器生命周期管理。

- 单例模式，懒初始化
- headed 模式（反检测 + 用户可见扫码）
- 反指纹注入 + playwright-stealth
- 连接检查 + 自动重连
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

try:
    from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright
except ImportError:
    raise ImportError("playwright not installed. Run: pip install playwright && playwright install chromium")

try:
    from playwright_stealth import stealth_sync
    HAS_STEALTH = True
except ImportError:
    HAS_STEALTH = False

# ── 常量 ──────────────────────────────────────────────────────────

XIANYU_HOME_URL = os.environ.get("XIANYU_HOME_URL", "https://www.goofish.com")
HEADLESS = os.environ.get("PLAYWRIGHT_HEADLESS", "false").strip().lower() == "true"
PROXY = os.environ.get("PROXY", "").strip() or None

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# 反检测注入脚本
_ANTI_DETECT_SCRIPT = """
() => {
    // 隐藏 webdriver 标记
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    // 伪造 plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
    });
    // 伪造 languages
    Object.defineProperty(navigator, 'languages', {
        get: () => ['zh-CN', 'zh', 'en'],
    });
    // 伪造 chrome runtime
    window.chrome = { runtime: {} };
}
"""


def _log(msg: str, level: str = "info") -> None:
    """简易日志，可替换为正式 logger。"""
    import datetime
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    prefix = {"info": "INFO", "warn": "WARN", "err": "ERR"}[level]
    print(f"[{ts}] [{prefix}] {msg}")


# ── BrowserManager ────────────────────────────────────────────────

class BrowserManager:
    """管理 Playwright 浏览器实例，单例 + 懒初始化。"""

    def __init__(self) -> None:
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    # ── 启动 ──────────────────────────────────────────────────

    def _ensure_browser(self) -> None:
        """确保浏览器已启动，未启动则初始化。"""
        if self._browser and self._browser.is_connected():
            return

        _log("正在启动 Chromium 浏览器...")
        self._playwright = sync_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-infobars",
            "--disable-extensions",
            "--window-position=200,50",
            "--window-size=1100,860",
        ]

        launch_kwargs: dict = {
            "headless": HEADLESS,
            "args": launch_args,
        }
        if PROXY:
            launch_kwargs["proxy"] = {"server": PROXY}

        self._browser = self._playwright.chromium.launch(**launch_kwargs)

        context_kwargs: dict = {
            "viewport": {"width": 1100, "height": 860},
            "user_agent": DEFAULT_UA,
            "locale": "zh-CN",
            "timezone_id": "Asia/Shanghai",
        }
        if PROXY:
            context_kwargs["proxy"] = {"server": PROXY}

        self._context = self._browser.new_context(**context_kwargs)

        # 反检测脚本注入
        self._context.add_init_script(_ANTI_DETECT_SCRIPT)

        self._page = self._context.new_page()

        # playwright-stealth 增强
        if HAS_STEALTH:
            stealth_sync(self._page)

        _log(f"浏览器启动完成 (headless={HEADLESS})")

    # ── 获取页面 ──────────────────────────────────────────────

    def get_page(self) -> Page:
        """获取当前 Page，自动确保浏览器已启动。"""
        self._ensure_browser()
        assert self._page is not None
        if not self._browser.is_connected():
            _log("浏览器连接断开，正在重启...", "warn")
            self.close()
            self._ensure_browser()
        return self._page

    @property
    def context(self) -> BrowserContext:
        """获取当前 BrowserContext。"""
        self._ensure_browser()
        assert self._context is not None
        return self._context

    # ── 关闭 ──────────────────────────────────────────────────

    def close(self) -> None:
        """关闭浏览器并释放资源。"""
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None
        _log("浏览器已关闭")

    def __del__(self) -> None:
        self.close()

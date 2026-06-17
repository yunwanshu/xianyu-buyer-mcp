# xianyu-buyer-mcp

闲鱼（Goofish）买家侧询价 MCP Server。支持搜索商品、批量发送询价消息、自动回收卖家回复。

## 功能

| 工具 | 说明 |
|------|------|
| `login` | 扫码登录闲鱼（首次需要，后续自动复用 cookies） |
| `check_login` | 检查登录状态 |
| `search` | 搜索商品，返回商品列表 + 卖家 ID |
| `send_inquiry` | 向单个卖家发送询价消息 |
| `batch_send_inquiry` | 批量发送询价消息 |
| `get_conversations` | 获取 IM 对话列表，查看所有卖家回复 |
| `get_conversation_detail` | 获取与某个卖家的完整聊天记录 |

## 安装

### 前置条件

- Python 3.11+
- 闲鱼/淘宝 App（用于扫码登录）

### 步骤

```bash
# 1. 克隆项目
git clone https://github.com/<your-username>/xianyu-buyer-mcp.git
cd xianyu-buyer-mcp

# 2. 安装依赖
pip install -e .

# 3. 安装 Chromium 浏览器
playwright install chromium
```

### 可选配置

复制环境变量模板并按需修改：

```bash
cp .env.example .env
```

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PLAYWRIGHT_HEADLESS` | `false` | 是否无头模式（建议保持 false 以便扫码） |
| `PROXY` | （空） | HTTP 代理地址 |
| `COOKIES_PATH` | `~/.xianyu-buyer-mcp/cookies.json` | Cookie 存储路径 |
| `XIANYU_HOME_URL` | `https://www.goofish.com` | 闲鱼首页 URL |

## 在 MCP 客户端中使用

### Claude Desktop / Cursor / QoderWork

在 MCP 配置文件中添加：

```json
{
  "mcpServers": {
    "xianyu-buyer": {
      "command": "python",
      "args": ["/path/to/xianyu-buyer-mcp/server.py"]
    }
  }
}
```

### 首次使用

1. 在 AI 助手中调用 `login` 工具
2. 浏览器窗口会自动弹出闲鱼登录页
3. 用闲鱼或淘宝 App 扫码登录
4. Cookies 自动保存到 `~/.xianyu-buyer-mcp/cookies.json`
5. 后续使用无需重复扫码

### 典型流程

```
# 1. 登录
login()

# 2. 搜索商品
search("MacBook Pro M1 16G 512G", max_price=5000)

# 3. 批量询价
batch_send_inquiry(
  items='[{"itemId": "xxx", "sellerId": "yyy"}, ...]',
  message="你好，还在吗？"
)

# 4. 查看回复
get_conversations()

# 5. 查看某个对话详情
get_conversation_detail(item_id="xxx", seller_id="yyy")
```

## 技术细节

- **反检测**: 使用 playwright-stealth + 自定义 UA + navigator 伪造，降低被识别为机器人的风险
- **CAPTCHA 规避**: 卖家信息查询通过 IM 页面的 `lib.mtop.request` SDK 完成，避免商品详情页触发滑块验证
- **频率控制**: 批量发送消息间隔 2 秒，避免触发平台风控
- **线程安全**: 所有浏览器操作在单线程 executor 中序列化执行

## 注意事项

- 闲鱼有反爬机制，请勿高频调用或用于大规模数据采集
- Cookies 有效期有限，过期后需重新扫码
- 本项目仅供学习研究，请遵守闲鱼平台的使用条款

## License

MIT

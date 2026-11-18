# cizhenyu_un_comtrade

UN Comtrade MCP for 词真语 Deploy（零依赖 Python，stdio JSON-RPC）。

查询具体商品的进出口**金额**、**数量**、**单价**与**贸易伙伴流向**。

## 两种接口

| 接口 | 端点 | 说明 |
|------|------|------|
| 无注册 preview | `https://comtradeapi.un.org/public/v1/preview/{type}/{freq}/{cl}` | 无需任何密钥，直接可用；有记录数（约 500）与速率限制 |
| 注册后 data | `https://comtradeapi.un.org/data/v1/get/{type}/{freq}/{cl}` | 订阅 Key 通过 `Ocp-Apim-Subscription-Key`（兼容 `subscription-key`） |

未配置订阅 Key 时自动走 preview；配置后自动切换到完整 data API。

## 工具

- `comtrade_trade_flows` — 核心查询：金额（`value_usd`）、数量（`quantity`）、单价（`unit_price_usd`）、伙伴流向（省略 `partner_code`）。
- `comtrade_verify` — 验证注册后的订阅 Key 是否有效。
- `comtrade_lookup_countries` — 按名称/ISO 查 UN M49 国家代码。
- `comtrade_list_references` — 列出参考代码表（国家/商品分类/单位等）。

## Secrets

Do **not** commit API keys.

Deploy 注入：

- `COMTRADE_SUBSCRIPTION_KEY`（来自表单 `subscriptionKey`）
- 和/或 `CIZHENYU_AUTH_DIR` → `comtrade.json`（`subscriptionKey` / `apiKey`）

## Run

```bash
python server.py                 # stdio MCP
python server.py list            # 列出工具
python server.py check           # 验证订阅 Key
python server.py comtrade_trade_flows --json "{\"reporter_code\":\"156\",\"period\":\"2023\",\"cmd_code\":\"8517\"}"
```

## 示例

中国 2023 年手机（HS 8517）进出口及伙伴流向：

```bash
python server.py comtrade_trade_flows --json "{\"reporter_code\":\"156\",\"period\":\"2023\",\"cmd_code\":\"8517\"}"
```

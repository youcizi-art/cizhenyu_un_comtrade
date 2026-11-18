# UN Comtrade 配置

## 无需注册（预览接口）

本工具**无需注册即可使用**：不填任何密钥时，自动走 `public/v1/preview` 接口，
可直接查询进出口金额、数量、单价与贸易伙伴流向，但有记录数（约 500）与速率限制。

## 注册后可解锁完整 data API（可选）

1. 打开 [UN Comtrade](https://comtradeplus.un.org/) 注册账号。
2. 登录后进入 **My Comtrade → API Portal**，点击 **Generate API Key** 复制订阅 Key。
   - 免费订阅可用部分 API；付费订阅解锁全部 API 与更高限额。
3. 在磁帧鱼 Deploy 工具箱 → UN Comtrade → 配置，粘贴 API Key 并保存。
4. 保存后 `comtrade_trade_flows` 自动切换到 `data/v1/get` 接口。

## 验证

- 工具箱启用后，调用 `comtrade_verify` 可验证订阅 Key 是否有效。
- 命令行自检：`python server.py check`

## 常用代码

- 国家代码（UN M49）：用 `comtrade_lookup_countries` 查询；`156=中国`、`842=美国`、`826=英国`、`702=新加坡`。
- 商品代码：HS 分类，如 `8517=手机`、`85=电机/电气设备`、`TOTAL=全部商品`。
- 流向：`M=进口`、`X=出口`、`M,X=进出口`。

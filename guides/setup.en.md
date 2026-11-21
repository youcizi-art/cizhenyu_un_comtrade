# UN Comtrade setup

## No signup (preview API)

Works without credentials via `public/v1/preview` (import/export value, quantity, unit price, partner flows). Limits apply (~500 rows / rate limits).

## Optional subscription (full data API)

1. Register at [UN Comtrade](https://comtradeplus.un.org/).
2. My Comtrade → API Portal → Generate API Key.
3. Deploy → Toolbox → UN Comtrade → Configure → paste the key.
4. `comtrade_trade_flows` then uses `data/v1/get`.

## Verify

- Call `comtrade_verify` after enabling, or run `python server.py check`.

## Common codes

- Countries (UN M49): `comtrade_lookup_countries`; e.g. `156=China`, `842=USA`.
- Products: HS codes, e.g. `8517=phones`, `TOTAL=all`.
- Flow: `M=import`, `X=export`, `M,X=both`.

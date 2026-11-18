#!/usr/bin/env python3
"""UN Comtrade MCP 服务器 + CLI（零依赖，stdio JSON-RPC）。

查询联合国商品贸易数据：具体商品的进出口金额、数量、单价（金额/数量）与
贸易伙伴流向。

- 无注册接口（preview）：无需任何密钥，直接可用，有记录数与速率限制。
    base = https://comtradeapi.un.org/public/v1/preview/{typeCode}/{freqCode}/{clCode}
- 注册后接口（data）：在 https://comtradeplus.un.org/ 注册并生成订阅 Key，
    通过 header `Ocp-Apim-Subscription-Key`（同时兼容 query `subscription-key`）调用。
    base = https://comtradeapi.un.org/data/v1/get/{typeCode}/{freqCode}/{clCode}

订阅 Key 由词真语 Deploy 注入（无需写死在仓库）：
  - 进程环境 COMTRADE_SUBSCRIPTION_KEY
  - 或 CIZHENYU_AUTH_DIR/comtrade.json 的 subscriptionKey / apiKey

MCP 用法（DSH / Claude / Cursor 挂载）：
  command: <python.exe>
  args:    ["server.py"]
  cwd:     <un-comtrade 目录>

CLI 用法（不依赖 MCP 也能调）：
  python server.py list
  python server.py check
  python server.py comtrade_trade_flows --json "{\"reporter_code\":\"156\",\"period\":\"2023\",\"cmd_code\":\"8517\"}"
  python server.py comtrade_lookup_countries --json "{\"query\":\"china\"}"

协议自检：
  echo {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}} | python server.py
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SERVER_NAME = "un-comtrade"
SERVER_VERSION = "1.0.0"

PREVIEW_BASE = "https://comtradeapi.un.org/public/v1/preview"
DATA_BASE = "https://comtradeapi.un.org/data/v1/get"
LIST_REFERENCES_URL = "https://comtradeapi.un.org/files/v1/app/reference/ListofReferences.json"
REPORTERS_URL = "https://comtradeapi.un.org/files/v1/app/reference/Reporters.json"

# 预览接口单次最多返回的记录数（官方公平使用限制）
PREVIEW_MAX_RECORDS = 500
# 订阅接口单次 maxRecords 上限
DATA_MAX_RECORDS = 100000


class ComtradeError(RuntimeError):
    pass


# ------------------------------------------------------------------ 凭据

def auth_dir() -> Path | None:
    for key in ("CIZHENYU_AUTH_DIR", "SEOGEO_AUTH_DIR"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return Path(raw)
    return None


def subscription_key() -> str:
    """返回订阅 Key；未配置则返回空串（此时走 preview 无注册接口）。"""
    env = os.environ.get("COMTRADE_SUBSCRIPTION_KEY", "").strip()
    if env:
        return env
    base = auth_dir()
    if not base:
        return ""
    path = base / "comtrade.json"
    if not path.is_file():
        return ""
    try:
        conf = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return ""
    for k in ("subscriptionKey", "subscription_key", "apiKey", "api_key"):
        val = conf.get(k)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


# ------------------------------------------------------------------ HTTP

def _get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90, context=ssl.create_default_context()) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        if exc.code in (401, 403):
            raise ComtradeError(
                f"订阅密钥无效或未授权（HTTP {exc.code}）。请检查 API Key 是否已订阅相应 API 产品。"
            ) from exc
        raise ComtradeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ComtradeError(f"网络错误: {exc}") from exc


def _query(path: str, params: dict, key: str = "") -> dict:
    base = DATA_BASE if key else PREVIEW_BASE
    q = {k: v for k, v in params.items() if v is not None and v != ""}
    url = f"{base}/{path}?" + urllib.parse.urlencode(q)
    headers = {
        "Accept": "application/json",
        "User-Agent": f"cizhenyu/{SERVER_NAME}/{SERVER_VERSION}",
    }
    if key:
        headers["Ocp-Apim-Subscription-Key"] = key
        url += "&subscription-key=" + urllib.parse.quote(key)
    data = _get_json(url, headers)
    # 预览接口成功时也带有 "error": ""（空串）；仅当非空才视为错误。
    if isinstance(data, dict) and data.get("error"):
        raise ComtradeError(f"API 返回错误: {json.dumps(data['error'], ensure_ascii=False)}")
    if not isinstance(data, dict) or "data" not in data:
        raise ComtradeError(f"响应缺少 data 字段: {str(data)[:200]}")
    return data


# ------------------------------------------------------------------ 业务

def _clean_record(r: dict) -> dict:
    qty = r.get("qty")
    value = r.get("primaryValue")
    unit_price = None
    if value is not None and isinstance(qty, (int, float)) and qty > 0:
        unit_price = round(value / qty, 4)
    return {
        "period": r.get("period"),
        "reporter_code": r.get("reporterCode"),
        "reporter": r.get("reporterDesc") or r.get("reporterISO") or "",
        "flow": r.get("flowCode"),
        "flow_desc": r.get("flowDesc") or "",
        "partner_code": r.get("partnerCode"),
        "partner": r.get("partnerDesc") or r.get("partnerISO") or "",
        "cmd_code": r.get("cmdCode"),
        "commodity": r.get("cmdDesc") or "",
        "value_usd": value,
        "fob_usd": r.get("fobvalue"),
        "cif_usd": r.get("cifvalue"),
        "quantity": qty,
        "quantity_unit": r.get("qtyUnitAbbr") or r.get("qtyUnitCode"),
        "net_weight_kg": r.get("netWgt"),
        "unit_price_usd": unit_price,
        "customs_code": r.get("customsCode"),
        "mot_code": r.get("motCode"),
    }


def trade_flows(
    reporter_code: str,
    period: str,
    cmd_code: str = "TOTAL",
    flow_code: str = "M,X",
    partner_code: str | None = None,
    partner2_code: str | None = None,
    freq_code: str = "A",
    cl_code: str = "HS",
    type_code: str = "C",
    customs_code: str | None = None,
    mot_code: str | None = None,
    max_records: int = 100,
    aggregate_by: str | None = None,
    breakdown_mode: str = "classic",
) -> dict:
    key = subscription_key()
    mode = "subscription" if key else "preview"
    cap = DATA_MAX_RECORDS if key else PREVIEW_MAX_RECORDS
    max_records = min(int(max_records), cap)

    params = {
        "reporterCode": reporter_code,
        "flowCode": flow_code,
        "cmdCode": cmd_code,
        "partnerCode": partner_code,
        "partner2Code": partner2_code,
        "customsCode": customs_code,
        "motCode": mot_code,
        "maxRecords": max_records,
        "aggregateBy": aggregate_by,
        "breakdownMode": breakdown_mode,
        "includeDesc": True,
    }
    path = f"{type_code}/{freq_code}/{cl_code}"
    periods = [p for p in str(period).split(",") if p]

    if key:
        # 订阅接口支持逗号分隔多 period，一次调用
        params["period"] = ",".join(periods)
        resp = _query(path, params, key)
    else:
        # 预览接口一次只接受单个 period，逐期合并
        merged: list[dict] = []
        total_count = 0
        for p in periods:
            params["period"] = p
            part = _query(path, params, "")
            merged.extend(part.get("data") or [])
            total_count += int(part.get("count") or 0)
        resp = {"data": merged, "count": total_count}

    data = resp.get("data") or []
    records = [_clean_record(r) for r in data]

    values = [r.get("value_usd") for r in records if isinstance(r.get("value_usd"), (int, float))]
    net_wgts = [r.get("net_weight_kg") for r in records if isinstance(r.get("net_weight_kg"), (int, float))]

    return {
        "mode": mode,
        "query": {
            "reporter_code": reporter_code,
            "period": period,
            "cmd_code": cmd_code,
            "flow_code": flow_code,
            "partner_code": partner_code,
            "freq_code": freq_code,
            "cl_code": cl_code,
            "type_code": type_code,
        },
        "count": int(resp.get("count") or 0),
        "returned": len(records),
        "summary": {
            "total_value_usd": round(sum(values), 2) if values else None,
            "total_net_weight_kg": round(sum(net_wgts), 2) if net_wgts else None,
            "note": (
                "value_usd 为 primaryValue（出口 FOB / 进口 CIF，单位美元）；"
                "unit_price_usd = value_usd / quantity，仅当数量>0 时计算；"
                "省略 partner_code 得到全部贸易伙伴流向，partner_code=0 为世界合计。"
            ),
        },
        "records": records,
    }


def verify_key() -> dict:
    key = subscription_key()
    if not key:
        return {
            "verified": False,
            "mode": "none",
            "message": (
                "未配置订阅 Key。当前可使用无注册 preview 接口（有记录数/速率限制）。"
                "如需完整 data API 与更高限额：在 https://comtradeplus.un.org/ 注册，"
                "进入 My Comtrade → API Portal → Generate API Key，再于工具箱配置。"
            ),
        }
    params = {
        "reporterCode": "842",
        "period": "2023",
        "flowCode": "X",
        "cmdCode": "TOTAL",
        "maxRecords": 1,
        "includeDesc": False,
    }
    try:
        resp = _query("C/A/HS", params, key)
        return {
            "verified": True,
            "mode": "subscription",
            "count": int(resp.get("count") or 0),
            "message": "订阅 Key 有效，已接入完整 data API。",
        }
    except ComtradeError as exc:
        return {"verified": False, "mode": "subscription", "message": f"验证失败：{exc}"}


# ------------------------------------------------------------------ 参考数据

_reporters_cache: list[dict] | None = None


def _fetch_reporters() -> list[dict]:
    global _reporters_cache
    if _reporters_cache is not None:
        return _reporters_cache
    data = _get_json(REPORTERS_URL, {"Accept": "application/json"})
    results = data.get("results") if isinstance(data, dict) else data
    if not isinstance(results, list):
        raise ComtradeError("Reporters 参考数据格式异常")
    _reporters_cache = results
    return results


def lookup_countries(query: str = "", limit: int = 50) -> dict:
    q = (query or "").strip().lower()
    results = _fetch_reporters()
    out: list[dict] = []
    for r in results:
        text = (r.get("text") or r.get("reporterDesc") or "").strip()
        code = r.get("reporterCode")
        if code is None:
            code = r.get("id")
        iso2 = (r.get("reporterCodeIsoAlpha2") or "").strip()
        iso3 = (r.get("reporterCodeIsoAlpha3") or "").strip()
        if not q or q in text.lower() or q == str(code) or q == iso2.lower() or q == iso3.lower():
            out.append(
                {
                    "code": code,
                    "name": text,
                    "iso2": iso2 or None,
                    "iso3": iso3 or None,
                    "is_group": bool(r.get("isGroup")),
                }
            )
    # 精确命中排前面，其余按 code 排序
    out.sort(key=lambda x: (not (q and x["name"].lower() == q), _int_or(x["code"], 0)))
    return {
        "query": query,
        "count": len(out),
        "countries": out[: max(1, min(int(limit), 500))],
    }


def list_references() -> dict:
    data = _get_json(LIST_REFERENCES_URL, {"Accept": "application/json"})
    results = data.get("results") if isinstance(data, dict) else data
    if not isinstance(results, list):
        raise ComtradeError("ListofReferences 参考数据格式异常")
    tables = [
        {
            "category": r.get("category"),
            "variable": r.get("variable"),
            "description": r.get("description"),
            "fileuri": r.get("fileuri"),
        }
        for r in results
    ]
    return {"count": len(tables), "tables": tables}


def _int_or(x, default: int) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ 工具注册表

TOOLS = {
    "comtrade_trade_flows": {
        "fn": trade_flows,
        "desc": (
            "查询具体商品的进出口金额、数量、单价与贸易伙伴流向（UN Comtrade）。"
            "未配置订阅 Key 时走无注册 preview 接口（有记录数/速率限制），配置后自动切换完整 data API。"
        ),
        "schema": {
            "type": "object",
            "properties": {
                "reporter_code": {
                    "type": "string",
                    "description": "报告国 UN M49 数字代码，如 156=中国、842=美国、826=英国、702=新加坡。",
                },
                "period": {
                    "type": "string",
                    "description": "期次：年度如 2023，月度如 202305；可逗号分隔多期（订阅接口支持）。",
                },
                "cmd_code": {
                    "type": "string",
                    "default": "TOTAL",
                    "description": "商品代码（HS/SITC 等），如 8517（手机）、85（电机）、TOTAL（全部商品）。",
                },
                "flow_code": {
                    "type": "string",
                    "enum": ["M", "X", "M,X"],
                    "default": "M,X",
                    "description": "贸易流向：M=进口，X=出口，M,X=进出口都查。",
                },
                "partner_code": {
                    "type": "string",
                    "description": "贸易伙伴 UN M49 代码。省略=全部伙伴（流向明细），0=世界合计。",
                },
                "partner2_code": {"type": "string", "description": "第二伙伴代码（可选）。"},
                "freq_code": {
                    "type": "string",
                    "enum": ["A", "M"],
                    "default": "A",
                    "description": "频率：A=年度，M=月度。",
                },
                "cl_code": {
                    "type": "string",
                    "default": "HS",
                    "description": "商品分类：HS（合并 HS）、H0..H6（各 HS 版本）、S1..S4（SITC 版本）、BEC 等。",
                },
                "type_code": {
                    "type": "string",
                    "enum": ["C", "S"],
                    "default": "C",
                    "description": "数据类型：C=货物，S=服务。",
                },
                "customs_code": {"type": "string", "description": "海关制度代码（可选）。"},
                "mot_code": {"type": "string", "description": "运输方式代码（可选）。"},
                "max_records": {
                    "type": "integer",
                    "default": 100,
                    "description": "返回记录数上限（preview 最多 500，订阅最多 100000）。",
                },
                "aggregate_by": {"type": "string", "description": "聚合维度（可选，如 cmdCode/partnerCode）。"},
                "breakdown_mode": {
                    "type": "string",
                    "enum": ["classic", "plus"],
                    "default": "classic",
                    "description": "分解模式：classic（经典）或 plus。",
                },
            },
            "required": ["reporter_code", "period"],
        },
    },
    "comtrade_verify": {
        "fn": verify_key,
        "desc": "验证注册后的订阅 API Key 是否有效（对 data API 做一次最小调用）。",
        "schema": {"type": "object", "properties": {}, "required": []},
    },
    "comtrade_lookup_countries": {
        "fn": lookup_countries,
        "desc": "按名称/ISO 代码查询 UN M49 国家代码（用于 reporter_code / partner_code）。",
        "schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "default": "", "description": "国家名/ISO2/ISO3/代码，如 china、CN、156。"},
                "limit": {"type": "integer", "default": 50},
            },
            "required": [],
        },
    },
    "comtrade_list_references": {
        "fn": list_references,
        "desc": "列出 UN Comtrade 参考表（频率/流向/国家/商品分类/数量单位等代码表）及其下载地址。",
        "schema": {"type": "object", "properties": {}, "required": []},
    },
}


def call_tool(name: str, args: dict) -> dict:
    spec = TOOLS.get(name)
    if not spec:
        return {"error": f"unknown tool: {name}"}
    try:
        result = spec["fn"](**args)
        return {"ok": True, "tool": name, "result": result}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "tool": name, "error": f"{type(exc).__name__}: {exc}"}


# ------------------------------------------------------------------ MCP stdio

def _force_utf8_stdio() -> None:
    # Windows 上管道 stdout 默认可能是 gbk；MCP 客户端按 UTF-8 解码，强制 UTF-8。
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _reply(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def serve() -> None:
    _force_utf8_stdio()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        method = msg.get("method")
        msg_id = msg.get("id")
        params = msg.get("params") or {}

        if method == "initialize":
            _reply({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {
                    "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            })
        elif method in ("notifications/initialized", "initialized"):
            continue
        elif method == "tools/list":
            _reply({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"tools": [
                    {"name": n, "description": s["desc"], "inputSchema": s["schema"]}
                    for n, s in TOOLS.items()
                ]},
            })
        elif method == "tools/call":
            name = params.get("name", "")
            args = params.get("arguments") or {}
            result = call_tool(name, args)
            _reply({
                "jsonrpc": "2.0", "id": msg_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]},
            })
        elif method == "ping":
            _reply({"jsonrpc": "2.0", "id": msg_id, "result": {}})
        elif msg_id is not None:
            _reply({"jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32601, "message": f"method not found: {method}"}})


# ------------------------------------------------------------------ CLI

def cli(argv: list[str]) -> int:
    _force_utf8_stdio()
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "list":
        for name, spec in TOOLS.items():
            print(f"{name:28} {spec['desc']}")
        return 0
    if cmd == "check":
        print(json.dumps(call_tool("comtrade_verify", {}), ensure_ascii=False, indent=2))
        return 0
    args: dict = {}
    if "--args-file" in argv:
        path = argv[argv.index("--args-file") + 1]
        args = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    elif "--json" in argv:
        idx = argv.index("--json")
        args = json.loads(argv[idx + 1])
    else:
        for i, token in enumerate(argv[1:], start=1):
            if token.startswith("--"):
                key = token[2:].replace("-", "_")
                val = argv[i + 1] if i + 1 < len(argv) else ""
                if key in ("max_records", "limit"):
                    args[key] = int(val)
                else:
                    args[key] = val
    print(json.dumps(call_tool(cmd, args), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(cli(sys.argv[1:]))
    serve()

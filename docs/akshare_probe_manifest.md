# AKShare ETF 探针调用清单（阶段 0.6）

采集时间：2026-09-17 11:34:04~11:37:40（Asia/Shanghai）

环境：Python 3.13.3；AKShare 1.18.95；pandas 3.0.5；NumPy 2.5.3；requests 2.34.2。

隔离环境：仓库外临时 venv；未修改项目依赖或系统 Python。

## 1. 实际 AKShare 调用

`attempts` 包含首次请求；`retries=3` 表示首次失败后最多重试 3 次。失败调用的返回行数是“不适用”，不是 0 行。

| 接口 | 标的/范围 | period | adjust | 请求时间（CST） | 耗时 | attempts/retries | 返回 | 结果 |
|---|---|---|---|---|---:|---:|---:|---|
| `fund_etf_hist_em` | `510300.SH`→`510300`；20260817~20260916 | daily | `""` | 11:34:04 | 11.433s | 4/3 | N/A | `request_failed`；`ConnectionError(RemoteDisconnected)` |
| `fund_etf_hist_em` | 同上 | daily | `qfq` | 11:34:15 | 11.227s | 4/3 | N/A | `request_failed`；同上 |
| `fund_etf_hist_em` | 同上 | daily | `hfq` | 11:34:26 | 11.149s | 4/3 | N/A | `request_failed`；同上 |
| `fund_etf_hist_em` | 同上；短期稳定性重复 1 | daily | `""` | 11:34:38 | 10.705s | 4/3 | N/A | `request_failed`；同上 |
| `fund_etf_hist_em` | 同上；短期稳定性重复 2 | daily | `""` | 11:34:48 | 10.988s | 4/3 | N/A | `request_failed`；同上 |
| `fund_etf_spot_em` | 当前横截面 | N/A | N/A | 11:37:13 | 26.372s | 1/0 | 1,618 | `success`；SHA-256 `e973eb2d8c9686380b8c0a747b8b37806ac053cca128edaeaf00bfc3906fdfaf` |

第一次冒烟脚本版本在三种复权失败后仍发出了两次预定的稳定性请求；它们也全部失败。脚本现已修正为：任一冒烟请求失败即停止后续历史请求。没有继续请求另外四只锚点 ETF 或分层样本。

## 2. 结果分类

- 历史接口均未取得 HTTP 内容或 DataFrame，故分类为 `request_failed`，不能分类为“成功但空表”，也不能据此判断 ETF 当日未交易或历史缺失。
- 当前快照成功返回 1,618 行、1,618 个唯一六位代码；缓存只保存在 `.cache/akshare_etf_audit/`，不会加入 Git。
- 没有 Cookie、访问令牌、代理地址或连接信息写入本清单。

## 3. 仅检查签名、docstring 或已安装源码而未调用的相关接口

| 接口 | 当前版本暴露的用途 | 本轮判定 |
|---|---|---|
| `fund_etf_dividend_sina(symbol)` | 单只 ETF 累计分红 | 存在；未调用，不能证明覆盖或稳定性 |
| `fund_fh_em(year, ...)` | 全基金分红事件 | 存在；不是完整 ETF 公司行动账，未调用 |
| `fund_cf_em(year, ...)` | 全基金拆分/折算事件 | 存在；不是独立复权因子，未调用 |
| `fund_etf_fund_daily_em()` | 当前场内交易基金净值列表 | 当前快照/净值用途，不是历史场内 EOD |
| `fund_etf_fund_info_em(fund, ...)` | 单只场内基金历史净值 | 净值用途，不是场内成交价 |
| `fund_etf_scale_sse/szse` | 当前交易所 ETF 规模；深交所结果含上市日期 | 不构成历史 ETF 池或退市史 |

`fund_etf_hist_em` 的当前源码只接受 `adjust in {"", "qfq", "hfq"}` 并返回相应价格序列，没有返回独立复权因子的选项。检查到的 ETF 接口中没有专门的历史停复牌、交易状态、涨跌停价格或完整历史 ETF/退市列表接口。

## 4. 实际执行命令

以下命令均使用仓库外临时 venv 中的 Python：

```powershell
python -m venv $env:TEMP\BetaStrategy-akshare-audit-py313
& $auditPython -m pip install --disable-pip-version-check akshare pytest
& $auditPython -m pytest -q
& $auditPython src/data_audit/audit_akshare_etf_eod.py --mode smoke --as-of 20260916 --start-date 20260817 --cache-dir .cache/akshare_etf_audit/raw --output-dir .cache/akshare_etf_audit/smoke --interval-seconds 2 --max-retries 3
& $auditPython src/data_audit/audit_akshare_etf_eod.py --mode current-universe --as-of 20260916 --universe-csv .cache/akshare_etf_audit/wdzx_current_20260916.csv --cache-dir .cache/akshare_etf_audit/raw --output-dir .cache/akshare_etf_audit/current --interval-seconds 2 --max-retries 3
```

WDZX 当前池由只读 `oracle_wdzx` MCP 分页抽取到忽略缓存；未直连 Oracle，未把 AKShare 调用写入 Oracle SQL 证据文件。

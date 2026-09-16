# WDZX Oracle 数据库可行性审计（阶段 0）

审计日期：2026-09-16（Asia/Shanghai）  
证据来源：仅使用本地只读 `oracle_wdzx` MCP；未直连 Oracle，未执行 DDL/DML/存储过程/`EXPLAIN PLAN`。  
策略依据：仓库 `Beta策略.md` 及任务内嵌说明；仓库内未找到 `Beta策略.docx`。

## 1. 执行摘要与结论

**结论：WDZX 当前不足以支持《Beta策略》的严谨完整历史回测；下一阶段只能先做明确标注限制的简化版，若要做完整回测，必须先补充或确认 ETF 场内日行情数据。**

数据库已经能够支持相当一部分研究工作：ETF 基本资料和上市/退市区间、带进入/退出日的基金分类、ETF—指数有效期映射、基金规模的报告期与公告日、ETF 日净值和净值复权因子、指数日行情、沪深 300 价格/全收益口径、交易日历、停复牌、基金分红/拆分，以及 2019 年以来的上市基金集合竞价价格。受限样例也证明，3 只中证 500 ETF 的复权净值收益可与中证 500 指数连续对齐 61 个交易日，中证 500 与沪深 300 也可连续对齐 61 个交易日，沪深 300 有足够月末数据计算 MA3、MA12 和斜率。

阻止“完整回测”的核心缺口是：**没有找到包含 ETF 未复权 OHLC、复权 OHLC、成交量/额和交易状态的正式日行情表**。`ASHAREEODPRICES` 虽具备所需字段，但对审计样例 `510300.SH`、`510500.SH`、`510510.SH`、`512500.SH` 无记录。现有数据只能分别提供：

- `CHINAMUTUALFUNDNAV`：每日单位净值、复权净值和净值复权因子，不是场内成交价；
- `CHINACLOSEDFUNDAUCTION`：未复权的开/收盘集合竞价成交价和量，样例从 2019-07-25 开始，不是完整日行情，也没有复权价；
- `CMFTRADINGSUSPENSION`：显式停复牌事件；
- `CHINAMFDIVIDEND`、`CMFUNDSPLIT`：现金分红与份额折算事件。

因此，不能把后复权净值静默当作历史真实成交价，也不能仅凭净值因子声称已经得到策略要求的后复权场内开收盘价。

### 1.1 当前 ETF 数量的两个严格口径

- 2026-09-16 可由 `CHINAETFINVESTCLASS`、基本资料和上市/退市条件识别出 **1,667 只已上市、当前有效的 ETF 候选**（Q01）。
- 同日这 1,667 只均有集合竞价表记录，但只有 **920 只**同时有正的开盘集合竞价价格与成交量；另有 1,155 只有有效收盘集合竞价价量（Q01）。因此，若“真正可交易”严格解释为“可在当日开盘集合竞价成交”，可验证数量是 920，而不能把 1,667 全部视为当日开盘可成交。

### 1.2 建议日期范围

- **严谨完整回测：无可推荐起始日。** ETF 正式场内日行情/复权 OHLC 缺口在所有日期上都是阻断项。
- **受限简化版（ETF 复权净值做收益/跟踪误差，集合竞价原价做成交代理）：暂定 2019-08-01 至 2026-09-15。** 3 只样例的集合竞价数据均始于 2019-07-25，且 SSE 日历确认 2019-08-01 是该月首个交易日（Q27）；这一最早日期尚未做全 ETF 覆盖率验证，只能作为原型起点，不能写入正式回测规格。
- **最新共同可用信号日：2026-09-15。** ETF 净值样例更新至该日；指数和集合竞价已到 2026-09-16，因此可验证 T 日信号、T+1 开盘代理，但不能把 2026-09-16 的 ETF 净值视为已完整可得。
- 沪深 300 价格指数 `000300.SH` 收盘历史始于 2002-01-04、开盘始于 2005-01-04；指数正式发布日期是 2005-04-08，早于发布日期的回填值不可用于声称当时可交易。全收益指数是 `h00300.CSI`，收盘历史始于 2004-12-31（Q13、Q14）。

## 2. 必须问题的回答

| # | 问题 | 结论 | 证据与限制 |
|---|---|---|---|
| 1 | 当前可识别多少只真正可交易 ETF | `部分可用` | 1,667 只当前已上市有效 ETF 候选；2026-09-16 仅 920 只有效开盘集合竞价价量。缺少完整日内/日行情，无法证明其余标的可按开盘市价成交（Q01）。 |
| 2 | 能否按历史日重建 ETF 池 | `部分可用` | 基本资料有上市/退市日；基金分类有进入/退出日。2023-06-01 可重建 790 只且包含后来退市的 515930.SH（Q02）。但 ETF 板块代码缺少可见字典，部分 `OPDATE` 晚于生效日，严格 PIT 需补字典/源公告。 |
| 3 | ETF—指数映射是否有历史有效期 | `部分可用` | `CHINAMUTUALFUNDTRACKINGINDEX` 有 `ENTRY_DT`/`REMOVE_DT`，14,717 行中 2,388 行有失效日；515930.SH 有 2023-06-12 失效记录（Q03、Q04）。表内无公告日；部分旧记录 `OPDATE` 晚于生效日多年。业绩基准表有 `ANN_DT`，但不能无条件替代跟踪指数公告史。 |
| 4 | ETF 与指数日数据是否足够长 | `部分可用` | 指数日行情充分；3 只 ETF 净值分别自 2013/2013/2015 覆盖至 2026-09-15（Q09）。但 ETF 正式场内日行情未找到。 |
| 5 | 是否有 ETF 开/收盘、复权因子和后复权开收盘 | `缺失` | 有集合竞价未复权开/收盘和净值复权因子，但没有经字段注释和样例确认的 ETF 场内后复权 OHLC。`ASHAREEODPRICES` 的相关字段对样例 ETF 无行（Q10、Q11、Q22）。 |
| 6 | 沪深 300 是否有至少 12 个月 MA12 预热 | `直接可用` | `000300.SH` 有 5,994 行收盘；2026-07/08 的 MA12 均有 12 个完整月观察，且可计算 S3/S12（Q14、Q18）。 |
| 7 | ETF 与跟踪指数能否按交易日对齐 | `部分可用` | 2026-03 至 05，3 只中证 500 ETF 的复权净值与 `000905.SH` 各有 61 个完整收益配对（Q16）。这是净值口径，不是场内价格口径。 |
| 8 | 指数与沪深 300 能否按交易日对齐 | `可派生` | `000905.SH` 与 `000300.SH` 在同一窗口有 61 个完整收益配对（Q17）；Beta/alpha 公式仍属规则待确认。 |
| 9 | 历史基金规模是否有报告期和公告日 | `直接可用` | `CHINAMUTUALFUNDASSETPORTFOLIO` 同时有 `F_PRT_ENDDATE`、`F_ANN_DATE`、资产总值/净值；3 个样例每期均有公告日（Q06、Q07）。调仓只能选 `F_ANN_DATE < 调仓开盘日` 的最近报告。 |
| 10 | 已退市 ETF 是否保留完整历史 | `部分可用` | 515930.SH 的描述、分类、映射、净值、规模和竞价记录仍在；但净值止于 2023-06-12，退市日为 2023-07-31，竞价仅 381 行且止于 2023-07-28，不能称“完整”（Q20）。 |
| 11 | 能否识别停牌、无成交、开盘缺失、首日 | `部分可用` | 停复牌事件直接可用；竞价空值/价量可识别无开盘集合竞价，基本资料可识别上市首日，竞价表有涨跌停价。样例 `DEALNUM_TOTAL` 全为 NULL，且无完整日成交状态（Q10、Q12）。 |
| 12 | 正式抽取/缓存方案 | `可派生` | 见第 9 节；必须按标的批次和日期增量抽取，保留原始 PIT 字段，不允许每次回测扫描 2,400 万/3,700 万行大表。 |

## 3. 数据需求映射

| 策略环节 | 所需数据 | 表及字段 | 数据频率 | 历史范围 | Point-in-time 依据 | 覆盖情况 | 可用性 | 证据 | 缺口或替代方案 |
|---|---|---|---|---|---|---|---|---|---|
| ETF 池 | ETF 身份、上市/退市、交易所、状态 | `CHINAMUTUALFUNDDESCRIPTION`: `F_INFO_WINDCODE`, `LISTEDFUNDORNOT`, `F_INFO_LISTDATE`, `F_INFO_DELISTDATE`, `F_INFO_EXCHMARKET`, `F_INFO_STATUS` | 事件/快照 | 样例最早 ETF 2005-02-23 | 上市/退市业务日期；`F_INFO_ANNDATE` 是“最新基本信息”公告日，不能还原全部修订 | 当前基础信息完整，历史修订不充分 | `部分可用` | Q01、Q02 | 保存每次抽取快照；补基本资料历史公告表。 |
| ETF 分类 | 历史 ETF 类型 | `CHINAMUTUALFUNDSECTOR`: `S_INFO_SECTOR`, `S_INFO_SECTORENTRYDT`, `S_INFO_SECTOREXITDT`; `CHINAETFINVESTCLASS` 当前分类 | 事件 | 板块样例至 2004-12-30 | 进入/退出日；`OPDATE` 只能说明入库时间 | 当前 1,667 与分类表交叉一致；历史有有效期 | `部分可用` | Q01、Q02 | 补 `2001020200` 的官方板块字典和历史公告/可得日。 |
| 历史存续池 | 任意日已上市且未退市 ETF | 上述两表组合 | 日派生 | 2023-06-01 样例 790 只 | `entry/list <= T < exit/delist` | 能包含后来退市标的 | `可派生` | Q02 | 仍受分类 PIT 风险约束。 |
| ETF—指数 | 跟踪指数及有效期 | `CHINAMUTUALFUNDTRACKINGINDEX`: `S_INFO_WINDCODE`, `S_INFO_INDEXWINDCODE`, `ENTRY_DT`, `REMOVE_DT` | 事件 | 最早 `ENTRY_DT=19000101`（含哨兵/缺省值）至 2026-09-15 | 生效/失效日；无公告日 | 有历史有效期，2,388 条失效记录 | `部分可用` | Q03、Q04 | 对 `19000101` 和迟到 `OPDATE` 制定质量规则；补公告日。 |
| 业绩基准佐证 | 基准代码、权重、公告 | `CHINAMUTUALFUNDBENCHMARK`: `S_INFO_BGNDT`, `S_INFO_ENDDT`, `S_INFO_INDEXWINDCODE`, `S_INFO_INDEXWEG`, `ANN_DT` | 事件 | 样例自 ETF 成立 | `ANN_DT` 与有效期 | 3 只样例均为 100% `000905.SH` | `直接可用` | Q05 | 仅作跟踪关系佐证，不能自动替代 tracking-index 表。 |
| 代表 ETF 筛选 | 历史基金规模 | `CHINAMUTUALFUNDASSETPORTFOLIO`: `F_PRT_ENDDATE`, `F_ANN_DATE`, `F_PRT_TOTALASSET`, `F_PRT_NETASSET`, `CRNCY_CODE` | 季度/报告期 | 样例 2013/2015 至 2026-06-30 | 必须以公告日而非报告期控制可得性 | 样例完整；频率低于调仓频率 | `直接可用` | Q06、Q07 | 使用调仓前最近已公告值；明确规模取总资产还是净资产。 |
| 跟踪误差 | ETF 日收益 | `CHINAMUTUALFUNDNAV`: `PRICE_DATE`, `ANN_DATE`, `F_NAV_ADJUSTED`, `F_NAV_ADJFACTOR` | 日 | 样例 2013/2015 至 2026-09-15 | `PRICE_DATE` 是业务日，保守用 `ANN_DATE` 判可得 | 3 只样例与指数连续对齐 61 日 | `部分可用` | Q08、Q09、Q16 | 仅能严谨称“净值跟踪误差”；场内价格跟踪误差缺行情。公式/窗口待确认。 |
| 指数收益 | 指数收盘/涨跌幅 | `AINDEXEODPRICES`: `TRADE_DT`, `S_DQ_CLOSE`, `S_DQ_PCTCHANGE` | 日 | `000905.SH` 2004-12-31 至 2026-09-16 | T 日收盘后可知 | 收盘完整；百分比单位已复核 | `直接可用` | Q14、Q15 | `S_DQ_PCTCHANGE` 是百分数，建模需除以 100。 |
| Beta/alpha | 指数与基准日收益 | `AINDEXEODPRICES` 同日连接 | 日 | 样例窗口 61 个收益对 | T 日收盘后可知 | 对齐成功 | `可派生` | Q17 | Beta/alpha 精确定义、三个月窗口和价格/全收益口径待确认。 |
| 趋势/均线 | 沪深 300 月末收盘 | `AINDEXEODPRICES` 的 `000300.SH` | 日转月 | 收盘 2002-01-04 起；正式发布 2005-04-08 | 月末收盘后；日内监测在 T 收盘后 | MA3/MA12/S3/S12 可计算 | `可派生` | Q13、Q14、Q18 | 禁止使用发布日期前回填历史声称当时已可知。 |
| 基准口径 | 价格指数/全收益指数 | `AINDEXDESCRIPTION`: `INCOME_PROCESSING_METHOD`; 代码 `000300.SH` / `h00300.CSI` | 静态+事件 | 均发布于 2005-04-08 | 发布日、终止日 | 两种口径均明确且有行情 | `直接可用` | Q13、Q14 | 策略必须选择其一；不可混用。 |
| 月初/T+1 调仓 | 交易日和下一交易日 | `ASHARECALENDAR`: `TRADE_DAYS`, `S_INFO_EXCHMARKET` | 日历 | SSE 1990-12-19 至 2040-12-31 | 日历可能含未来预排日期 | SSE/SZSE 可用 | `直接可用` | Q19 | 临近节假日应冻结已确认日历快照，避免未来调整。 |
| 实际开盘成交 | 场内未复权开盘价/量 | `CHINACLOSEDFUNDAUCTION`: `OPEN_AUCTION_PRICE`, `OPEN_AUCTION_VOLUME`, `MAXUP`, `MAXDOWN` | 日 | 3 只样例 2019-07-25 至 2026-09-16 | 当日开盘后 | 仅 920/1,667 在审计日有效开盘竞价 | `部分可用` | Q01、Q10、Q11 | 不能代表连续竞价第一笔；无集合竞价时需明确不可成交/替代规则。 |
| 信号/成交复权价 | ETF 场内未复权及后复权 OHLC | 未找到满足要求的表 | 日 | 无 | 无 | 关键字段缺失 | `缺失` | Q22 | 补充上市基金正式 EOD 价量/复权因子数据；不得拿净值替代成交价。 |
| 停复牌 | 停牌日、复牌日、原因 | `CMFTRADINGSUSPENSION` | 事件 | 样例 2015 事件 | 停牌/复牌业务日，`OPDATE` 入库日 | 明确事件表 | `直接可用` | Q12 | 仍需和开盘价/量联合判断可成交性。 |
| 分红/折算 | 现金、除息、份额变更 | `CHINAMFDIVIDEND`, `CMFUNDSPLIT` | 事件 | 样例自 2012/2015 | 公告日、登记日、除息/折算日 | 字段较完整 | `直接可用` | Q25、Q26 | 复权价和真实持仓现金/份额必须分账处理。 |
| 历史代码 | 旧/新 Wind 代码 | `CFUNDCHANGEWINDCODE`: `S_INFO_OLDWINDCODE`, `S_INFO_NEWWINDCODE`, `CHANGE_DATE` | 事件 | 样例至 2024 | 变更日和 `OPDATE` | 找到 510820.SH→510810.SH 等样例 | `直接可用` | Q24 | 构建 canonical security id，不能只截取 6 位代码。 |
| 直接指标 | tracking error、Beta、alpha | 未检索到候选表 | 不适用 | 无 | 无 | 无直接指标 | `缺失` | 元数据搜索无结果 | 从原始收益派生；算法仍属规则待确认。 |

## 4. 候选表、键和日期字段

所有表的物理主键均由 MCP `describe_table` 标识为 `OBJECT_ID`。下表的“逻辑键”是回测抽取候选键；仅 Q21 所列小窗口验证过无重复，不能据此宣称全表唯一。

| 表 | 用途 | 代码字段 | 业务/报告/公告/生效日期 | 逻辑键候选 | 验证结果 |
|---|---|---|---|---|---|
| `CHINAMUTUALFUNDDESCRIPTION` | 基金基本资料 | `F_INFO_WINDCODE`, `S_INFO_INNERCODE`, `S_INFO_OUTERCODE`, `SEC_ID` | `F_INFO_LISTDATE`, `F_INFO_DELISTDATE`, `F_INFO_ANNDATE` | `F_INFO_WINDCODE` | 510300/515930 样例区分在市与退市；`.SH/.SZ/.OF` 映射可见。 |
| `CHINAETFINVESTCLASS` | 当前 ETF 分类 | `S_INFO_WINDCODE` | 仅 `OPDATE` | `(S_INFO_WINDCODE,S_INFO_SECTOR)` | 无有效期；同一 ETF 可有多个分类标签。 |
| `CHINAMUTUALFUNDSECTOR` | 历史基金板块 | `F_INFO_WINDCODE`, 内外代码 | `S_INFO_SECTORENTRYDT`, `S_INFO_SECTOREXITDT`, `OPDATE` | `(F_INFO_WINDCODE,S_INFO_SECTOR,ENTRY_DT)` | `2001020200` 与当前分类交叉后得到同样的 1,667 只；代码字典未找到。 |
| `CHINAMUTUALFUNDTRACKINGINDEX` | 跟踪指数 | ETF/指数 Wind 代码 | `ENTRY_DT`, `REMOVE_DT`, `OPDATE` | `(ETF,ENTRY_DT,INDEX)` | 有失效记录；无公告日。 |
| `CHINAMUTUALFUNDBENCHMARK` | 业绩基准 | ETF/指数 Wind 代码 | `S_INFO_BGNDT`, `S_INFO_ENDDT`, `ANN_DT` | `(ETF,BGNDT,SEQUENCE)` | 3 个样例是 100% 中证 500。 |
| `CHINAMUTUALFUNDNAV` | 净值、复权净值 | `F_INFO_WINDCODE` | `PRICE_DATE`, `ANN_DATE`, `OPDATE` | `(F_INFO_WINDCODE,PRICE_DATE)` | 3 只×2026-03~05 无重复；不是成交价格。 |
| `CHINAMUTUALFUNDASSETPORTFOLIO` | 历史规模 | Wind/内外代码 | `F_PRT_ENDDATE`, `F_ANN_DATE`, `OPDATE` | `(S_INFO_WINDCODE,F_PRT_ENDDATE)` | 3 只×2024~2026-06 无重复。 |
| `AINDEXDESCRIPTION` | 指数口径/终止 | `S_INFO_WINDCODE`, `S_INFO_CODE` | `S_INFO_LISTDATE`, `EXPIRE_DATE` | `S_INFO_WINDCODE` | 精确识别沪深 300 价格/全收益代码。 |
| `AINDEXEODPRICES` | 指数行情 | `S_INFO_WINDCODE`, `SEC_ID` | `TRADE_DT`, `OPDATE` | `(S_INFO_WINDCODE,TRADE_DT)` | 2 指数×2026-03~05 无重复。 |
| `ASHARECALENDAR` | 交易日历 | `S_INFO_EXCHMARKET` | `TRADE_DAYS` | `(EXCHANGE,TRADE_DAYS)` | 可用 `LEAD` 派生下一交易日。 |
| `CHINACLOSEDFUNDAUCTION` | ETF 开/收盘集合竞价 | Wind/内外代码 | `TRADE_DT`, `OPDATE` | `(S_INFO_WINDCODE,TRADE_DT)` | 3 ETF×2026-03~05 无重复；`DEALNUM_TOTAL` 样例为空。 |
| `CMFTRADINGSUSPENSION` | 基金停复牌 | `S_INFO_WINDCODE`, `SEC_ID` | `S_DQ_SUSPENDDATE`, `S_DQ_RESUMPDATE` | `(CODE,SUSPENDDATE,TYPE)` | 510500.SH 有份额合并停牌样例。 |
| `CHINAMFDIVIDEND` | 基金分红 | `S_INFO_WINDCODE` | `ANN_DATE`, `EX_DT`, `PAY_DT` 等 | `(CODE,EX_DT,PROGRESS)` | 510300/510500 有现金分红样例。 |
| `CMFUNDSPLIT` | 拆分/折算 | Wind/内外代码 | 公告、折算、除权日 | `(CODE,SHARETRANSDATE,TYPE)` | 510500/512500 有折算样例。 |
| `CFUNDCHANGEWINDCODE` | 历史代码 | 旧/新 Wind 代码 | `CHANGE_DATE`, `OPDATE` | `(OLD_CODE,NEW_CODE,CHANGE_DATE)` | 有场内代码变更样例。 |
| `ASHAREEODPRICES` | 被否决的 ETF 日行情候选 | `S_INFO_WINDCODE` | `TRADE_DT` | `(CODE,TRADE_DT)` | 字段理想，但 4 个 ETF 样例均为 0 行，不能用于 ETF。 |

表规模来自 `ALL_TABLES` 统计值而非全表扫描：`CHINAMUTUALFUNDNAV` 约 3,709 万行、`AINDEXEODPRICES` 约 2,466 万行、`ASHAREEODPRICES` 约 1,849 万行、`CHINACLOSEDFUNDAUCTION` 约 199 万行、`CHINAMUTUALFUNDSECTOR` 约 106 万行（Q23）。

## 5. ETF—指数—基准连接关系

```text
ETF 场内代码（510500.SH）
  ├─ 基本资料：CHINAMUTUALFUNDDESCRIPTION.F_INFO_WINDCODE
  │    └─ 场外代码：S_INFO_OUTERCODE（510500.OF）
  ├─ 历史 ETF 身份：CHINAMUTUALFUNDSECTOR（进入/退出日）
  ├─ 跟踪指数：CHINAMUTUALFUNDTRACKINGINDEX.S_INFO_INDEXWINDCODE
  │    └─ 000905.SH → AINDEXDESCRIPTION / AINDEXEODPRICES
  ├─ 公告佐证：CHINAMUTUALFUNDBENCHMARK（权重、有效期、ANN_DT）
  ├─ 规模：CHINAMUTUALFUNDASSETPORTFOLIO（报告期、公告日）
  ├─ 净值收益：CHINAMUTUALFUNDNAV（PRICE_DATE、ANN_DATE）
  └─ 成交代理：CHINACLOSEDFUNDAUCTION（TRADE_DT）

策略基准
  ├─ 价格指数：000300.SH
  └─ 全收益指数：h00300.CSI
```

历史日期 `T` 的连接条件应至少为：

1. ETF 身份：`sector_entry <= T < sector_exit`；
2. 上市状态：`list_date <= T < delist_date`；
3. 跟踪关系：`tracking_entry <= T < tracking_remove`；
4. 规模：取 `F_ANN_DATE < T 的调仓开盘` 的最新报告；
5. 指数/ETF 收益：只能使用 T 前已结束交易日；月初开盘不能使用当日收盘；
6. 代码变更：先映射到稳定证券 ID，再连接行情，不能只按当前代码回填。

## 6. 复权价格与成交价格口径

1. `CHINAMUTUALFUNDNAV.F_NAV_ADJUSTED` 是**复权单位净值**。样例满足 `F_NAV_UNIT × F_NAV_ADJFACTOR = F_NAV_ADJUSTED`，但这是净值体系，不是交易所成交价体系（Q08）。
2. `CHINACLOSEDFUNDAUCTION.OPEN_AUCTION_PRICE`/`CLOSE_AUCTION_PRICE` 是未复权场内集合竞价成交价，可作为实际成交代理，但不能当作连续竞价完整开/收盘行情（Q10）。
3. `CHINAMFDIVIDEND` 提供公告、登记、除息、派息与每份现金；`CMFUNDSPLIT` 提供公告、折算、场内除权和比例（Q25、Q26）。这些数据足以维护现金和份额，但本轮没有证据证明它们与某个场内价格复权因子完全一致。
4. 后复权价吸收了后续分红/折算信息，数值不是历史真实成交价。正确实现必须至少维护：
   - 信号/收益序列（经选定规则复权）；
   - 原始成交价、持仓份额与现金账；
   - 除息/折算事件对现金与份额的实际影响。
5. 在正式 ETF EOD 数据补齐前，不得将“复权净值 + 未复权集合竞价价”混称为策略原文的“后复权开盘价和收盘价”。

## 7. Point-in-time、前视与幸存者偏差

| 风险 | 证据 | 控制要求 |
|---|---|---|
| 当前 ETF 分类回填历史 | `CHINAETFINVESTCLASS` 无有效期且不含退市 515930.SH | 历史池用 sector/list/delist 有效期；保留退市证券；补板块字典。 |
| 分类/映射事后修订 | 部分 `OPDATE` 比 `ENTRY_DT` 晚多年 | 不把 `OPDATE` 晚到的记录自动视为当时已知；优先源公告日，缺失则降级并做敏感性分析。 |
| 跟踪指数公告缺口 | tracking 表有生效/失效、无公告日 | 用 benchmark 公告交叉核验但不强行等同；关键变更需补公告历史。 |
| 规模前视 | 报告期早于公告日约数周 | 只按 `F_ANN_DATE` 选择可得规模，禁止直接按季度末向前填充。 |
| T 收盘生成 T 开盘交易 | 日行情/净值在收盘后产生 | 月初开盘只用前一交易日及更早数据；交叉在 T 收盘确认，最早 T+1 开盘执行。 |
| 未来分红进入历史成交价 | 后复权序列包含后续现金分配影响 | 信号价格和成交现金账分离；不得用后复权价格直接计算份额和现金。 |
| 指数发布日期前回填 | `000300.SH` 收盘回到 2002，但发布日期为 2005-04-08 | 发布日前数据只能做研究/预热敏感性，不可声称历史参与者当时可获得。 |
| 退市历史不完整 | 515930.SH 净值止于跟踪终止日而非退市日，竞价覆盖也不完整 | 对每只退市标的做 coverage gate；不完整则从可交易池提前剔除需有公告依据，否则整段降级。 |

最大的三个回测风险是：

1. **价格口径错配**：复权净值、后复权信号价格和真实未复权成交价混用会直接扭曲收益、份额和现金。
2. **PIT/幸存者偏差**：当前 ETF 分类、迟到入库的历史分类/映射和退市标的缺口会抬高历史表现。
3. **开盘可成交性高估**：1,667 只当前 ETF 中只有 920 只在审计日有正的开盘集合竞价价量；缺少全日 EOD/首笔成交信息时，不能默认市价单均能按“开盘价”成交。

## 8. 受限可行性样例

样例指数选 `000905.SH`（中证 500），ETF 选 `510500.SH`、`510510.SH`、`512500.SH`。

- 跟踪关系：tracking 表和 benchmark 表都把三者连接到 `000905.SH`；benchmark 权重均为 100%，并有公告日（Q05）。
- 规模：三者均有季度报告期、公告日和资产净值；2024-12-31 至 2025-12-31 每季可见，报告期至公告日约 3 周（Q06）。
- 净值：分别自 2013-02-06、2013-04-11、2015-05-05 覆盖至 2026-09-15，复权净值/因子在样例中无缺失（Q09）。
- ETF—指数对齐：2026-03-02 至 2026-05-29，每只 ETF 与中证 500 均有 61 个完整日收益配对（Q16）。
- 指数—基准对齐：同窗口中证 500 与沪深 300 有 61 个完整日收益配对（Q17）。
- MA：用 2025-05 至 2026-08 月末数据，2026-07/08 的 MA12 观察数均为 12，并成功计算 S3、S12（Q18）。
- 竞价：3 只 ETF 的集合竞价记录从 2019-07-25 到 2026-09-16；2026-06-01~05 的开收盘竞价价量均存在（Q10、Q11）。
- 重复：上述 3 只 ETF 和 2 个指数在 2026-03~05 的净值/指数/竞价逻辑键未发现重复（Q21）。

这个样例证明“净值收益对齐 + 指数信号 + 集合竞价成交代理”的简化研究可做；它没有证明 ETF 场内后复权 OHLC 可做，也不是完整回测。

## 9. 查询性能与正式抽取建议

MCP 连通正常，Oracle 为 11g 11.2.0.4.0。本轮查询全部串行、显式选列、限定代码/日期并使用 MCP `limit`；未做大表无过滤 `COUNT(*)`、全表 distinct 或全表排序。没有查询超时。

正式阶段建议建立只读、可复核的本地列式缓存：

1. **元数据层**：一次性抽取小表（描述、指数描述、跟踪映射、基准、停复牌、代码变更、分红、折算），原样保存 `OBJECT_ID`、业务日、公告日、生效/失效日和 `OPDATE`。
2. **日期分区事实层**：对 NAV、指数日行情、竞价按月或季度、按 50~200 个代码批次抽取；SQL 始终带代码集合和日期上下界。建议 Parquet 分区 `dataset/year/month`，DuckDB/Polars 仅作本地查询层。
3. **不可变原始层 + 派生层**：原始列不覆盖；另建 canonical code、PIT universe、daily returns、month-end、availability-time 等派生表，并记录查询版本和抽取时间。
4. **增量水位**：业务日期和 `OPDATE` 双水位。业务日期抓新增，`OPDATE` 回看最近若干月捕捉迟到修订；修订以新版本保留，不覆盖旧版本。
5. **质量门**：每批验证 `(code,business_date)` 重复、公告日早于使用日、上市/退市边界、指数代码可连接、价格/量非负、百分比缩放、日历连续性和公司行动对账。
6. **覆盖清单**：在回测前生成每只证券各表的 min/max、空值比例和断档区间；这应基于分批已抽取缓存完成，而不是在线扫描 3,700 万行 NAV 表。

## 10. 策略规则待确认

以下均归为 `规则待确认`，不是数据库缺失：

- ETF 范围是否包含跨境、债券、商品、货币、行业、主题、宽基 ETF；
- 是否排除杠杆、反向、增强、联接基金和非上市货币基金；
- tracking error 使用净值收益还是场内价格收益，窗口、样本标准差和年化方式；
- “近三个月”是自然月、约 60 个交易日还是滚动日期区间；
- Beta 是回归斜率还是 Cov/Var；alpha 是回归截距、日均残差还是区间累计超额；
- 指数与基准使用价格指数还是全收益指数；
- 百分位算法、并列值处理、50%~75% 正 Beta 的归属；
- 每组不足 10 个指数、alpha 并列时的处理；
- 月度调仓与交叉信号同日出现的优先级；最高/最低档再次交叉的处理；
- 手续费、滑点、最小交易单位、现金余额、无集合竞价/无法成交的处理；
- 信号价格与成交价格的复权口径；
- 基金规模使用总资产还是净资产，以及多份额/合并口径；
- ETF 无对应指数时“ETF=指数”的收益应取净值还是场内价格。

## 11. 下一阶段建议

**结论选择：必须补充数据后再开发完整回测；如业务接受口径偏离，只能先开发简化版。**

进入完整回测开发前，至少完成：

1. 补充或定位经过字段注释与样例验证的上市 ETF 正式日行情：未复权 OHLC、成交量/额、交易状态、涨跌停、场内复权因子或可审计的公司行动调整链；
2. 补充 ETF 历史分类板块代码字典和跟踪指数变更公告/实际可得日，明确迟到 `OPDATE` 的处理；
3. 对全部历史 ETF（含退市）做分批覆盖审计，确认行情/净值/规模/映射的断档；
4. 由策略负责人确认第 10 节规则。

在此之前允许的简化原型必须在名称和结果中明确写明：**ETF 收益采用复权净值、成交采用集合竞价原价代理、起始日暂定 2019-08-01、结果不等同于策略原文的完整历史回测。**

## 12. 证据索引与限制

- 所有 Q01~Q27 SQL 均收录于 `docs/oracle_wdzx_probe_queries.sql`，均通过 MCP 成功执行；返回 0 行的 Q21/Q22 也是用于证伪/重复检查的成功查询。
- 字段注释、物理主键和表注释来自 MCP `describe_table`/`search_tables`，这些元数据调用不伪装为 SQL。
- 未运行任何回测或实现代码，未创建应用框架，未 commit、未 push。
- 本轮无超时。无法验证事项：ETF 正式 EOD 行情所在表、历史 ETF 板块代码官方字典、tracking-index 初始公告时间、全 ETF 的历史竞价覆盖率，以及退市 ETF 全量完整性。

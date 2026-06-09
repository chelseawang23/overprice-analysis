# 亚太精选ETF (159687) 溢价监控

每天自动分析亚太精选ETF的溢价信号，通过 Seatalk 推送交易提醒。

## 工作流程

| 时间 (北京时间) | 任务 | 说明 |
|----------------|------|------|
| **14:30** | 盘中提醒 | 分析 IOPV 溢价，判断是否尾盘买入 |
| **22:00** | 盘后日报 | NAV 溢价分析 + 成本预估 |

## 策略简介

- 标的：亚太精选ETF (159687)，T+0 交易
- 信号：Δ溢价 > 1.0%（今日 IOPV 溢价与昨日收盘溢价之差）
- 入场：14:55 尾盘集合竞价买入
- 出场：次日 9:25 开盘集合竞价卖出
- 历史回测：57 次信号，累计 +29.7%，胜率 63.2%
- 扣除成本后（0.13%/笔）：累计 +22.3%，年化 6.4%

详见策略分析：[回测报告]()

## 配置

在仓库 Settings → Secrets and variables → Actions 中设置：

### Secrets
- `SEATALK_APP_ID`：Seatalk Open Platform 的 App ID
- `SEATALK_APP_SECRET`：Seatalk App Secret

### Variables（可选）
- `SEATALK_USER_EMAILS`：通知邮箱列表，逗号分隔（默认 huixia.huang@shopee.com,jiayu.lin@shopee.com）
- `COST_MODEL`：成本模型（ideal/low/realistic/conservative，默认 realistic）
- `TRADE_CAPITAL`：每笔资金（默认 20000）

## 手动运行

在 Actions 页面 → ETF 溢价监控 → Run workflow → 选择模式运行。

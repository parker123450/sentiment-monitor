# 情绪面板

一个人用的交易助手：替我盯着美股（半导体为主）的情绪，平时不说话，值得看的时候才说。这个仓库是代码，网页要密码，数据都加密存放。

## 页面从上到下

规则都先写在 [口径.md](口径.md)，再写代码。

1. **今天要知道的**：
   - 只说少见的变化：涨跌、情绪阶段变了、近月比远月贵、趋势状态变了、关系断了、小盘先崩、保险比实际波动贵或便宜、做市商 gamma 转向、预测市场大变化、你的判断有变化。
   - 每条写"过去 10 年几次"，越少见越靠前；没有就一句"今天没有值得看的变化"。
   - 下面列接下来两个交易日的日历。
2. **情绪阶段和 K 线**：
   - 在卖 → 在怕 → 投降 → 在出清。
   - 四条恐慌读数（抛售、定价、仓位、信用）写"少见 / 偏高 / 平常"和"在加速 / 在减速"，不写分位数字。
   - K 线叠阶段色带、恐慌热度、转折标签、期权事件和判断日。
3. **我的判断**：逻辑链每一环每天按规则读支持 / 中性 / 反对；还有"什么情况算我错了"。卡片原文加密存放。
4. **期权**：十个标的各回答五个问题——保险贵不贵、更怕跌还是更想涨、押在哪个价位、做市商会放大还是压住波动、定价了多大的涨跌。
5. **预测市场**：Polymarket，按话题、成交大的。
6. **新闻和日历**：
   - 首屏最多 3 条要闻。
   - 7 天日历附议息会概率和期权定价。
   - 点 K 线某一天，能看那天存下的新闻。
7. **试用记录**：每天点一下，看哪块真有用。

推送（ntfy，也可以加企业微信群机器人、Bark）推新出现的"今天要知道的"、快讯的"第一次"和扩散、数据断了、自检没过；每天最多 6 条（北京 08:00 起算），十年少见的不占名额，超了的第二天早上合成一条。

## 第四轮：交易员雷达（radar 分支，2026-10-27 起，验收通过、用户同意后才合进 main）

- **快讯**（第 1 步，`qx/flash.py`，口径第九节）："今天要知道的"下面。路透经 TradingView 和谷歌新闻取，加 CNBC、MarketWatch、金融时报、Seeking Alpha、日经亚洲、美联储、韩联社、华尔街见闻；按 `登记/entities.toml` 打公司和六条线的标签，观察名单的"第一次"和多家同时报道会推送。
- **Worker**（`worker/`）：Cloudflare 上每 5 分钟取快讯和开盘中市场的价格，页面打开时现取。要用户注册 Cloudflare、加 Secret 以后才部署（`worker-setup.yml` 建库，`worker.yml` 测试和部署）。
- **数据源实测**（第 0 步）：`tools/probe.py`、`docs/数据源实测.md`。

## 怎么跑

| 命令 | 做什么 |
|---|---|
| `python run.py auto` | 云端每 15 分钟跑的：自己决定这次抓什么、算不算 |
| `python run.py page` | 不下载，用存下的数据重算、生成页面 |
| `python run.py daily` | 马上下载一次日线，再算 |
| `python run.py selftest` | 自检：把数据截到过去某天重算，必须和全量一致（不用未来数据） |
| `python run.py seal` | 本机 `../判断/*.json`（判断卡原文，不进仓库）加密成 `cards/*.enc` |
| `python run.py backfill` | 快讯回补过去 30 天（约 3 小时；跑完才推"第一次"） |
| `python run.py pushtest` | 测试推送：正文写发送时间，看手机上的到达时间 |
| `python run.py rules` | 导出给 Worker 的规则 `data/out/rules.json` |
| `cd worker && npm test` | Worker 的测试（不用装包，和 Python 对拍） |

## 放在哪

| 东西 | 在哪 | 公开吗 |
|---|---|---|
| 代码、口径 | main 分支 | 公开 |
| 行情历史 | Actions 缓存 | 不公开 |
| 攒下来的小文件（日志、期权链摘要、CNN、预测市场、要闻、AAII） | data 分支的 `data.enc` | 加密 |
| 完整期权链（每天一份） | Releases | 加密 |
| 网页 | GitHub Pages | 整页加密，要密码 |

Secrets：

- `PAGE_PASSWORD`：网页密码。
- `DATA_KEY`：数据钥匙，本机 `~/.config/qx/data_key` 有一份。钥匙丢了，攒下的历史就打不开了。
- `NTFY_TOPIC`、`FEEDBACK_TOPIC`：推送频道和试用记录频道，本机 `~/.config/qx/` 各有一份。
- 第四轮要加的（用户同意后）：`WECOM_KEY`、`BARK_KEY`（推送渠道，可选）；`CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID`；`WORKER_URL` 和四把 Worker 令牌 `WORKER_READ_TOKEN`、`WORKER_WRITE_TOKEN`、`WORKER_BRIEF_TOKEN`、`WORKER_INGEST_TOKEN`。

数据来源：Yahoo、FRED、CBOE、AAII、CNN、Polymarket、谷歌新闻和几家一手来源。这里只描述市场，不是买卖建议。

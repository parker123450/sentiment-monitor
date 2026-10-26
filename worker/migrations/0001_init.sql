-- 雷达 Worker 的 D1 表（第四轮第 1 步，2026-10-27）。只放公开的新闻标题、行情和读数；判断卡、三种走向不放。
-- news 主键是（路, 去掉参数的链接）；只给 seen 建索引（D1 写入时每个索引多算一行）。
CREATE TABLE IF NOT EXISTS news (
  route TEXT NOT NULL, id TEXT NOT NULL, src TEXT, t TEXT, pub INTEGER, seen INTEGER, ents TEXT, lines TEXT, first TEXT,
  PRIMARY KEY (route, id)
);
CREATE INDEX IF NOT EXISTS news_seen ON news (seen);
-- "第一次"：（主体:线）→ 上次在白名单里看到的时间（毫秒）。Actions 每 15 分钟把它那边看到的（彭博、WSJ 等）经 /firsts 推过来。
CREATE TABLE IF NOT EXISTS firsts (k TEXT PRIMARY KEY, at INTEGER);
-- state：Actions 推来的 rules / 行情少见表 / 各市场时刻，和 Worker 自己的价格包、推送状态。每样一行。
CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT, at INTEGER);
-- 推送记录（所有推送都经 /push 或 Worker 自己的定时，统一上限、去重、合并）
CREATE TABLE IF NOT EXISTS pushlog (key TEXT PRIMARY KEY, at INTEGER, day TEXT, sent INTEGER);
-- 各条路的健康
CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, ok_at INTEGER, fails INTEGER, stop_until INTEGER, n INTEGER, err TEXT);
-- 定时文字（第 6 步）
CREATE TABLE IF NOT EXISTS brief (at INTEGER PRIMARY KEY, slot TEXT, text TEXT);

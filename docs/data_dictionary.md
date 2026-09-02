# 数据字典与口径说明

## 数据源

Yelp Open Dataset v2022（官方公开数据）：https://business.yelp.com/data/resources/open-dataset/
- business：150,346 家商家
- review：6,990,280 条评论（2005-02 ~ 2022-01）
- user：1,987,897 个用户
- tip：908,915 条贴士；checkin：131,930 条签到
- 覆盖 11 个美国都市区

## 数仓结构（DuckDB, yelp.db）

### ODS（原始层，与源 JSON 一致）
| 表 | 内容 |
|---|---|
| raw_business / raw_review / raw_user / raw_tip / raw_checkin | 源文件直读 |

### DWD（维度与事实）
| 表 | 关键字段 |
|---|---|
| dim_business | business_id, name, city, state, stars, review_count, is_open, categories, hours, attributes, category_count, first_review_ts, last_review_ts, biz_age_days |
| fact_review | review_id, user_id, business_id, stars, useful, funny, cool, text, date, yr, mon, month_ts, year_ts |
| dim_month | 月度时间维度（2005-02 起 204 个月） |

### ADS（指标宽表）
| 表 | 关键字段 |
|---|---|
| ads_business_metrics | stars, review_count, cnt_12m（2021 评论量）, cnt_prev12m（2020）, growth_12m（近12月增速）, avg_stars_12m, stars_ge4_ratio（好评占比） |

## 指标口径

| 指标 | 定义 | 备注 |
|---|---|---|
| 星级水平 | 平均星级 | 需结合评论量看（好评偏差） |
| 评论量 | 总评论数 | 客流代理指标（无交易金额数据） |
| 近12月评论量 | 2021-01~2021-12 评论数 | 固定窗口（数据集截止 2022-01） |
| 评论增速 | (cnt_12m − cnt_prev12m)/cnt_prev12m | 趋势/热度 |
| 好评占比 | 近12月 4-5 星评论占比 | 口碑质量 |
| 竞争密度 | 同城同品类商家数 | 品类字段拆行后城市×品类自连接 |
| 商家年龄 | 首评日期至 2022-01-19 天数 | 发展阶段 |

## 关键分析口径

| 分析 | 口径 |
|---|---|
| 抱怨指数 | 低星(1-2)提及率 − 高星(4-5)提及率（词典法 9 维度） |
| 平台大盘外推 | 2015-2019 CAGR（7.1%）外推反事实基线 |
| 高潜识别 | 特征=2020 状态（星级/评论量/好评占比/年龄/2019-20增速/品类），目标=2021 增速 > +50% |
| 样本过滤 | 高潜模型：69,850 家（2020 与 2021 均有评论） |

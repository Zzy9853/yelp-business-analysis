"""
Y1：Yelp 数据建仓（ODS → DWD → ADS）
- ODS：原始 JSON 导入（raw_* 表，与源文件一致）
- DWD：清洗建模（dim_business 商家维度 / fact_review 评论事实 / dim_date 时间维度）
- ADS：商家指标宽表（基础版：星级/评论量/增速/情感/竞争密度）
"""
import sys, io, os, time, json
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import duckdb

# 仓库根目录（相对路径，保证可复现）
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO, "data")   # 将 Yelp JSON 解压后的 5 个文件放到 data/ 目录
DB = os.path.join(REPO, "yelp.db")
os.makedirs(os.path.dirname(DB), exist_ok=True)

con = duckdb.connect(DB)
t0 = time.time()
log = []


def step(name, fn):
    s = time.time()
    fn()
    log.append(f"{name}: {time.time()-s:.1f}s")
    print(f"  ✅ {name} ({time.time()-s:.1f}s)")


print("═══ Y1 建仓开始 ═══")

# ── ODS：原始层 ──
def ods():
    con.execute(f"CREATE OR REPLACE TABLE raw_business AS SELECT * FROM read_json_auto('{SRC}/yelp_academic_dataset_business.json')")
    con.execute(f"CREATE OR REPLACE TABLE raw_review AS SELECT * FROM read_json_auto('{SRC}/yelp_academic_dataset_review.json')")
    con.execute(f"CREATE OR REPLACE TABLE raw_user AS SELECT * FROM read_json_auto('{SRC}/yelp_academic_dataset_user.json')")
    con.execute(f"CREATE OR REPLACE TABLE raw_tip AS SELECT * FROM read_json_auto('{SRC}/yelp_academic_dataset_tip.json')")
    con.execute(f"CREATE OR REPLACE TABLE raw_checkin AS SELECT * FROM read_json_auto('{SRC}/yelp_academic_dataset_checkin.json')")
    print(f"  ODS: {con.execute('SELECT count(*) FROM raw_business').fetchone()[0]:,} 商家 / {con.execute('SELECT count(*) FROM raw_review').fetchone()[0]:,} 评论")


step("ODS 原始层", ods)

# ── DWD：维度与事实 ──
def dwd():
    # 商家维度（含首/末评论时间、商家年龄、类别数）
    con.execute("""
    CREATE OR REPLACE TABLE dim_business AS
    SELECT b.business_id, b.name, b.city, b.state, b.postal_code,
           b.latitude, b.longitude,
           b.stars, b.review_count, b.is_open,
           b.categories, b.hours, b.attributes,
           array_length(string_split(b.categories, ', ')) AS category_count,
           r.first_review_ts, r.last_review_ts,
           date_diff('day', r.first_review_ts::DATE, date '2022-01-19') AS biz_age_days
    FROM raw_business b
    LEFT JOIN (
        SELECT business_id,
               min(date) AS first_review_ts,
               max(date) AS last_review_ts
        FROM raw_review GROUP BY business_id
    ) r ON b.business_id = r.business_id
    """)
    # 评论事实
    con.execute("""
    CREATE OR REPLACE TABLE fact_review AS
    SELECT review_id, user_id, business_id, stars,
           useful, funny, cool, text,
           date, year(date) AS yr, month(date) AS mon,
           date_trunc('month', date) AS month_ts,
           date_trunc('year', date) AS year_ts
    FROM raw_review
    """)
    # 时间维度（月）
    con.execute("""
    CREATE OR REPLACE TABLE dim_month AS
    SELECT range AS month_idx,
           date '2005-02-01' + INTERVAL (range) MONTH AS month_start,
           year(date '2005-02-01' + INTERVAL (range) MONTH) AS yr,
           month(date '2005-02-01' + INTERVAL (range) MONTH) AS mon
    FROM range(0, 204)
    """)
    print(f"  DWD: dim_business {con.execute('SELECT count(*) FROM dim_business').fetchone()[0]:,} / fact_review {con.execute('SELECT count(*) FROM fact_review').fetchone()[0]:,}")

step("DWD 维度事实", dwd)

# ── ADS：商家指标宽表（基础版）──
def ads():
    con.execute("""
    CREATE OR REPLACE TABLE ads_business_metrics AS
    SELECT b.business_id, b.name, b.city, b.state, b.is_open,
           b.stars, b.review_count,
           b.first_review_ts, b.last_review_ts, b.biz_age_days,
           b.category_count,
           -- 近 12 个月（2021-01 ~ 2021-12）评论量
           r12.cnt_12m,
           -- 前 12 个月（2020-01 ~ 2020-12）评论量
           r12p.cnt_prev12m,
           -- 近 12 个月增速（相对前 12 个月）
           CASE WHEN r12p.cnt_prev12m > 0 THEN (r12.cnt_12m - r12p.cnt_prev12m) * 1.0 / r12p.cnt_prev12m END AS growth_12m,
           -- 平均评分（近 12 个月）
           r12.avg_stars_12m,
           -- 情感（近 12 个月评论平均情感，基于星级代理；文本情感 Y3 补充）
           r12.stars_ge4_ratio,
           -- 评论活跃天数（评论跨度）
           b.biz_age_days
    FROM dim_business b
    LEFT JOIN (
        SELECT business_id, count(*) AS cnt_12m,
               avg(stars) AS avg_stars_12m,
               avg(CASE WHEN stars >= 4 THEN 1.0 ELSE 0.0 END) AS stars_ge4_ratio
        FROM fact_review WHERE date BETWEEN '2021-01-01' AND '2021-12-31'
        GROUP BY business_id
    ) r12 ON b.business_id = r12.business_id
    LEFT JOIN (
        SELECT business_id, count(*) AS cnt_prev12m
        FROM fact_review WHERE date BETWEEN '2020-01-01' AND '2020-12-31'
        GROUP BY business_id
    ) r12p ON b.business_id = r12p.business_id
    """)
    n = con.execute("SELECT count(*) FROM ads_business_metrics").fetchone()[0]
    with_12m = con.execute("SELECT count(*) FROM ads_business_metrics WHERE cnt_12m IS NOT NULL AND cnt_12m > 0").fetchone()[0]
    print(f"  ADS: {n:,} 商家, 近12个月有评论 {with_12m:,}")

step("ADS 指标宽表", ads)

# ── 校验 ──
n_biz = con.execute("SELECT count(*) FROM dim_business").fetchone()[0]
n_rev = con.execute("SELECT count(*) FROM fact_review").fetchone()[0]
dup = con.execute("SELECT count(*) FROM (SELECT business_id FROM dim_business GROUP BY business_id HAVING count(*) > 1)").fetchone()[0]
print(f"\n═══ 建仓校验 ═══")
print(f"  商家维度: {n_biz:,} (重复 {dup}) | 评论事实: {n_rev:,}")
print(f"  总耗时: {time.time()-t0:.0f}s")
con.close()
print("[Y1 建仓完成] yelp.db")

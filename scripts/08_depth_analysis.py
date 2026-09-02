"""
Z7：剩余扩展分析——新店存活率 / 评论权威性加权 / 竞争进入影响 / 增长归因分解 / 健康度指数
"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import duckdb
from scipy.stats import spearmanr

con = duckdb.connect(os.path.join(REPO, "yelp.db"), read_only=True)

print("═══ 1. 新店存活率曲线（按入驻年份）═══")
surv = con.execute("""
SELECT year(first_review_ts) cohort, is_open,
       count(*) n
FROM dim_business
WHERE first_review_ts IS NOT NULL AND year(first_review_ts) BETWEEN 2013 AND 2019
GROUP BY 1, 2 ORDER BY 1, 2
""").df()
piv = surv.pivot(index="cohort", columns="is_open", values="n").fillna(0)
piv["存活率"] = piv[1] / (piv[0] + piv[1])
print("入驻年份 × 存活率（截至 2022-01）:")
for c in piv.index:
    print(f"  {c} 年入驻: n={piv.loc[c,0]+piv.loc[c,1]:,.0f} 存活率 {piv.loc[c,'存活率']*100:.1f}%")

print("\n═══ 2. 评论权威性加权（useful 投票）═══")
w = con.execute("""
SELECT CASE WHEN useful >= 5 THEN '高有用(≥5)'
            WHEN useful >= 1 THEN '中有用(1-4)'
            ELSE '低有用(0)' END band,
       count(*) n, avg(stars) avg_stars,
       avg(CASE WHEN stars<=2 THEN 1 ELSE 0 END) low_ratio
FROM fact_review WHERE yr=2021 GROUP BY 1 ORDER BY min(useful)
""").fetchall()
print("2021 评论按有用投票分层:")
for r in w:
    print(f"  {r[0]}: n={r[1]:,} 平均星级={r[2]:.2f} 低星占比={r[3]*100:.1f}%")

print("\n═══ 3. 竞争进入影响（新店进入对老店）═══")
df3 = con.execute("""
WITH cat AS (SELECT business_id, city, trim(cat) cat FROM
             (SELECT business_id, city, unnest(string_split(categories, ', ')) cat FROM dim_business)),
     entry AS (SELECT c.city, c.cat, count(*) new_n
               FROM cat c JOIN dim_business b USING (business_id)
               WHERE year(b.first_review_ts) IN (2020, 2021)
               GROUP BY 1,2),
     old AS (SELECT c.business_id, c.city, c.cat
             FROM cat c JOIN dim_business b USING (business_id)
             WHERE year(b.first_review_ts) <= 2018),
     rev AS (SELECT business_id, yr, count(*) n, avg(stars) s
             FROM fact_review WHERE yr IN (2019, 2021) GROUP BY 1, 2),
     r19 AS (SELECT business_id, n n19, s s19 FROM rev WHERE yr=2019),
     r21 AS (SELECT business_id, n n21, s s21 FROM rev WHERE yr=2021)
SELECT o.business_id, o.city, o.cat, COALESCE(e.new_n, 0) new_entrants,
       r19.n19, r21.n21, r19.s19, r21.s21
FROM old o
LEFT JOIN entry e ON o.city=e.city AND o.cat=e.cat
LEFT JOIN r19 ON o.business_id=r19.business_id
LEFT JOIN r21 ON o.business_id=r21.business_id
WHERE r19.n19 IS NOT NULL AND r21.n21 IS NOT NULL
""").df()
df3["growth"] = (df3["n21"] - df3["n19"]) / df3["n19"].clip(lower=1)
df3["new_band"] = np.where(df3["new_entrants"] == 0, "无新店", 
                   np.where(df3["new_entrants"] <= 10, "低进入(1-10)", "高进入(>10)"))
print(f"老店样本: {len(df3):,}")
print("新店进入强度 × 老店增速中位:")
for band, sub in df3.groupby("new_band", observed=True):
    print(f"  {band}: n={len(sub):,} 老店增速中位={sub['growth'].median():.2f}")
rho, p = spearmanr(df3["new_entrants"], df3["growth"])
print(f"新店进入数 × 老店增速 Spearman: {rho:+.3f} (p={p:.2e})")

print("\n═══ 4. 评论量增长归因分解（2019→2021）═══")
dec = con.execute("""
WITH y AS (SELECT yr, count(*) c FROM fact_review WHERE yr IN (2019,2021) GROUP BY 1),
cat AS (SELECT business_id, trim(cat) cat FROM (SELECT business_id, unnest(string_split(categories, ', ')) cat FROM dim_business)),
cy AS (SELECT c.cat, r.yr, count(*) c
       FROM cat c JOIN fact_review r USING (business_id)
       WHERE r.yr IN (2019,2021) GROUP BY 1,2)
SELECT * FROM y ORDER BY 1
""").fetchall()
c19 = dict(dec)["__x__"] if False else None
# 简化：直接查
rows = con.execute("SELECT yr, count(*) FROM fact_review WHERE yr IN (2019,2021) GROUP BY 1 ORDER BY 1").fetchall()
c19, c21 = rows[0][1], rows[1][1]
print(f"全量评论: 2019={c19:,} → 2021={c21:,} (总增速 {c21/c19-1:+.1%})")
cat_rows = con.execute("""
WITH cat AS (SELECT business_id, trim(cat) cat FROM (SELECT business_id, unnest(string_split(categories, ', ')) cat FROM dim_business)),
cy AS (SELECT c.cat, r.yr, count(*) c
       FROM cat c JOIN fact_review r USING (business_id)
       WHERE r.yr IN (2019,2021) AND c.cat IN ('Restaurants','Shopping','Beauty & Spas','Nightlife','Home Services')
       GROUP BY 1,2)
SELECT cat, sum(CASE WHEN yr=2021 THEN c END)*1.0/sum(CASE WHEN yr=2019 THEN c END) g
FROM cy GROUP BY 1 ORDER BY g
""").fetchall()
print("品类增速（2019→2021）:")
for r in cat_rows:
    print(f"  {r[0]}: {r[1]-1:+.1%}")

print("\n═══ 5. 商家健康度综合指数 ═══")
hlth = con.execute("""
WITH m AS (SELECT business_id, stars, review_count, cnt_12m, growth_12m, stars_ge4_ratio
           FROM ads_business_metrics WHERE cnt_12m IS NOT NULL AND cnt_12m > 0),
comp AS (SELECT c1.business_id, count(DISTINCT c2.business_id) comp_n
         FROM (SELECT business_id, city, trim(cat) cat FROM (SELECT business_id, city, unnest(string_split(categories, ', ')) cat FROM dim_business)) c1
         JOIN (SELECT business_id, city, trim(cat) cat FROM (SELECT business_id, city, unnest(string_split(categories, ', ')) cat FROM dim_business)) c2
         ON c1.city=c2.city AND c1.cat=c2.cat AND c1.business_id<>c2.business_id
         GROUP BY 1)
SELECT m.*, COALESCE(c.comp_n, 0) comp_n FROM m LEFT JOIN comp c USING (business_id)
""").df()
# 分位归一化各维度（1=最健康）
for col in ["stars", "review_count", "cnt_12m", "growth_12m", "stars_ge4_ratio"]:
    hlth[f"pct_{col}"] = hlth[col].rank(pct=True)
hlth["pct_comp_inv"] = 1 - hlth["comp_n"].rank(pct=True)  # 竞争密度反向（竞争小=更健康）
# 加权健康度（规模/质量/趋势/竞争 各 0.25）
hlth["health"] = (hlth["pct_stars"] + hlth["pct_review_count"] + hlth["pct_growth_12m"] + hlth["pct_comp_inv"]) / 4
print(f"健康度指数分布: 均值 {hlth['health'].mean():.3f} 标准差 {hlth['health'].std():.3f}")
top = hlth["health"] >= hlth["health"].quantile(0.8)
print(f"top20% 健康度商家: {top.sum():,} 家")
print(f"  星级中位: {hlth[top]['stars'].median():.1f} vs 其余 {hlth[~top]['stars'].median():.1f}")
print(f"  近12月评论中位: {hlth[top]['cnt_12m'].median():.0f} vs 其余 {hlth[~top]['cnt_12m'].median():.0f}")

con.close()
print("\n[Z7 完成]")

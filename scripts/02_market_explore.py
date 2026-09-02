"""
Y2：探索与指标定义
- 市场画像深挖：星级×品类/城市/竞争/年龄/活跃度
- 商家表现指标体系定稿
- 填充 Y0 骨架占位数字
"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import duckdb

import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
con = duckdb.connect(os.path.join(REPO, "yelp.db"), read_only=True)


def q(sql, label):
    rows = con.execute(sql).fetchall()
    print(f"\n── {label} ──")
    for r in rows:
        print("  " + str(r))
    return rows


print("═══ Y2 市场画像 ═══")

# 1. 星级分布（全量与活跃商家）
q("""
SELECT '全量' grp, round(stars,0) st, count(*) c FROM dim_business GROUP BY 2,1
UNION ALL SELECT '活跃(近12月有评论)', round(stars,0), count(*) FROM ads_business_metrics WHERE cnt_12m IS NOT NULL AND cnt_12m>0 GROUP BY 2
ORDER BY 1,2
""", "星级分布：全量 vs 活跃")

# 2. 活跃 vs 关闭商家画像
q("""
SELECT b.is_open,
       count(*) n,
       round(avg(b.stars),2) avg_stars,
       round(avg(b.review_count),1) avg_rc,
       round(avg(b.biz_age_days)) avg_age_days,
       round(avg(CASE WHEN a.cnt_12m IS NOT NULL AND a.cnt_12m>0 THEN 1 ELSE 0 END),3) active_ratio
FROM dim_business b LEFT JOIN ads_business_metrics a ON b.business_id=a.business_id
GROUP BY 1
""", "营业 vs 关闭商家画像")

# 3. 品类星级分布（Top 品类）
q("""
WITH cat AS (SELECT business_id, trim(cat) cat FROM (SELECT business_id, unnest(string_split(categories, ', ')) cat FROM dim_business))
SELECT cat, count(*) n, round(avg(b.stars),2) avg_stars, round(avg(b.review_count),1) avg_rc
FROM cat c JOIN dim_business b USING (business_id)
WHERE cat IN ('Restaurants','Shopping','Beauty & Spas','Home Services','Health & Medical','Nightlife','Automotive','Local Services')
GROUP BY 1 ORDER BY n DESC
""", "主要品类画像")

# 4. 商家年龄与星级（新店 vs 老店）
q("""
SELECT CASE WHEN biz_age_days < 365 THEN '新店<1年'
            WHEN biz_age_days < 1461 THEN '1-4年'
            WHEN biz_age_days < 2922 THEN '4-8年'
            ELSE '8年+' END age_band,
       count(*) n, round(avg(stars),2) avg_stars, round(avg(review_count),1) avg_rc,
       round(avg(CASE WHEN is_open THEN 1 ELSE 0 END),3) open_ratio
FROM dim_business GROUP BY 1 ORDER BY min(biz_age_days)
""", "商家年龄带画像")

# 5. 评论增速分布（近 12 月 vs 前 12 月）
q("""
SELECT CASE WHEN growth_12m > 0.5 THEN '高速增长>+50%'
            WHEN growth_12m > 0 THEN '增长0~50%'
            WHEN growth_12m IS NULL AND cnt_12m > 0 THEN '新活跃(前12月无评论)'
            WHEN growth_12m < 0 THEN '下滑' END band,
       count(*) n
FROM ads_business_metrics WHERE cnt_12m IS NOT NULL AND cnt_12m > 0
GROUP BY 1 ORDER BY 2 DESC
""", "近12月评论增速分布（活跃商家）")

# 6. 城市画像
q("""
SELECT city, count(*) n, round(avg(stars),2) avg_stars,
       round(avg(CASE WHEN is_open THEN 1 ELSE 0 END),3) open_ratio
FROM dim_business GROUP BY 1 HAVING count(*) >= 3000 ORDER BY n DESC LIMIT 10
""", "主要城市画像")

# 7. 竞争密度（简化：同城同品类的商家数均值，用 join 优化）
q("""
WITH cat AS (SELECT business_id, city, trim(cat) cat FROM (SELECT business_id, city, unnest(string_split(categories, ', ')) cat FROM dim_business)),
     comp AS (SELECT c1.business_id, count(DISTINCT c2.business_id) comp_n
              FROM cat c1 JOIN cat c2 ON c1.city=c2.city AND c1.cat=c2.cat AND c1.business_id<>c2.business_id
              GROUP BY 1)
SELECT round(avg(comp_n)) avg_comp, max(comp_n) max_comp,
       count(*) FILTER (WHERE comp_n >= 500) high_comp_n,
       count(*) FILTER (WHERE comp_n < 10) low_comp_n
FROM comp
""", "竞争密度分布")

con.close()
print("\n[Y2 探索完成]")

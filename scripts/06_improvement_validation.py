"""
Z5：P0 改进收益验证——"减少等待抱怨是否提升星级"
验证 A（横截面，控制混杂）：等待抱怨占比高的商家，星级是否系统性更低？
验证 B（时间，改进收益）：等待抱怨占比下降的商家，星级是否上升？（变化-变化相关）
"""
import sys, io
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

print("═══ Z5 改进收益验证 ═══")
df = con.execute("""
WITH wait20 AS (SELECT business_id,
                avg(CASE WHEN text LIKE '%wait%' OR text LIKE '%line%' OR text LIKE '%long time%' OR text LIKE '%waiting%' THEN 1.0 ELSE 0.0 END) wait20,
                avg(stars) stars20, count(*) n20
                FROM fact_review WHERE yr=2020 GROUP BY 1),
     wait21 AS (SELECT business_id,
                avg(CASE WHEN text LIKE '%wait%' OR text LIKE '%line%' OR text LIKE '%long time%' OR text LIKE '%waiting%' THEN 1.0 ELSE 0.0 END) wait21,
                avg(stars) stars21, count(*) n21
                FROM fact_review WHERE yr=2021 GROUP BY 1),
     cat AS (SELECT business_id, first(trim(cat)) main_cat FROM
             (SELECT business_id, unnest(string_split(categories, ', ')) cat FROM dim_business)
             WHERE trim(cat) IS NOT NULL GROUP BY 1)
SELECT w20.business_id, w20.wait20, w20.stars20, w20.n20,
       w21.wait21, w21.stars21, w21.n21,
       c.main_cat, b.city
FROM wait20 w20
JOIN wait21 w21 USING (business_id)
JOIN dim_business b USING (business_id)
LEFT JOIN cat c USING (business_id)
WHERE w20.n20 >= 5 AND w21.n21 >= 5
""").df()
print(f"样本: {len(df):,} 家（2020 与 2021 都有 ≥5 评论）")

# 星级变化与等待抱怨变化
df["delta_stars"] = df["stars21"] - df["stars20"]
df["delta_wait"] = df["wait21"] - df["wait20"]
df["n20_log"] = np.log1p(df["n20"])

print("\n═══ 验证 A：横截面（2020 等待抱怨占比 × 2020 星级，控制评论量）═══")
rho_all, p = spearmanr(df["wait20"], df["stars20"])
print(f"全量 Spearman: wait20 × stars20 = {rho_all:+.3f} (p={p:.2e})")
# 控制评论量分层
df["size_band"] = pd.qcut(df["n20_log"], 4, labels=["小","中","中大","大"])
print("控制评论量后（同规模内）:")
for band, sub in df.groupby("size_band", observed=True):
    rho, p = spearmanr(sub["wait20"], sub["stars20"])
    print(f"  {band}规模 (n={len(sub):,}): rho={rho:+.3f} (p={p:.2e})")
# 品类分层
print("控制品类后（Top 品类内）:")
for c in ["Restaurants", "Shopping", "Beauty & Spas", "Nightlife", "Home Services"]:
    sub = df[df["main_cat"] == c]
    if len(sub) > 1000:
        rho, p = spearmanr(sub["wait20"], sub["stars20"])
        print(f"  {c} (n={len(sub):,}): rho={rho:+.3f} (p={p:.2e})")

print("\n═══ 验证 B：改进收益（等待抱怨减少 × 星级变化）═══")
rho, p = spearmanr(df["delta_wait"], df["delta_stars"])
print(f"Δwait × Δstars = {rho:+.3f} (p={p:.2e}) —— 负相关=等待抱怨减少伴随星级上升")
# 分位对比：wait 改善组 vs 恶化组
df["wait_chg_band"] = pd.qcut(df["delta_wait"], 3, labels=["改善", "持平", "恶化"])
print("\n等待抱怨变化三分位 × 星级变化均值:")
for band, sub in df.groupby("wait_chg_band", observed=True):
    print(f"  {band}: Δ星级均值={sub['delta_stars'].mean():+.3f} (n={len(sub):,})")
# 控制初始星级
print("\n控制初始星级后（同初始星级内）:")
df["stars20_band"] = pd.qcut(df["stars20"], 4, labels=["低星","中低","中高","高星"])
for sb in ["低星", "中低", "中高", "高星"]:
    sub = df[df["stars20_band"] == sb]
    rho, p = spearmanr(sub["delta_wait"], sub["delta_stars"])
    print(f"  {sb} (n={len(sub):,}): Δwait×Δstars rho={rho:+.3f} (p={p:.2e})")

con.close()
print("\n[Z5 P0 完成]")

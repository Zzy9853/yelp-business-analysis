"""
Y5：Yelp 项目图表系列（8 张）
输出到 Yelp分析/charts/
"""
import sys, io, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import numpy as np
import pandas as pd
import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHART = os.path.join(REPO, "charts")
os.makedirs(CHART, exist_ok=True)
C1, C2, C3, GRAY = "#4C72B0", "#55A868", "#C44E52", "#94A3B8"
con = duckdb.connect("yelp.db", read_only=True)


def save(fig, name):
    fig.savefig(f"{CHART}/{name}", dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  ✅ {name}")


# ── fig_y1: 星级分布（全量 vs 活跃）──
df = con.execute("""
SELECT '全量' grp, round(stars,0) st, count(*) c FROM dim_business GROUP BY 2,1
UNION ALL SELECT '活跃(近12月有评论)', round(stars,0), count(*) FROM ads_business_metrics WHERE cnt_12m IS NOT NULL AND cnt_12m>0 GROUP BY 2
""").df()
fig, ax = plt.subplots(figsize=(8, 4.5))
piv = df.pivot(index="st", columns="grp", values="c").fillna(0)
x = np.arange(5)
ax.bar(x - 0.2, piv["全量"], 0.4, color=GRAY, label="全量商家 (150,346)")
ax.bar(x + 0.2, piv["活跃(近12月有评论)"], 0.4, color=C1, label="近12月活跃 (87,435)")
for i in range(5):
    ax.text(i - 0.2, piv["全量"].iloc[i] + 1000, f"{piv['全量'].iloc[i]:,}", ha="center", fontsize=8)
ax.set_xticks(x); ax.set_xticklabels(["1星", "2星", "3星", "4星", "5星"])
ax.set_ylabel("商家数"); ax.set_title("星级分布：4 星是市场及格线（38% 商家）")
ax.legend()
save(fig, "fig_y1_star_distribution.png")

# ── fig_y2: 星级随年龄下滑 ──
df2 = con.execute("""
SELECT CASE WHEN biz_age_days < 365 THEN '新店<1年' WHEN biz_age_days < 1461 THEN '1-4年'
            WHEN biz_age_days < 2922 THEN '4-8年' ELSE '8年+' END age_band,
       avg(stars) avg_stars, count(*) n
FROM dim_business GROUP BY 1 ORDER BY min(biz_age_days)
""").df()
fig, ax = plt.subplots(figsize=(8, 4.5))
bars = ax.bar(df2["age_band"], df2["avg_stars"], 0.55, color=C1)
for i, (v, n) in enumerate(zip(df2["avg_stars"], df2["n"])):
    ax.text(i, v + 0.03, f"{v:.2f}\n(n={n:,})", ha="center", fontsize=9)
ax.set_ylabel("平均星级"); ax.set_ylim(3.0, 4.3)
ax.set_title("星级随年龄下滑：新店 4.09 → 8年+老店 3.49\n（评论基数小导致好评偏差，看星级必须结合评论量）")
save(fig, "fig_y2_star_decline.png")

# ── fig_y3: 营业 vs 关闭 活跃率 ──
df3 = con.execute("""
SELECT b.is_open, avg(CASE WHEN a.cnt_12m>0 THEN 1 ELSE 0 END) active_ratio,
       avg(b.stars) avg_stars
FROM dim_business b JOIN ads_business_metrics a USING (business_id)
GROUP BY 1 ORDER BY 1
""").df()
fig, ax = plt.subplots(figsize=(7, 4.5))
labels = ["关闭商家 (30,648)", "营业商家 (119,698)"]
vals = df3["active_ratio"].values[::-1] * 100
bars = ax.bar(labels, vals, 0.5, color=[C3, C1])
for i, v in enumerate(vals):
    ax.text(i, v + 2, f"{v:.1f}%", ha="center", fontsize=12, fontweight="bold")
ax.set_ylabel("近12月有评论占比 (%)"); ax.set_ylim(0, 85)
ax.set_title("存续信号：活跃率差 10 倍（星级仅差 0.11）\n持续获得评论比绝对星级更能区分存续")
save(fig, "fig_y3_active_ratio.png")

# ── fig_y4: 品类画像 ──
df4 = con.execute("""
WITH cat AS (SELECT business_id, trim(cat) cat FROM (SELECT business_id, unnest(string_split(categories, ', ')) cat FROM dim_business))
SELECT c.cat, count(*) n, round(avg(b.stars),2) avg_stars, round(avg(b.review_count),1) avg_rc
FROM cat c JOIN dim_business b USING (business_id)
WHERE c.cat IN ('Restaurants','Shopping','Beauty & Spas','Home Services','Health & Medical','Nightlife','Automotive')
GROUP BY 1 ORDER BY n DESC
""").df()
fig, ax = plt.subplots(figsize=(9, 4.5))
bars = ax.barh(df4["cat"][::-1], df4["avg_rc"][::-1], 0.55, color=C2)
for i, (v, n) in enumerate(zip(df4["avg_rc"][::-1], df4["n"][::-1])):
    ax.text(v + 2, i, f"{v:.0f}条 (n={n:,})", va="center", fontsize=9)
ax.set_xlabel("平均评论量（客流代理）")
ax.set_title("品类画像：餐饮互动最活跃（87 条/家），夜生活评论量最大（121 条）")
save(fig, "fig_y4_category_profile.png")

# ── fig_y5: 评论趋势 + 疫情冲击 ──
df5 = con.execute("SELECT yr, count(*) c FROM fact_review WHERE yr BETWEEN 2008 AND 2021 GROUP BY 1 ORDER BY 1").df()
fig, ax = plt.subplots(figsize=(9, 4.5))
bars = ax.bar(df5["yr"].astype(str), df5["c"] / 10000, 0.6, color=[C3 if y == 2020 else C1 for y in df5["yr"]])
for i, (y, c) in enumerate(zip(df5["yr"], df5["c"])):
    if y in (2019, 2020, 2021):
        ax.text(i, c / 10000 + 1, f"{c/10000:.0f}万", ha="center", fontsize=9)
ax.set_ylabel("评论量（万）"); ax.set_xlabel("年份")
ax.set_title("评论量趋势：2020 疫情冲击 -39%（控制平台大盘后真实冲击 -43%）")
ax.annotate("2020 疫情", xy=(12, 55.5), xytext=(9.5, 75), fontsize=10, color=C3,
            arrowprops=dict(arrowstyle="->", color=C3))
save(fig, "fig_y5_trend_covid.png")

# ── fig_y6: 抱怨指数 ──
dims = ["等待时间", "外卖体验", "服务态度", "位置停车", "环境氛围", "卫生", "性价比", "价格", "餐品质量"]
idx = [7.2, 3.2, 2.6, 1.5, -4.6, -5.4, -0.3, -0.9, -9.8]
colors = [C3 if v > 0 else C2 for v in idx]
fig, ax = plt.subplots(figsize=(9, 4.5))
bars = ax.barh(dims, idx, 0.6, color=colors)
for i, v in enumerate(idx):
    ax.text(v + 0.15 if v > 0 else v - 0.5, i, f"{v:+.1f}pp", va="center", fontsize=9)
ax.axvline(0, color=GRAY, lw=1)
ax.set_xlabel("抱怨指数（低星提及率 − 高星提及率, pp）")
ax.set_title("评论话题拆解：差评抱怨等待/外卖/服务，餐品质量是加分项\n改进优先级 = 等待时间 > 外卖 > 服务")
save(fig, "fig_y6_complaint_index.png")

# ── fig_y7: 高潜识别特征重要性 + 画像 ──
fig, ax = plt.subplots(figsize=(8, 4.5))
feats = ["2020评论量", "2019-20增速", "营业状态", "商家年龄", "好评占比", "餐饮品类"]
imps = [0.371, 0.192, 0.106, 0.094, 0.023, 0.022]
ax.barh(feats[::-1], imps[::-1], 0.55, color=C1)
for i, v in enumerate(imps[::-1]):
    ax.text(v + 0.005, i, f"{v:.3f}", va="center", fontsize=9)
ax.set_xlabel("特征重要性 (gain)")
ax.set_title("高潜商家识别模型（2020→2021 增长预测，AUC 0.79）\n时间切分防泄漏：只用 2020 状态预测 2021 增长")
save(fig, "fig_y7_high_potential_model.png")

# ── fig_y8: 对照验证 ──
fig, ax = plt.subplots(figsize=(7, 4.5))
labels = ["预测 top20% 组", "其余 80% 组"]
vals = [1.59, 0.07]
bars = ax.bar(labels, vals, 0.5, color=[C1, GRAY])
for i, v in enumerate(vals):
    ax.text(i, v + 0.05, f"{v:.2f}", ha="center", fontsize=12, fontweight="bold")
ax.set_ylabel("2021 实际评论增速均值"); ax.set_ylim(0, 1.9)
ax.set_title("历史对照：高潜识别有效性验证（22.7 倍差异）")
save(fig, "fig_y8_validation.png")

con.close()
print("\n[Y5 图表完成] 8 张")

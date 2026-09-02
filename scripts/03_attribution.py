"""
Z2-P0：全量话题拆解（700 万条正式版，替代抽样版）
- 输出：全量抱怨指数 CSV + 修正 fig_y6
"""
import sys, io, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import duckdb
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHART = os.path.join(REPO, "charts")
C3, C2, GRAY = "#C44E52", "#55A868", "#94A3B8"

con = duckdb.connect("yelp.db", read_only=True)

DIMS = {
    "等待时间": ["wait", "line", "long time", "waiting", "queue"],
    "外卖体验": ["delivery", "takeout", "take out", "to go"],
    "服务态度": ["service", "staff", "rude", "friendly", "waiter", "waitress"],
    "位置停车": ["parking", "location"],
    "环境氛围": ["ambience", "atmosphere", "decor", "loud", "noise"],
    "卫生": ["clean", "dirty", "sanitary", "hygiene"],
    "性价比": ["value", "worth", "overpriced", "affordable"],
    "价格": ["price", "expensive", "cheap"],
    "餐品质量": ["food", "taste", "delicious", "bland", "fresh", "flavor"],
}

t0 = time.time()
parts = []
for i, (name, kws) in enumerate(DIMS.items()):
    cond = " OR ".join(["text LIKE '%" + k + "%'" for k in kws])
    parts.append(f"SUM(CASE WHEN stars<=2 AND ({cond}) THEN 1 ELSE 0 END) AS low_{i}")
    parts.append(f"SUM(CASE WHEN stars>=4 AND ({cond}) THEN 1 ELSE 0 END) AS high_{i}")
row = con.execute(
    "SELECT SUM(CASE WHEN stars<=2 THEN 1 ELSE 0 END) n_low, "
    "SUM(CASE WHEN stars>=4 THEN 1 ELSE 0 END) n_high, "
    + ", ".join(parts) + " FROM fact_review WHERE length(text) > 20"
).fetchone()
n_low, n_high = row[0], row[1]
print(f"全量: 低星 {n_low:,} / 高星 {n_high:,}（耗时 {time.time()-t0:.0f}s）")

import pandas as pd
rows = []
print(f"\n{'维度':<8}{'低星提及率':>12}{'高星提及率':>12}{'抱怨指数':>10}")
for i, name in enumerate(DIMS.keys()):
    low_r = row[2 + i * 2] / n_low * 100
    high_r = row[2 + i * 2 + 1] / n_high * 100
    idx = low_r - high_r
    rows.append({"维度": name, "低星提及率": round(low_r, 1), "高星提及率": round(high_r, 1),
                 "抱怨指数": round(idx, 1)})
    print(f"{name:<8}{low_r:>11.1f}%{high_r:>11.1f}%{idx:>+9.1f}pp")

res = pd.DataFrame(rows)
res.to_csv(os.path.join(REPO, "output_full_topics.csv"), index=False, encoding="utf-8-sig")
print("\n[已保存] output_full_topics.csv")

# 修正 fig_y6
dims = res["维度"].tolist()
idx = res["抱怨指数"].tolist()
colors = [C3 if v > 0 else C2 for v in idx]
fig, ax = plt.subplots(figsize=(9, 4.5))
bars = ax.barh(dims, idx, 0.6, color=colors)
for i, v in enumerate(idx):
    ax.text(v + 0.2 if v > 0 else v - 0.5, i, f"{v:+.1f}pp", va="center", fontsize=9)
ax.axvline(0, color=GRAY, lw=1)
ax.set_xlabel("抱怨指数（低星提及率 − 高星提及率, pp）")
ax.set_title("评论话题拆解（全量 700 万条）：等待时间是最强抱怨点（+13.0pp）\n餐品质量是加分项（−7.3pp）——先改流程而非菜品")
fig.savefig(f"{CHART}/fig_y6_complaint_index.png", dpi=150, bbox_inches="tight")
plt.close(fig)
print("[已更新] fig_y6_complaint_index.png（全量版）")
con.close()

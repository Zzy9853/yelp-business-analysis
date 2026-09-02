"""
Z6：P1 关闭预警 + 轨迹聚类 + 话题时间演化
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
from xgboost import XGBClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

con = duckdb.connect(os.path.join(REPO, "yelp.db"), read_only=True)

print("═══ 1. 关闭预警模型（识别将死商家）═══")
df = con.execute("""
WITH rev20 AS (SELECT business_id, count(*) rc20, avg(stars) stars20,
                      avg(CASE WHEN stars>=4 THEN 1.0 ELSE 0.0 END) ge4_20
               FROM fact_review WHERE yr=2020 GROUP BY 1),
     rev19 AS (SELECT business_id, count(*) rc19 FROM fact_review WHERE yr=2019 GROUP BY 1),
     cat AS (SELECT business_id, first(trim(cat)) main_cat FROM
             (SELECT business_id, unnest(string_split(categories, ', ')) cat FROM dim_business)
             WHERE trim(cat) IS NOT NULL GROUP BY 1)
SELECT b.business_id, b.is_open, b.biz_age_days, c.main_cat,
       COALESCE(r20.rc20,0) rc20, COALESCE(r20.stars20, b.stars) stars20, COALESCE(r20.ge4_20,0.5) ge4_20,
       COALESCE(r19.rc19,0) rc19
FROM dim_business b
LEFT JOIN cat c USING (business_id)
LEFT JOIN rev20 r20 USING (business_id)
LEFT JOIN rev19 r19 USING (business_id)
WHERE r20.rc20 IS NOT NULL AND r20.rc20 > 0
""").df()
df["target"] = (df["is_open"] == 0).astype(int)
print(f"样本: {len(df):,}（2020 有评论）| 关闭占比 {df['target'].mean()*100:.1f}%")
df["rc20_log"] = np.log1p(df["rc20"])
df["age_log"] = np.log1p(df["biz_age_days"])
df["growth_1920"] = ((df["rc20"] - df["rc19"]) / df["rc19"].clip(lower=1)).clip(-1, 5)
FEATS = ["stars20", "rc20_log", "ge4_20", "age_log", "growth_1920"]
for c in df["main_cat"].value_counts().head(10).index:
    df[f"cat_{c.replace(' ', '_')}"] = (df["main_cat"] == c).astype(int)
    FEATS.append(f"cat_{c.replace(' ', '_')}")
X, y = df[FEATS].fillna(0), df["target"]
aucs = []
for seed in range(10):
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=seed, stratify=y)
    m = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                      random_state=42, n_jobs=-1, verbosity=0, eval_metric="auc")
    m.fit(X_tr, y_tr)
    aucs.append(roc_auc_score(y_te, m.predict_proba(X_te)[:, 1]))
print(f"关闭预警 AUC={np.mean(aucs):.4f}±{np.std(aucs):.4f}（对照高潜识别 0.81）")
# 预警信号：关闭 vs 存活特征差异
print("\n预警信号（关闭 vs 存活，2020 状态中位数）:")
g, s = df[df["target"]==1], df[df["target"]==0]
for col in ["stars20", "rc20", "ge4_20", "growth_1920", "biz_age_days"]:
    print(f"  {col}: 关闭 {g[col].median():.2f} vs 存活 {s[col].median():.2f}")

print("\n═══ 2. 商家轨迹聚类（2018-2021 星级×评论量轨迹）═══")
traj = con.execute("""
WITH agg AS (SELECT business_id, yr, count(*) n, avg(stars) stars
             FROM fact_review WHERE yr BETWEEN 2018 AND 2021 GROUP BY 1,2)
SELECT business_id,
       sum(CASE WHEN yr=2018 THEN n END) n18, sum(CASE WHEN yr=2018 THEN stars END) s18,
       sum(CASE WHEN yr=2019 THEN n END) n19, sum(CASE WHEN yr=2019 THEN stars END) s19,
       sum(CASE WHEN yr=2020 THEN n END) n20, sum(CASE WHEN yr=2020 THEN stars END) s20,
       sum(CASE WHEN yr=2021 THEN n END) n21, sum(CASE WHEN yr=2021 THEN stars END) s21
FROM agg GROUP BY 1
HAVING count(*) = 4
""").df().fillna(0)
print(f"连续 4 年有评论的商家: {len(traj):,}")
for col in ["n18","n19","n20","n21"]:
    traj[f"{col}_log"] = np.log1p(traj[col])
# 轨迹特征：星级水平、规模、增速
traj["avg_stars"] = traj[["s18","s19","s20","s21"]].mean(axis=1)
traj["total_n"] = traj[["n18","n19","n20","n21"]].sum(axis=1)
traj["g18_19"] = (traj["n19"]-traj["n18"])/(traj["n18"].clip(lower=1))
traj["g19_20"] = (traj["n20"]-traj["n19"])/(traj["n19"].clip(lower=1))
traj["g20_21"] = (traj["n21"]-traj["n20"])/(traj["n20"].clip(lower=1))
traj[["g18_19","g19_20","g20_21"]] = traj[["g18_19","g19_20","g20_21"]].clip(-1, 3)
CL = ["avg_stars", "n18_log", "n19_log", "n20_log", "n21_log", "g18_19", "g19_20", "g20_21"]
sc = StandardScaler()
Xc = sc.fit_transform(traj[CL])
km = KMeans(n_clusters=5, random_state=42, n_init=10).fit(Xc)
traj["cluster"] = km.labels_
print("\n轨迹聚类画像（5 类）:")
prof = traj.groupby("cluster").agg(n=("business_id","count"),
                                   avg_stars=("avg_stars","mean"),
                                   total_n=("total_n","mean"),
                                   g18_19=("g18_19","mean"),
                                   g19_20=("g19_20","mean"),
                                   g20_21=("g20_21","mean")).round(3)
prof["占比%"] = (prof["n"]/len(traj)*100).round(1)
print(prof.to_string())

print("\n═══ 3. 话题时间演化（2019 vs 2021 抱怨话题）═══")
DIMS = {
    "等待": ["wait", "line", "long time", "waiting", "queue"],
    "外卖": ["delivery", "takeout", "take out", "to go"],
    "服务": ["service", "staff", "rude", "friendly"],
    "价格": ["price", "expensive", "cheap"],
    "卫生": ["clean", "dirty", "sanitary", "hygiene"],
    "餐品": ["food", "taste", "delicious", "bland"],
}
def topic_by_year(yr):
    parts = []
    for i, (name, kws) in enumerate(DIMS.items()):
        cond = " OR ".join(["text LIKE '%" + k + "%'" for k in kws])
        parts.append(f"SUM(CASE WHEN stars<=2 AND ({cond}) THEN 1 ELSE 0 END) AS d_{i}")
    row = con.execute(
        f"SELECT SUM(CASE WHEN stars<=2 THEN 1 ELSE 0 END) n_low, "
        f"{', '.join(parts)} FROM fact_review WHERE yr={yr} AND length(text) > 20"
    ).fetchone()
    return row
r19 = topic_by_year(2019)
r21 = topic_by_year(2021)
print(f"{'维度':<6}{'2019低星提及率':>14}{'2021低星提及率':>14}{'变化':>10}")
for i, name in enumerate(DIMS.keys()):
    a = r19[1+i]/r19[0]*100
    b = r21[1+i]/r21[0]*100
    print(f"{name:<6}{a:>13.1f}%{b:>13.1f}%{b-a:>+9.1f}pp")

con.close()
print("\n[Z6 完成]")

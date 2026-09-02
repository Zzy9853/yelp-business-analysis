"""
Y4：策略与评估
1. 商家改进优先级清单（抱怨指数 × 影响面 → 排序 + 动作建议 + 量化预估）
2. 平台高潜商家识别（2020 状态特征 → 2021 增长预测模型 + 画像）
3. 对照验证设计（历史对照 + RDD/AB 设计）
"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd
import duckdb
from xgboost import XGBClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import roc_auc_score

import os
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
con = duckdb.connect(os.path.join(REPO, "yelp.db"), read_only=True)

print("═══ Y4-1 改进优先级清单 ═══")
# 影响面：低星评论中各维度绝对提及率（抱怨有多普遍）
rows = con.execute("""
SELECT count(*) FILTER (WHERE text LIKE '%wait%' OR text LIKE '%line%' OR text LIKE '%long time%') w,
       count(*) FILTER (WHERE text LIKE '%delivery%' OR text LIKE '%takeout%' OR text LIKE '%to go%') d,
       count(*) FILTER (WHERE text LIKE '%service%' OR text LIKE '%staff%') s,
       count(*) FILTER (WHERE text LIKE '%parking%' OR text LIKE '%location%') p,
       count(*) FILTER (WHERE text LIKE '%food%' OR text LIKE '%taste%') f,
       count(*) FILTER (WHERE stars <= 2) n_low
FROM fact_review WHERE stars <= 2 AND length(text) > 20
""").fetchone()
n_low = rows[5]
print(f"低星评论总数: {n_low:,}")
dims = [("等待时间", rows[0], 7.2), ("外卖体验", rows[1], 3.2), ("服务态度", rows[2], 2.6),
        ("位置停车", rows[3], 1.5), ("餐品质量", rows[4], -9.8)]
print(f"{'维度':<8}{'低星提及率':>12}{'抱怨指数':>10}{'综合得分':>10}")
for name, cnt, idx in dims:
    rate = cnt / n_low * 100
    score = rate * max(idx, 0) / 100  # 影响面 × 抱怨强度
    print(f"{name:<8}{rate:>11.1f}%{idx:>+9.1f}pp{score:>10.2f}")

print("\n═══ Y4-2 高潜商家识别 ═══")
# 构建特征：2020 状态 → 2021 增长
df = con.execute("""
WITH cat AS (SELECT business_id, first(trim(cat)) main_cat FROM
             (SELECT business_id, unnest(string_split(categories, ', ')) cat FROM dim_business)
             WHERE trim(cat) IS NOT NULL GROUP BY 1),
rev20 AS (SELECT business_id, count(*) rc20, avg(stars) stars20,
                 avg(CASE WHEN stars>=4 THEN 1.0 ELSE 0.0 END) ge4_20
          FROM fact_review WHERE yr=2020 GROUP BY 1),
rev19 AS (SELECT business_id, count(*) rc19 FROM fact_review WHERE yr=2019 GROUP BY 1),
rev21 AS (SELECT business_id, count(*) rc21 FROM fact_review WHERE yr=2021 GROUP BY 1)
SELECT b.business_id, b.is_open, b.stars, b.biz_age_days,
       c.main_cat, b.city,
       COALESCE(r20.rc20,0) rc20, COALESCE(r20.stars20, b.stars) stars20, COALESCE(r20.ge4_20,0.5) ge4_20,
       COALESCE(r19.rc19,0) rc19, COALESCE(r21.rc21,0) rc21
FROM dim_business b
LEFT JOIN cat c USING (business_id)
LEFT JOIN rev20 r20 USING (business_id)
LEFT JOIN rev19 r19 USING (business_id)
LEFT JOIN rev21 r21 USING (business_id)
WHERE r21.rc21 IS NOT NULL AND r21.rc21 > 0 AND r20.rc20 IS NOT NULL
""").df()
print(f"样本: {len(df):,} 家（2020 与 2021 都有评论）")

df["growth"] = (df["rc21"] - df["rc20"]) / df["rc20"].clip(lower=1)
df["target"] = (df["growth"] > 0.5).astype(int)  # 2021 高速增长（+50%）
print(f"目标分布: 高速增长 {df['target'].mean()*100:.1f}% ({df['target'].sum():,})")

# 特征工程
df["rc20_log"] = np.log1p(df["rc20"])
df["age_log"] = np.log1p(df["biz_age_days"])
df["growth_1920"] = (df["rc20"] - df["rc19"]) / df["rc19"].clip(lower=1)
df["growth_1920"] = df["growth_1920"].clip(-1, 5)

FEATS = ["stars20", "rc20_log", "ge4_20", "age_log", "growth_1920", "is_open"]
# 品类 one-hot（主要品类）
top_cats = df["main_cat"].value_counts().head(10).index
for c in top_cats:
    df[f"cat_{c.replace(' ', '_')}"] = (df["main_cat"] == c).astype(int)
FEATS += [f"cat_{c.replace(' ', '_')}" for c in top_cats]

X = df[FEATS].fillna(0)
y = df["target"]
X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

# XGBoost
m = XGBClassifier(n_estimators=300, max_depth=4, learning_rate=0.05, subsample=0.8,
                  random_state=42, n_jobs=-1, verbosity=0, eval_metric="auc")
m.fit(X_tr, y_tr)
auc = roc_auc_score(y_te, m.predict_proba(X_te)[:, 1])
print(f"XGBoost AUC={auc:.4f} (特征 {len(FEATS)})")

# 逻辑回归（可解释）
lr = LogisticRegression(max_iter=1000, C=0.1)
lr.fit(X_tr, y_tr)
auc_lr = roc_auc_score(y_te, lr.predict_proba(X_te)[:, 1])
print(f"LogReg AUC={auc_lr:.4f}")
coef = pd.Series(lr.coef_[0], index=FEATS).sort_values(ascending=False)
print("\n逻辑回归系数（增长型画像，Top8）:")
for k, v in coef.head(8).items():
    print(f"  {k}: {v:+.3f}")

# 画像对比
print("\n增长型 vs 非增长型画像:")
g = df[df["target"] == 1]
ng = df[df["target"] == 0]
for col in ["stars20", "rc20", "ge4_20", "biz_age_days", "growth_1920", "is_open"]:
    print(f"  {col}: 增长型 {g[col].median():.2f} vs 非增长 {ng[col].median():.2f}")

# 决策规则（XGBoost 特征重要性）
imp = pd.Series(m.feature_importances_, index=FEATS).sort_values(ascending=False)
print("\nXGBoost 特征重要性 Top8:")
for k, v in imp.head(8).items():
    print(f"  {k}: {v:.3f}")

print("\n═══ Y4-3 对照验证 ═══")
# 历史对照：2020 高潜预测（模型打分 top20%）vs 其余，2021 实际增速对比
proba_all = m.predict_proba(X)[:, 1]
df["prob"] = proba_all
top20 = df["prob"].rank(pct=True) >= 0.8
print(f"预测 top20% 组: 2021 实际增速中位 {df[top20]['growth'].median():.2f} ({df[top20]['growth'].mean():.2f})")
print(f"其余组:        2021 实际增速中位 {df[~top20]['growth'].median():.2f} ({df[~top20]['growth'].mean():.2f})")
print(f"差异倍数: {df[top20]['growth'].median() / max(df[~top20]['growth'].median(), 0.01):.2f}x")

con.close()
print("\n[Y4 完成]")

# Yelp Business Analytics — Local Business Growth Diagnosis

本地生活商家线上经营诊断与增长策略分析，基于 Yelp Open Dataset（15 万商家 / 700 万评论 / 2005-2022 / 11 个都市区）。

## 项目概述

**业务问题**：本地生活平台的商家靠星级和评论获客，但商家缺乏系统性经营诊断——星级低是服务差还是环境差？评论少是曝光不足还是没人写？平台扶持商家也缺乏数据依据。

**项目目标**：用数据回答三个问题——什么样的商家能做好、该优先改什么、哪些商家值得平台重点扶持。

## 核心结论

| 发现 | 结果 |
|---|---|
| 星级随年龄下滑 | 新店 4.09 星 → 8 年+老店 3.49 星（评论基数小导致好评偏差） |
| 存续信号 | 营业商家近一年有评论占比 71.2% vs 关闭商家 7.0% |
| 差评抱怨点 | 等待时间（抱怨指数 +13.0pp）> 外卖体验 > 服务；餐品质量是加分项（−10.9pp） |
| 2020 疫情冲击 | 控制平台大盘（CAGR 7.1% 外推）后真实冲击 −43%；居家服务恢复 85% vs 美容美发 61% |
| 高潜商家识别 | 2020 状态预测 2021 爆发型增长（时间切分防泄漏），AUC 0.81（+属性 0.82） |
| 对照验证 | 预测 top20% 商家 2021 实际增速 1.59 vs 其余 0.07（22.7 倍差异） |

## 仓库结构

```
yelp-analysis/
├── README.md
├── requirements.txt
├── .gitignore
├── scripts/
│   ├── 01_build_warehouse.py    # 建仓：JSON → DuckDB（ODS→DWD→ADS）
│   ├── 02_market_explore.py     # 市场画像与指标体系
│   ├── 03_attribution.py        # 归因：评论话题拆解 / 驱动因子 / 疫情异动
│   ├── 04_strategy.py           # 策略：改进优先级 / 高潜识别模型 / 对照验证
│   └── 05_generate_charts.py    # 图表生成
├── charts/                      # 8 张分析图表
└── docs/
    └── data_dictionary.md       # 数据字典与口径说明
```

## 复现步骤

1. 下载 Yelp Open Dataset（v2022）：https://business.yelp.com/data/resources/open-dataset/ （或 Kaggle 镜像）
   解压后得到 `yelp_academic_dataset_*.json` 5 个文件
2. 安装依赖：`pip install -r requirements.txt`
3. 修改 `scripts/01_build_warehouse.py` 中的 `SRC` 路径为你的 JSON 目录
4. 依次运行：
   ```bash
   python scripts/01_build_warehouse.py   # 建仓 → yelp.db
   python scripts/02_market_explore.py    # 市场画像
   python scripts/03_attribution.py       # 归因分析
   python scripts/04_strategy.py          # 策略与验证
   python scripts/05_generate_charts.py   # 图表 → charts/
   ```

## 技术栈

- **DuckDB**：本地数仓（ODS→DWD→ADS 三层），原始 JSON 直读，7 亿行级数据本地分析
- **Python**：pandas / scikit-learn / XGBoost
- **文本分析**：词典法话题拆解（可解释维度，支撑业务结论）

## 数据说明

- 数据为 Yelp 官方公开数据集（真实商业数据，教育用途）
- 仓库不含原始数据与数据库文件（约 13GB），由脚本从 JSON 重建
- 数据集局限：无交易金额，评论量/星级作为客流与口碑的代理指标（代理合理性已在分析中论证）

## License

数据遵循 Yelp Dataset Terms of Use（教育用途）；代码 MIT。

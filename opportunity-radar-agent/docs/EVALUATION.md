# 真实数据标注与模型对比

## 当前状态

2026-09-26，用户已在 `evaluation/private/review-2026-09-26/` 完成 9 篇文章和 1 组画像（5 个候选）的首次人工确认，状态均为 labeled。标签由 AI 起草、人类确认，尚无二次 reviewed 或第二位独立盲标者。原始 `evaluation/private/extraction.jsonl` 和 `ranking.jsonl` 保留未标注状态；本批评测请使用 review 目录文件。所有正文、画像和报告均被 Git 忽略。

本批修复前抽取 F1 0.8889、字段匹配 13/20；据此优化后，同批 F1 1.0、字段 20/20。这是开发集回归成绩，独立测试仍待扩充。排序只有一个相关候选，NDCG@3 1.0、Precision@3 0.3333；此候选集的 Precision@3 上限就是 1/3，不能解读为推荐准确率 100%。

仓库中的 `cases.json`（抽取）和 `ranking_cases.jsonl`（排序）是虚构回归用例，只用于防止代码改坏，不能称为真实效果。不能拿模型自身已经抽取的 5 个机会当作真值；本批人工抽取确认的是 4 个机会。

## 1. 从本地数据库建立队列

在主项目目录执行：

```bash
python -m evaluation.real_data export-extraction
python -m evaluation.real_data export-ranking
```

重复导出会按正文哈希或候选集身份保留已有人工标签。模型现有结果保存在 `model_suggestions` / `model_order`，数据指纹和指标会忽略它们，人工标注不会被自动覆盖。推荐导出省略画像姓名。

默认最多导出 200 篇，也可以指定：

```bash
python -m evaluation.real_data export-extraction --limit 100
python -m evaluation.real_data export-ranking --profile-id 1 --as-of 2026-09-09
```

## 2. 使用本地标注工作台

```bash
sh run_annotation.sh
```

Windows 使用 `run_annotation.ps1`。打开 http://127.0.0.1:8502 。标注工具只允许写入本项目的 `evaluation/private/`，并采用临时文件 + 原子替换，写入中断不会留下半个 JSONL。

抽取标注：

- 先独立判断文章是否发布了可报名、申请或参与的具体机会；即使已经截止也仍算机会，回顾、经验文章或取消通知不算。
- 一篇文章可标多个机会；每项提供 `name`、`category`、用于匹配的 `match_keywords`。
- `fields` 只填你愿意严格核对的字段；明确缺失可以写空字符串。
- 机会编辑框默认空白，模型建议仅在独立折叠区展示，不会预填到人工标签。切换记录时，判断、备注和复查状态各自隔离。

推荐标注：

- 先看画像，以 `0=无关、1=弱相关、2=相关、3=高度相关` 独立标每个候选。
- 每个候选默认“尚未判断”；必须逐项明确选择，包括明确判断为 0 分，才可以保存。未判断不会自动变成负例。
- 评测日期固定在 `as_of`，避免截止日期经过后导致回归结果漂移。
- 建议第一次标注不要先看模型排序；完成后再展开对照，减少锚定偏差。
- `reviewed` 应表示至少进行过第二次检查；若条件允许，应由第二位标注者独立标注并计算一致性。

人工机会 JSON 示例（请替换为原文中你独立确认的信息）：

```json
[
  {
    "name": "原文机会名称",
    "category": "实习",
    "match_keywords": ["机会名称中的区分词"],
    "fields": {"deadline": "", "location": "", "link": "", "organizer": ""}
  }
]
```

先完成现有队列以验证流程，再扩充到不同来源、负例、一文多机会和不同画像。扩充时保留独立测试集，避免一边修改规则一边用同一批样本宣称泛化效果。当前排序评测不包含用户行为和成长记忆样本，不能用合成排序成绩说明长期记忆有效；相关新测试只验证上下文连接、用户隔离和反馈降权逻辑。

检查进度：

```bash
python -m evaluation.real_data validate evaluation/private/extraction.jsonl
python -m evaluation.real_data validate evaluation/private/extraction.jsonl --require-complete
python -m evaluation.real_data validate evaluation/private/ranking.jsonl --require-complete
```

## 3. 离线评估本地规则

这两条命令强制使用无法联网的 gateway，不读取 DeepSeek Key：

```bash
python -m evaluation.real_data evaluate extraction evaluation/private/extraction.jsonl --mode rules --output evaluation/private/reports/extraction-rules.json
python -m evaluation.real_data evaluate ranking evaluation/private/ranking.jsonl --mode rules --k 3 --output evaluation/private/reports/ranking-rules.json
```

抽取指标包括：文章是否含机会、机会级 Precision / Recall / F1、多机会一对一匹配、总体和分字段精确匹配率，以及只包含案例 ID 的失败清单。

排序指标包括：NDCG@K（高相关结果是否靠前）、MRR（第一个相关结果位置）、Hit Rate@K、Precision@K 和成对顺序准确率。排序在隔离的内存 SQLite 中调用正式 `MatchingService`，不会修改个人数据库。

每份结果带数据指纹。基线也绑定指纹，数据集发生变化时不会悄悄拿旧门槛比较。CI 当前用三组虚构画像检查排序基线：

```bash
python -m evaluation.real_data evaluate ranking evaluation/ranking_cases.jsonl --mode rules --k 3 --baseline evaluation/ranking_baseline.json
```

## 4. 以后对比 DeepSeek

只有当你拥有自己的 Key、理解正文会发送给第三方且接受可能产生费用时，才执行：

```bash
python -m evaluation.real_data compare extraction evaluation/private/extraction.jsonl --allow-network --output evaluation/private/reports/extraction-compare.json
python -m evaluation.real_data compare ranking evaluation/private/ranking.jsonl --allow-network --k 3 --output evaluation/private/reports/ranking-compare.json
```

程序要求同时满足三个条件：选择 DeepSeek/compare、显式写 `--allow-network`、本地配置有效 Key。少任一项都会在发送正文前停止。不要在 CI 中配置个人 Key，也不要提交 `evaluation/private/`。

## 解释指标时的边界

- 9 篇文章和 1 组画像远不足以说明泛化能力；至少扩展到不同来源、不同机会类型、负例和一文多机会。
- 同一个人完成标注与规则设计容易产生确认偏差；推荐标签也具有主观性。
- 公开结果时报告样本量、类别分布、标注规则、数据指纹、模型版本和日期，不只展示一个最高分。
- 联系方式、个人画像和受版权保护的全文默认只保存在本机；若要发布数据集，需要重新确认授权并做脱敏/许可审查。

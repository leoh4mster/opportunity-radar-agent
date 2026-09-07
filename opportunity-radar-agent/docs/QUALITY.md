# 导入可靠性与抽取评测

## 浏览器导入

左侧「导入文章」支持上传 UTF-8 JSON / TXT / Markdown（含 UTF-8 BOM）。
单次文件上限 2 MiB、500 篇。上传文件以字节流解析，不使用客户端文件名写入服务器文件系统。
成功后显示新增数和重复数；再点击「处理未抽取文章」进行抽取。

JSON 支持单对象、数组或 `{"articles": [...]}`：

```json
{
  "articles": [
    {
      "title": "数据分析实习招募",
      "content": "欢迎申请。\n地点：上海\n报名截止：2030-12-31",
      "source": "个人整理",
      "url": "https://example.com/apply"
    }
  ]
}
```

API：`POST /articles/upload`，multipart 字段为 `file`。
响应沿用 `imported`、`skipped_duplicates`、`article_ids`。
非法格式、正文为空、编码错误返回 400；文件超过上限返回 413。
已有本地路径导入 API 保留，使用同一解析器与校验规则。

## 导入事务与身份

- 完整校验一批文章后才开始写入；存储失败时回滚整批。
- 正文去除空白后计算 SHA-256。同一批、重复上传、路径导入和采集入口使用相同规则。
- 采集接口仍接收 `content_hash` 以兼容旧客户端，但正文身份只由服务端计算。错误哈希不会绕过去重。
- 采集入库与机会抽取在同一事务，抽取失败不留下孤立的新文章。

当前保证是顺序调用的幂等性：去重仍扫描已有正文，不承诺并发唯一性；删除所有空白也可能合并少量语义不同的英文内容。下一阶段需通过数据库迁移增加持久化哈希和唯一约束，并定义旧重复数据的保留策略。现有数据库没有在本轮重建或删除。

## 可复现评测

```bash
cd opportunity-radar-agent
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m evaluation.run
python -m evaluation.run --check
```

`evaluation/cases.json` 包含 15 条手写合成用例，10 条机会、5 条非机会。
覆盖实习、竞赛、实验室、科研、讲座、夏令营、奖学金、课程、交流，包含取消通知、活动回顾和经验文章。
每条最多标注一个机会；没有覆盖一文多机会、真实用户偏好排序或大规模中文语料。

评测强制注入离线 gateway，即使本机配置了真实 API Key 也不会调用模型，不产生 API 费用。
`--check` 对照 `baseline.json` 的最低指标，下降时返回非零退出码；CI 自动执行。

| 指标 | 初始结果 | 定义 |
| --- | --- | --- |
| Precision | 0.7692 | 正确识别数 / 预测机会数，10 / 13 |
| Recall | 1.0000 | 正确识别数 / 标注机会数，10 / 10 |
| F1 | 0.8696 | Precision 与 Recall 的调和平均 |
| 字段精确匹配率 | 0.9750 | 正例中类别、日期、地点、链接匹配字段数，39 / 40 |

字段匹配率含预期空值，不计负例上的多余字段；它不能代替 Precision。
报告输出失败用例 ID 和失败字段。当前失败为：`natural_date` 漏日期，`retrospective`、`cancelled`、`guidance` 误报机会。
这些数值只描述这份小型合成回归集，不能写成真实业务准确率，也不是 DeepSeek 的模型效果。
后续应收集独立标注的真实文章与保留测试集，再做规则与模型对比。

## API 回归测试

API 测试使用内存 SQLite 并覆盖依赖，不启动生产数据库 lifespan；显式禁止外部模型调用。
覆盖错误哈希去重、跨入口幂等、批次校验失败、存储异常回滚、抽取异常回滚、大小和数量边界、UTF-8 BOM。

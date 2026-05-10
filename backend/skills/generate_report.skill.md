# Skill: generate_report

## 适用场景
汇总整合统计数据，生成 Markdown 格式的整合报告。

## 输入 Schema
无需输入，从数据库实时统计。

## 输出 Schema
```json
{
  "textbooks": "dict",
  "chapters": "dict",
  "knowledge_graph": "dict",
  "decisions": "dict",
  "rag": "dict"
}
```

## 报告结构
1. 整合概览
2. 教材清单
3. 知识图谱统计
4. 整合决策摘要
5. 核心整合案例（炎症/结核/免疫）
6. 教学完整性说明
7. RAG 问答能力

## 质量检查
- 所有数值来自真实数据库统计
- 待系统统计的字段明确标注（压缩比等需整合完成后填充）

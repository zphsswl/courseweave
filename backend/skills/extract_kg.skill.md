# Skill: extract_kg

## 适用场景
从教材章节中抽取知识点和关系，构建单本教材知识图谱。

## 输入 Schema
```json
{
  "textbook": "string (教材名称)",
  "chapter": "string (章节名称)",
  "content": "string (章节原文，截断到8000字)",
  "max_nodes": "int (每章最多节点数，默认30)"
}
```

## 输出 Schema
```json
{
  "nodes": [
    {
      "name": "string (知识点名称)",
      "aliases": ["string"],
      "definition": "string",
      "category": "核心概念|结构|机制|疾病|病原体|表现|诊断|治疗",
      "importance": "int (1-5)",
      "source_quote": "string (原文依据)"
    }
  ],
  "edges": [
    {
      "source": "string (来源节点)",
      "target": "string (目标节点)",
      "relation_type": "prerequisite|parallel|contains|applies_to",
      "description": "string",
      "confidence": "float"
    }
  ]
}
```

## Prompt 模板
见 `backend/prompts/kg_extraction.txt`

## 失败重试
- JSON 解析失败 → JSON repair 正则修复
- LLM 调用失败 → 规则兜底抽取关键词
- 重试策略：最多重试 2 次

## 质量检查
- nodes 数量 > 0 且 <= max_nodes
- 每个 node 有 name 和 source_quote
- edges 至少包含 2 种关系类型

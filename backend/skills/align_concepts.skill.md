# Skill: align_concepts

## 适用场景
跨教材识别重复、互补、缺失的知识点，生成候选合并决策。

## 输入 Schema
```json
{
  "nodes": ["KnowledgeNode 列表"]
}
```

## 输出 Schema
```json
{
  "decisions": [
    {
      "action": "merge|keep|remove",
      "affected_nodes": ["node_id_1", "node_id_2"],
      "result_name": "string",
      "reason": "string",
      "confidence": "float",
      "overlap_type": "overlap|complement|missing"
    }
  ]
}
```

## Prompt 模板
见 `backend/prompts/concept_alignment.txt`

## 两阶段对齐
1. Embedding 召回候选：相似度 > 0.82 进入候选
2. LLM 复核：0.82-0.92 区间调用 LLM 判断

## 失败重试
- embedding 模型不可用 → 哈希兜底
- LLM 复核失败 → 阈值判断 (0.87 以上默认 merge)

## 质量检查
- 同名概念必须至少进入候选
- 上下位概念不能被标记为 merge

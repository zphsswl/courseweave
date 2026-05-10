# Skill: compress_essence

## 适用场景
基于重要度评分和图谱依赖，将知识库压缩到原始正文的 30% 以内。

## 输入 Schema
```json
{
  "nodes": ["所有知识点"],
  "decisions": ["所有整合决策"],
  "target_ratio": 0.30
}
```

## 输出 Schema
```json
{
  "original_chars": "int",
  "essence_chars": "int",
  "compression_ratio": "float",
  "compression_pct": "string",
  "original_nodes": "int",
  "essence_nodes": "int",
  "within_target": "bool"
}
```

## 评分公式
score = 0.35 × 出现教材数 + 0.25 × LLM重要度 + 0.20 × 图谱中心性 + 0.10 × 是否前置依赖 + 0.10 × 教师保留标记

## 保护机制
1. 前置依赖保护
2. 章节覆盖保护
3. 教学链路完整性检查
4. 教师手动保留永不删除

## 质量检查
- 压缩比 ≤ 30%
- 每本教材至少保留 3 个节点
- 前置依赖关系不断裂

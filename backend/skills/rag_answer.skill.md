# Skill: rag_answer

## 适用场景
基于教材原文 chunk 和精华知识库，回答医学问题并带来源引用。

## 输入 Schema
```json
{
  "question": "string (用户问题)",
  "top_k": "int (检索数量，默认8)",
  "final_k": "int (注入LLM数量，默认5)"
}
```

## 输出 Schema
```json
{
  "answer": "string (带引用的回答)",
  "citations": [
    {
      "textbook": "string",
      "chapter": "string",
      "page": "int",
      "relevance_score": "float"
    }
  ],
  "source_chunks": ["string (原文片段)"]
}
```

## Prompt 模板
见 `backend/prompts/rag_answer.txt`

## 检索策略
1. 向量检索 top-8
2. 取 top-5 注入 LLM
3. 强制引用格式：[教材, 章节, 页码]

## 防幻觉
- 仅基于 chunk 回答
- 无依据必须拒答
- 不编造页码/章节

## 质量检查
- 回答必须带至少 1 条引用
- 无依据时返回拒答固定话术

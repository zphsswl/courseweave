# Skill: teacher_patch

## 适用场景
接收教师自然语言反馈，转换为对整合决策的修改操作。

## 输入 Schema
```json
{
  "message": "string (教师自然语言输入)",
  "decisions": ["相关决策列表"]
}
```

## 输出 Schema
```json
{
  "response": "string (系统回复)",
  "operation": "keep|merge|split|remove|explain",
  "parsed": "dict (解析结果)"
}
```

## 可用操作
- keep: 保留知识点
- merge: 合并知识点
- split: 拆分已合并知识点
- remove: 删除冗余知识点
- explain: 解释决策原因

## Prompt 模板
见 `backend/prompts/teacher_dialogue.txt`

## 失败重试
- LLM 解析失败 → 规则关键词匹配兜底
- 决策 ID 不存在 → 提示用户指定具体决策

## 质量检查
- 不在决策库中的知识不能随意修改
- 信息不足时返回 need_clarification
- 每次修改后重新计算压缩比

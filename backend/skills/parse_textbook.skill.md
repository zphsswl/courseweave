# Skill: parse_textbook

## 适用场景
解析上传的医学教材文件（PDF/MD/TXT），识别章节结构。

## 输入 Schema
```json
{
  "file_path": "string (教材文件路径)",
  "textbook_id": "string (教材唯一ID)"
}
```

## 输出 Schema
```json
{
  "textbook_id": "string",
  "total_pages": "int",
  "total_chars": "int",
  "chapters": [
    {
      "chapter_id": "string",
      "title": "string",
      "page_start": "int",
      "page_end": "int",
      "content": "string",
      "char_count": "int"
    }
  ]
}
```

## Prompt 模板
无需 LLM，纯工程解析。

## 失败重试
- PDF 解析失败 → 切换 pypdf 兜底
- 章节识别失败 → 按 15 页生成伪章节
- 单页解析失败 → 记录错误，继续下一页

## 质量检查
- 章节数 > 0
- 总字符数 > 0
- 每章字符数 > 50

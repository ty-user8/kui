# 用户消息模板 · ask.user.template.v1

占位符固定为 `{query}` 与 `{context}`，由 `src/generate/ask.py` 填充；不要在此文件里改动占位符名称。

```text
<question>
{query}
</question>

<context>
{context}
</context>

请依据 <context> 中的条文回答 <question>，每个结论后用 [chunk_id] 标注来源。
```

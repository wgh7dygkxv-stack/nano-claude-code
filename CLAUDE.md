## 环境
- Python >= 3.10 | openai SDK | rich（仅允许这三个第三方库）
- Base URL: https://openrouter.ai/api/v1
- API Key: 环境变量 `OPENROUTER_API_KEY`
- 模型: anthropic/claude-3.5-sonnet

## 架构
- 每步生成 `agents/s{01-08}_xxx.py`，公共函数提取到 `agents/utils.py`
- 工具路由: dict dispatch (`TOOL_HANDLERS`)，Schema 与 Handler 严格分离
- 工具执行必须 try/except，错误作为 tool_result 返回

## 工作流
- 编写代码后必须运行验证，遇报错自行修复
- 使用中文回复
# Nano Claude Code

一个基于 Claude 3.5 的渐进式 AI Agent 实现教程。从零开始构建功能完整的代理系统，逐步演示工具调用、系统提示、任务管理、Hook 扩展和子代理委派等核心特性。

## 快速开始

### 环境要求

- **Python**: >= 3.10
- **依赖库**: openai、rich（仅允许这三个第三方库）
- **API**: OpenRouter (https://openrouter.ai/api/v1)
- **模型**: anthropic/claude-3.5-sonnet

### 安装

```bash
pip install openai rich
```

### 配置

设置 API 密钥环境变量：

```bash
export OPENROUTER_API_KEY="your-api-key"
```

## 项目结构

### 核心实现 (`agents/`)

按复杂度递增的 8 个步骤：

| 文件 | 功能 | 关键特性 |
|------|------|--------|
| **s01_agent_loop.py** | 基础工具调用 | LLM 循环、工具分发、消息管理 |
| **s02_system_prompt.py** | 系统提示管理 | 多提示支持、提示词工程 |
| **s03_compact.py** | 消息压缩 | 历史记录优化、上下文管理 |
| **s04_todo.py** | 任务列表 | 任务跟踪、状态管理 |
| **s05_skill.py** | 技能系统 | 动态能力扩展、/help 命令 |
| **s06_mcp.py** | MCP 服务器 | 外部工具集成、天气服务示例 |
| **s07_hook.py** | Hook 系统 | Pre/Post 钩子、命令审计 |
| **s08_subagent.py** | 子代理系统 | 任务委派、独立上下文、递归防护 |

支持文件：
- **utils.py** - 通用工具函数
- **test_utils.py** - 单元测试

### 扩展系统

#### Hooks (`hooks/`)

- `auto_lint.py` - 自动代码格式化 (Post Hook)
- `dangerous_cmd_guard.py` - 危险命令防护 (Pre Hook)

#### MCP 服务器 (`mcp_servers/`)

- `weather_server.py` - 天气查询服务示例

## 核心特性

### 1. 工具系统

```python
# Schema 定义 + Handler 分离
TOOLS_SCHEMA = [
    {"type": "function", "function": {"name": "bash", ...}},
]

TOOL_HANDLERS = {
    "bash": lambda args: handle_bash(**args),
}
```

- 严格的 Schema 与 Handler 分离
- 所有工具执行包含 try/except 错误处理
- 工具结果直接作为 LLM tool_result 返回

### 2. Hook 扩展机制

支持 Pre Hook（执行前拦截）和 Post Hook（执行后触发）：

```json
{
  "hooks": {
    "bash": {
      "pre": [{"command": "python3", "args": ["hooks/dangerous_cmd_guard.py"]}]
    }
  }
}
```

### 3. 子代理系统 (s08)

主代理可通过 `dispatch_subagent` 工具委派任务给子代理：

- ✅ 独立上下文（子代理有自己的 messages）
- ✅ 受限工具集（仅 bash + read_file）
- ✅ 递归防护（结构性阻止无限递归）
- ✅ 自动超时防护（max_iterations = 20）

```python
# 主代理调用
response = agent.dispatch_subagent("调研 agents/ 目录结构")

# 子代理独立执行，返回结果
```

## 使用示例

### 最小化版本

```bash
python agents/s01_agent_loop.py
```

```
你: 查看当前目录
助手: [执行 bash 工具获取目录列表]
```

### 完整版本（推荐）

```bash
python agents/s08_subagent.py
```

特性：
- Hook 系统自动加载（.hooks.json）
- 支持任务管理 (/compact)
- 子代理自动创建

### 与子代理交互

```
你: 派遣子代理帮我调研 agents/ 目录的结构
助手: 我会为你委派一个子代理...
  [子代理] 启动，任务: 派遣子代理帮我调研 agents/ 目录的结构
  [工具] bash({'command': 'find agents -type f -name "*.py"'})
  [结果] s01_agent_loop.py s02_system_prompt.py ...
  [子代理] 完成
助手: [子代理结果摘要]
```

## 架构特点

### 渐进式设计

每个版本都是前一个版本的**超集**，新增特性而不破坏既有功能：

```
s01 (基础)
  ↓
s02 (+ 系统提示)
  ↓
s03 (+ 消息压缩)
  ↓
s04 (+ 任务管理)
  ↓
s05 (+ 技能系统)
  ↓
s06 (+ MCP 服务器)
  ↓
s07 (+ Hook 系统)
  ↓
s08 (+ 子代理)
```

### 模块化

- **工具层**: TOOLS_SCHEMA + TOOL_HANDLERS 解耦
- **执行层**: run_agent_loop() 通用循环
- **扩展层**: Hook、Skill、MCP、Subagent

## 关键代码片段

### 工具调用循环

```python
def run_agent_loop(messages, tools_schema, tool_handlers, hooks_config=None):
    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools_schema,
        )

        if response.choices[0].finish_reason == "tool_calls":
            for tc in response.choices[0].message.tool_calls:
                # 执行工具、处理 Hook、添加结果
        else:
            return response.choices[0].message.content
```

### Hook 执行

```python
def run_turn(messages, tools_schema, hooks_config):
    allowed = run_pre_hooks(hooks_config, tool_name, args)
    if allowed:
        result = tool_handlers[tool_name](args)
        run_post_hooks(hooks_config, tool_name, args, result)
    return result
```

### 子代理委派

```python
def handle_dispatch_subagent(task_description: str) -> str:
    sub_messages = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "user", "content": task_description},
    ]
    # 子代理使用受限工具集独立执行
    return run_agent_loop(
        sub_messages,
        SUBAGENT_TOOLS_SCHEMA,  # 仅 [bash, read_file]
        SUBAGENT_HANDLERS,
        hooks_config=None,  # 不使用 Hook
        max_iterations=20,  # 安全阀
    )
```

## 配置文件

### CLAUDE.md

项目配置文件，定义：
- 环境依赖
- 架构约束
- API 配置

### .hooks.json

Hook 系统配置（自动生成）：

```json
{
  "hooks": {
    "bash": {
      "pre": [{"command": "python3", "args": ["hooks/dangerous_cmd_guard.py"]}]
    },
    "write_file": {
      "post": [{"command": "python3", "args": ["hooks/auto_lint.py"]}]
    }
  }
}
```

## 测试

运行工具函数测试：

```bash
python agents/test_utils.py
```

## 常见命令

| 命令 | 功能 |
|------|------|
| `exit` 或 `quit` | 退出程序 |
| `/help` | 显示帮助信息（s05+ 支持） |
| `/compact` | 压缩消息历史（s03+ 支持） |

## 学习路径

### 初学者

1. 运行 **s01** - 理解工具调用基础
2. 修改 TOOLS_SCHEMA - 添加自定义工具
3. 运行 **s02** - 体验系统提示的作用

### 进阶

4. 运行 **s03** - 学习消息管理
5. 运行 **s04** - 理解任务跟踪
6. 运行 **s05** - 扩展技能系统

### 高级

7. 运行 **s06** - 集成 MCP 服务器
8. 运行 **s07** - 部署 Hook 系统
9. 运行 **s08** - 实现多代理协作

## 扩展指南

### 添加新工具

1. 定义 Schema（在 STATIC_TOOLS_SCHEMA 中）
2. 实现 Handler（在 RAW_HANDLERS 中）
3. 添加 try/except 错误处理

```python
# 1. Schema
{"name": "my_tool", "description": "...", "parameters": {...}}

# 2. Handler
def handle_my_tool(**args):
    try:
        # 逻辑
        return result
    except Exception as e:
        return f"[error] {e}"

# 3. 注册
RAW_HANDLERS["my_tool"] = lambda a: handle_my_tool(**a)
```

### 添加 Hook

在 `.hooks.json` 中定义：

```json
{
  "hooks": {
    "my_tool": {
      "pre": [{"command": "python3", "args": ["hooks/my_hook.py"]}],
      "post": [...]
    }
  }
}
```

### 添加技能（s05+）

在 `/skills` 目录创建 `.md` 文件，定义技能逻辑。

## 设计理念

- **最小依赖**: 仅 openai 和 rich
- **模块化**: 每个版本独立可运行
- **渐进式**: 逐步引入复杂特性
- **教育性**: 代码清晰易读，注重演示

## 许可证

MIT

## 相关资源

- [OpenRouter API 文档](https://openrouter.ai/docs)
- [Claude API 指南](https://platform.openai.com/docs)
- [LLM Agent 设计模式](https://arxiv.org/abs/2303.17651)

---

**最后更新**: 2026-03-15 | **版本**: 1.0.0

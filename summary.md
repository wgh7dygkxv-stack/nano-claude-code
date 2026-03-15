# 项目结构总结

## 项目概述
这是一个基于 Claude 3.5 的 AI Agent 实现系列，展示了从简单到复杂的渐进式开发过程。项目使用 Python 实现，仅依赖 openai、rich 两个第三方库。

## 目录结构

### /agents - 核心实现
按照复杂度递增顺序实现了多个版本的 Agent:

1. s01_agent_loop.py - 基础工具调用循环
2. s02_system_prompt.py - 系统提示管理
3. s03_compact.py - 优化的紧凑版本
4. s04_todo.py - TODO 任务管理
5. s05_skill.py - 技能系统
6. s06_mcp.py - 主控制程序
7. s07_hook.py - Hook 系统
8. s08_subagent.py - 子代理系统

支持文件：
- utils.py - 通用工具函数
- test_utils.py - 工具函数测试

### /hooks - 扩展钩子
- auto_lint.py - 自动代码格式化
- dangerous_cmd_guard.py - 危险命令防护

### /mcp_servers - 服务组件
- weather_server.py - 天气服务示例

### /test_files - 测试资源
用于测试的示例文件

## 核心特性
1. 工具系统
   - 基于 Schema 定义工具接口
   - 使用字典分发处理工具调用
   - 严格的错误处理机制

2. 扩展机制
   - Hook 系统支持自定义扩展
   - 技能系统实现能力扩展
   - 子代理支持任务分发

3. 配置管理
   - 通过 CLAUDE.md 配置系统提示
   - 环境变量管理 API 密钥
   - 支持 OpenRouter API

## 使用说明
1. 环境要求
   - Python >= 3.10
   - 安装依赖: openai、rich
   - 设置环境变量: OPENROUTER_API_KEY

2. 启动方式
   - 基础版本: python agents/s01_agent_loop.py
   - 完整版本: python agents/s08_subagent.py
   - 其他版本根据需求选择

3. 可用命令
   - /help - 显示帮助
   - /compact - 压缩历史记录
   - exit/quit - 退出程序
import os
import json
import subprocess
import threading
from pathlib import Path
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)
MODEL = "anthropic/claude-3.5-sonnet"

HOOKS_CONFIG_FILE = Path(".hooks.json")
DEFAULT_HOOKS_CONFIG = {
    "hooks": {
        "write_file": {
            "post": [
                {"command": "python3", "args": ["hooks/auto_lint.py"]}
            ]
        },
        "bash": {
            "pre": [
                {"command": "python3", "args": ["hooks/dangerous_cmd_guard.py"]}
            ]
        }
    }
}

HOOKS_SCRIPTS = {
    "hooks/auto_lint.py": '''\
#!/usr/bin/env python3
"""Post hook: auto_lint - triggered after write_file"""
import sys
import json

if __name__ == "__main__":
    try:
        event = json.loads(sys.stdin.read())
    except Exception:
        event = {}
    print("[Hook] auto_lint 已触发")
''',
    "hooks/dangerous_cmd_guard.py": '''\
#!/usr/bin/env python3
"""Pre hook: dangerous_cmd_guard - blocks dangerous bash commands"""
import sys
import json

if __name__ == "__main__":
    try:
        event = json.loads(sys.stdin.read())
        command = event.get("arguments", {}).get("command", "")
        if "rm -rf" in command:
            print(json.dumps({"proceed": False}))
        else:
            print(json.dumps({"proceed": True}))
    except Exception:
        print(json.dumps({"proceed": True}))
''',
}

BASE_SYSTEM_PROMPT = """你是一个 CLI Coding Agent，运行在用户的终端中。
你可以使用工具帮助用户完成任务。
请用中文回复，保持简洁专业。"""


# ── Hook Engine ────────────────────────────────────────────────────────────────

def load_or_create_hooks_config() -> dict:
    if not HOOKS_CONFIG_FILE.exists():
        HOOKS_CONFIG_FILE.write_text(
            json.dumps(DEFAULT_HOOKS_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[hook] 已生成默认配置：{HOOKS_CONFIG_FILE}")

    # 确保 hook 脚本文件存在
    for rel_path, content in HOOKS_SCRIPTS.items():
        p = Path(rel_path)
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            print(f"[hook] 已生成 Hook 脚本：{rel_path}")

    return json.loads(HOOKS_CONFIG_FILE.read_text(encoding="utf-8"))


def _run_hook(hook_cfg: dict, event: dict, timeout: int = 5) -> str:
    """运行单个 Hook 子进程，返回其 stdout 输出。超时或出错返回空字符串。"""
    command = hook_cfg.get("command", "python3")
    args = hook_cfg.get("args", [])
    try:
        result = subprocess.run(
            [command] + args,
            input=json.dumps(event, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        print(f"[hook] 超时（{timeout}s），视为通过")
        return ""
    except Exception as e:
        print(f"[hook] 运行出错: {e}，视为通过")
        return ""


def run_pre_hooks(hooks_config: dict, tool_name: str, arguments: dict) -> bool:
    """
    执行 pre 钩子列表。
    若任一钩子输出含 {"proceed": false}，返回 False（拦截）。
    否则返回 True（放行）。
    """
    tool_hooks = hooks_config.get("hooks", {}).get(tool_name, {})
    pre_hooks = tool_hooks.get("pre", [])
    if not pre_hooks:
        return True

    event = {"tool": tool_name, "arguments": arguments}
    for hook_cfg in pre_hooks:
        output = _run_hook(hook_cfg, event)
        if output:
            try:
                result = json.loads(output)
                if result.get("proceed") is False:
                    return False
            except (json.JSONDecodeError, AttributeError):
                pass  # 解析失败视为通过
    return True


def run_post_hooks(hooks_config: dict, tool_name: str, arguments: dict, result: str):
    """执行 post 钩子列表（仅通知，不拦截）。"""
    tool_hooks = hooks_config.get("hooks", {}).get(tool_name, {})
    post_hooks = tool_hooks.get("post", [])
    if not post_hooks:
        return

    event = {"tool": tool_name, "arguments": arguments, "result": result}
    for hook_cfg in post_hooks:
        _run_hook(hook_cfg, event)


# ── Tool Handlers ──────────────────────────────────────────────────────────────

def handle_bash(command: str) -> str:
    import subprocess as sp
    try:
        result = sp.run(command, shell=True, capture_output=True, text=True, timeout=30)
        out = result.stdout
        if result.stderr:
            out += f"\n[stderr]\n{result.stderr}"
        return out or "(no output)"
    except sp.TimeoutExpired:
        return "[error] 命令超时（30s）"
    except Exception as e:
        return f"[error] {e}"


def handle_read_file(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception as e:
        return f"[error] {e}"


def handle_write_file(path: str, content: str) -> str:
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {path}"
    except Exception as e:
        return f"[error] {e}"


todo_list: list[dict] = []
STATUS_ICON = {"pending": "○", "in_progress": "◑", "completed": "●"}


def print_todo_list():
    if not todo_list:
        print("[todo] 任务列表为空")
        return
    print("[todo] 当前任务列表：")
    for item in todo_list:
        icon = STATUS_ICON.get(item.get("status", "pending"), "?")
        print(f"  {icon} [{item['id']}] {item['title']} ({item['status']})")


def handle_todo_write(todos: list) -> str:
    global todo_list
    valid = {"pending", "in_progress", "completed"}
    for t in todos:
        if t.get("status") not in valid:
            return f"[error] 无效状态: {t.get('status')}"
    todo_list = todos
    print_todo_list()
    return f"任务列表已更新，共 {len(todos)} 条。"


STATIC_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "执行 shell 命令",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取文件内容",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文件（覆盖）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "todo_write",
            "description": "更新任务列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "todos": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "title": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                            },
                            "required": ["id", "title", "status"],
                        },
                    }
                },
                "required": ["todos"],
            },
        },
    },
]

# 原始 handler（不含 hook 逻辑）
RAW_HANDLERS = {
    "bash": lambda a: handle_bash(**a),
    "read_file": lambda a: handle_read_file(**a),
    "write_file": lambda a: handle_write_file(**a),
    "todo_write": lambda a: handle_todo_write(**a),
}


# ── Subagent 定义 ─────────────────────────────────────────────────────────────

DISPATCH_SUBAGENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "dispatch_subagent",
        "description": "派遣子代理执行调研任务（独立上下文，仅 bash + read_file）",
        "parameters": {
            "type": "object",
            "properties": {
                "task_description": {"type": "string"},
            },
            "required": ["task_description"],
        },
    },
}

SUBAGENT_TOOLS_SCHEMA = [
    s for s in STATIC_TOOLS_SCHEMA
    if s["function"]["name"] in ("bash", "read_file")
]

SUBAGENT_HANDLERS = {
    "bash": lambda a: handle_bash(**a),
    "read_file": lambda a: handle_read_file(**a),
}


def handle_dispatch_subagent(task_description: str) -> str:
    """创建子代理独立上下文，执行调研任务，返回最终回复。"""
    print(f"  [子代理] 启动，任务: {task_description[:100]}")
    sub_messages = [
        {"role": "system", "content": BASE_SYSTEM_PROMPT},
        {"role": "user", "content": task_description},
    ]
    try:
        reply, _ = run_agent_loop(
            sub_messages,
            SUBAGENT_TOOLS_SCHEMA,
            SUBAGENT_HANDLERS,
            hooks_config=None,
            max_iterations=20,
        )
        print(f"  [子代理] 完成")
        return reply
    except Exception as e:
        return f"[error] 子代理执行失败: {e}"


MAIN_TOOLS_SCHEMA = STATIC_TOOLS_SCHEMA + [DISPATCH_SUBAGENT_SCHEMA]

MAIN_HANDLERS = {
    **RAW_HANDLERS,
    "dispatch_subagent": lambda a: handle_dispatch_subagent(**a),
}


# ── Agent Loop ────────────────────────────────────────────────────────────────

def run_agent_loop(
    messages: list,
    tools_schema: list,
    tool_handlers: dict,
    hooks_config: dict | None = None,
    max_iterations: int | None = None,
) -> tuple[str, list]:
    """
    通用代理循环：LLM 调用 + 工具执行。
    hooks_config 为 None 时跳过所有 hook。
    max_iterations 超限时追加总结请求做最终一轮调用。
    """
    iteration = 0
    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=tools_schema,
        )
        choice = response.choices[0]
        msg = choice.message
        messages.append(msg)

        if choice.finish_reason == "tool_calls":
            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                print(f"  [工具] {name}({'' if name == 'todo_write' else args})")

                # ── Pre Hook ──
                if hooks_config is not None:
                    allowed = run_pre_hooks(hooks_config, name, args)
                else:
                    allowed = True

                if not allowed:
                    result = f"[Hook 拦截] 工具 '{name}' 被 pre 钩子拦截，命令未执行。"
                    print(f"  [拦截] {result}")
                else:
                    # ── 执行工具 ──
                    handler = tool_handlers.get(name)
                    if handler:
                        result = handler(args)
                    else:
                        result = f"[error] 未知工具: {name}"
                    print(f"  [结果] {result[:200]}{'...' if len(result) > 200 else ''}")

                    # ── Post Hook ──
                    if hooks_config is not None:
                        run_post_hooks(hooks_config, name, args, result)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                messages.append({
                    "role": "user",
                    "content": "你已达到最大工具调用轮次，请直接总结当前结果。",
                })
                # 最终一轮调用，不再循环
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                )
                final_msg = response.choices[0].message
                messages.append(final_msg)
                return final_msg.content or "", messages
        else:
            return msg.content or "", messages


def run_turn(
    messages: list,
    tools_schema: list,
    hooks_config: dict,
) -> tuple[str, list]:
    return run_agent_loop(messages, tools_schema, MAIN_HANDLERS, hooks_config)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    hooks_config = load_or_create_hooks_config()

    messages = [{"role": "system", "content": BASE_SYSTEM_PROMPT}]

    print("\nNano Claude Code Agent - s08 subagent（输入 exit 或 quit 退出）\n")
    while True:
        try:
            user_input = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break

        if user_input.lower() in ("exit", "quit"):
            print("再见！")
            break
        if not user_input:
            continue

        messages.append({"role": "user", "content": user_input})
        reply, messages = run_turn(messages, MAIN_TOOLS_SCHEMA, hooks_config)
        print(f"助手: {reply}\n")


if __name__ == "__main__":
    main()

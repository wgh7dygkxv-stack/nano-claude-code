import os
import json
import subprocess
from pathlib import Path
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)
MODEL = "anthropic/claude-3.5-sonnet"

BASE_SYSTEM_PROMPT = """你是一个 CLI Coding Agent，运行在用户的终端中。
你可以使用以下工具帮助用户完成编程任务：
- bash: 执行 shell 命令
- read_file: 读取文件内容
- write_file: 将内容写入文件

请用中文回复，保持简洁专业。"""

# ── Tool Schemas ──────────────────────────────────────────────────────────────
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "在当前目录执行 shell 命令，返回 stdout/stderr",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"}
                },
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
                "properties": {
                    "path": {"type": "string", "description": "文件路径"}
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "将内容写入文件（覆盖）",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "要写入的内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
]

# ── Tool Handlers ─────────────────────────────────────────────────────────────
def handle_bash(command: str) -> str:
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout
        if result.stderr:
            output += f"\n[stderr]\n{result.stderr}"
        return output or "(no output)"
    except subprocess.TimeoutExpired:
        return "[error] 命令执行超时（30s）"
    except Exception as e:
        return f"[error] {e}"


def handle_read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"[error] {e}"


def handle_write_file(path: str, content: str) -> str:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True) if os.path.dirname(path) else None
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"已写入 {path}"
    except Exception as e:
        return f"[error] {e}"


TOOL_HANDLERS = {
    "bash": lambda args: handle_bash(**args),
    "read_file": lambda args: handle_read_file(**args),
    "write_file": lambda args: handle_write_file(**args),
}

# ── System Prompt Builder ─────────────────────────────────────────────────────
def find_claude_md() -> str | None:
    """从当前目录向上逐级查找 CLAUDE.md，返回内容或 None。"""
    current = Path.cwd()
    for directory in [current, *current.parents]:
        candidate = directory / "CLAUDE.md"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8"), str(candidate)
    return None, None


def build_system_prompt() -> str:
    content, path = find_claude_md()
    if content:
        print(f"已加载 CLAUDE.md（来自 {path}）")
        return BASE_SYSTEM_PROMPT + "\n\n---\n\n# 项目说明（CLAUDE.md）\n\n" + content
    return BASE_SYSTEM_PROMPT


# ── Compact Command ───────────────────────────────────────────────────────────
def msg_to_text(msg) -> str:
    """将消息对象转为可读文本，用于压缩。"""
    if isinstance(msg, dict):
        role = msg.get("role", "")
        content = msg.get("content", "")
    else:
        role = getattr(msg, "role", "")
        content = getattr(msg, "content", "") or ""
        # 处理带工具调用的 assistant 消息
        tool_calls = getattr(msg, "tool_calls", None)
        if tool_calls:
            parts = [content] if content else []
            for tc in tool_calls:
                parts.append(f"[工具调用] {tc.function.name}({tc.function.arguments})")
            content = "\n".join(parts)

    if role == "tool":
        tool_content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")
        return f"[工具结果] {tool_content[:300]}"

    return f"{role}: {content}"


def compact_messages(messages: list) -> list:
    """
    压缩 messages[1:-4]，保留 system prompt 和最近 4 条。
    返回新的 messages 列表。
    """
    system_msg = messages[0]
    tail = messages[-4:] if len(messages) >= 4 else messages[1:]
    to_compress = messages[1:-4] if len(messages) > 5 else []

    if len(to_compress) < 2:
        print(f"[compact] 可压缩消息不足 2 条（当前 {len(to_compress)} 条），跳过压缩。")
        return messages

    # 拼接压缩区内容
    history_text = "\n".join(msg_to_text(m) for m in to_compress)

    # 独立 LLM 调用生成摘要
    print("[compact] 正在生成对话摘要...")
    summary_response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {
                "role": "system",
                "content": "你是一个对话摘要助手，请用中文简洁地总结以下对话内容，不超过300字。保留关键信息、决策和结果。",
            },
            {
                "role": "user",
                "content": f"请总结以下对话：\n\n{history_text}",
            },
        ],
    )
    summary = summary_response.choices[0].message.content or ""

    # 重建 messages
    summary_msg = {
        "role": "user",
        "content": f"[对话摘要]\n{summary}",
    }
    ack_msg = {
        "role": "assistant",
        "content": "已了解之前的对话摘要，继续为您服务。",
    }

    new_messages = [system_msg, summary_msg, ack_msg] + tail
    old_count = len(messages)
    new_count = len(new_messages)
    print(f"[compact] 压缩完成：{old_count} 条 → {new_count} 条（压缩了 {old_count - new_count} 条）")
    print(f"[compact] 摘要预览：{summary[:100]}{'...' if len(summary) > 100 else ''}")
    return new_messages


# ── Agent Loop ────────────────────────────────────────────────────────────────
def run_turn(messages: list) -> str:
    """执行单轮对话，含工具调用内循环，返回最终文本回复。"""
    while True:
        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS_SCHEMA,
        )
        choice = response.choices[0]
        msg = choice.message
        messages.append(msg)  # assistant message

        if choice.finish_reason == "tool_calls":
            for tc in msg.tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                print(f"  [工具] {name}({args})")
                handler = TOOL_HANDLERS.get(name)
                if handler:
                    result = handler(args)
                else:
                    result = f"[error] 未知工具: {name}"
                print(f"  [结果] {result[:200]}{'...' if len(result) > 200 else ''}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            return msg.content or ""


def handle_command(cmd: str, messages: list) -> list:
    """处理 / 开头的命令，返回（可能更新的）messages。"""
    cmd = cmd.strip().lower()
    if cmd == "/compact":
        return compact_messages(messages)
    elif cmd == "/help":
        print("可用命令：")
        print("  /compact  压缩上下文历史")
        print("  /help     显示帮助")
        print("  exit/quit 退出")
    else:
        print(f"[未知命令] {cmd}，输入 /help 查看可用命令。")
    return messages


def main():
    system_prompt = build_system_prompt()
    messages = [{"role": "system", "content": system_prompt}]

    print("Nano Claude Code Agent - s03 compact（输入 exit 或 quit 退出）\n")
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

        # 命令路由
        if user_input.startswith("/"):
            messages = handle_command(user_input, messages)
            continue

        messages.append({"role": "user", "content": user_input})
        reply = run_turn(messages)
        print(f"助手: {reply}\n")


if __name__ == "__main__":
    main()

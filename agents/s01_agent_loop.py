import os
import json
import subprocess
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["OPENROUTER_API_KEY"],
    base_url="https://openrouter.ai/api/v1",
)
MODEL = "anthropic/claude-3.5-sonnet"

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


def main():
    print("Nano Claude Code Agent (输入 exit 或 quit 退出)\n")
    messages = []
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
        reply = run_turn(messages)
        print(f"助手: {reply}\n")


if __name__ == "__main__":
    main()

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

MCP_CONFIG_FILE = Path(".mcp.json")
DEFAULT_MCP_CONFIG = {
    "mcpServers": {
        "weather": {
            "command": "python3",
            "args": ["mcp_servers/weather_server.py"],
        }
    }
}

BASE_SYSTEM_PROMPT = """你是一个 CLI Coding Agent，运行在用户的终端中。
你可以使用工具帮助用户完成任务。MCP 工具以 mcp__<服务名>__<工具名> 命名。
当用户询问天气时，调用对应的 MCP 天气工具获取信息。
请用中文回复，保持简洁专业。"""


# ── MCP Client ────────────────────────────────────────────────────────────────

class MCPClient:
    def __init__(self, name: str, command: str, args: list[str]):
        self.name = name
        self.command = command
        self.args = args
        self.proc: subprocess.Popen | None = None
        self._id_counter = 0
        self._lock = threading.Lock()

    def _next_id(self) -> int:
        with self._lock:
            self._id_counter += 1
            return self._id_counter

    def start(self):
        self.proc = subprocess.Popen(
            [self.command] + self.args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )

    def send_request(self, method: str, params: dict | None = None) -> dict:
        req_id = self._next_id()
        req = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            req["params"] = params
        line = json.dumps(req, ensure_ascii=False) + "\n"
        self.proc.stdin.write(line)
        self.proc.stdin.flush()

        # 读取响应（跳过通知消息，直到找到匹配 id）
        while True:
            resp_line = self.proc.stdout.readline()
            if not resp_line:
                raise RuntimeError(f"MCP Server '{self.name}' 已关闭连接")
            resp_line = resp_line.strip()
            if not resp_line:
                continue
            resp = json.loads(resp_line)
            if resp.get("id") == req_id:
                return resp

    def send_notification(self, method: str, params: dict | None = None):
        notif = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            notif["params"] = params
        line = json.dumps(notif, ensure_ascii=False) + "\n"
        self.proc.stdin.write(line)
        self.proc.stdin.flush()

    def initialize(self) -> list[dict]:
        """握手 + 工具列表，返回 tools[]。"""
        resp = self.send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "nano-claude-code", "version": "0.6.0"},
            },
        )
        if "error" in resp:
            raise RuntimeError(f"初始化失败: {resp['error']}")

        # 发送 initialized 通知
        self.send_notification("notifications/initialized")

        tools_resp = self.send_request("tools/list")
        if "error" in tools_resp:
            raise RuntimeError(f"获取工具列表失败: {tools_resp['error']}")

        return tools_resp["result"].get("tools", [])

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        resp = self.send_request(
            "tools/call", {"name": tool_name, "arguments": arguments}
        )
        if "error" in resp:
            return f"[error] {resp['error'].get('message', resp['error'])}"
        content = resp["result"].get("content", [])
        parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(parts) or "(无返回内容)"

    def stop(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except Exception:
                pass
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()


# ── Config ────────────────────────────────────────────────────────────────────

def load_or_create_mcp_config() -> dict:
    if not MCP_CONFIG_FILE.exists():
        MCP_CONFIG_FILE.write_text(
            json.dumps(DEFAULT_MCP_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[mcp] 已生成默认配置：{MCP_CONFIG_FILE}")
    return json.loads(MCP_CONFIG_FILE.read_text(encoding="utf-8"))


# ── Tool Schema Builder ────────────────────────────────────────────────────────

def mcp_tool_name(server_name: str, tool_name: str) -> str:
    return f"mcp__{server_name}__{tool_name}"


def build_tool_schema(server_name: str, tool: dict) -> dict:
    return {
        "type": "function",
        "function": {
            "name": mcp_tool_name(server_name, tool["name"]),
            "description": f"[MCP:{server_name}] {tool.get('description', '')}",
            "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
        },
    }


# ── State ─────────────────────────────────────────────────────────────────────

mcp_clients: dict[str, MCPClient] = {}   # server_name -> MCPClient
# tool_name (mcp__x__y) -> (client, original_tool_name)
mcp_tool_map: dict[str, tuple[MCPClient, str]] = {}
todo_list: list[dict] = []


# ── Tool Handlers ─────────────────────────────────────────────────────────────

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


def handle_todo_write(todos: list) -> str:
    global todo_list
    valid = {"pending", "in_progress", "completed"}
    for t in todos:
        if t.get("status") not in valid:
            return f"[error] 无效状态: {t.get('status')}"
    todo_list = todos
    print_todo_list()
    return f"任务列表已更新，共 {len(todos)} 条。"


def handle_mcp_tool(full_name: str, args: dict) -> str:
    entry = mcp_tool_map.get(full_name)
    if not entry:
        return f"[error] 未找到 MCP 工具: {full_name}"
    mcp_client, original_name = entry
    return mcp_client.call_tool(original_name, args)


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
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
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


# ── Todo Display ──────────────────────────────────────────────────────────────

STATUS_ICON = {"pending": "○", "in_progress": "◑", "completed": "●"}


def print_todo_list():
    if not todo_list:
        print("[todo] 任务列表为空")
        return
    print("[todo] 当前任务列表：")
    for item in todo_list:
        icon = STATUS_ICON.get(item.get("status", "pending"), "?")
        print(f"  {icon} [{item['id']}] {item['title']} ({item['status']})")


# ── Agent Loop ────────────────────────────────────────────────────────────────

def run_turn(messages: list, tools_schema: list, tool_handlers: dict) -> tuple[str, list]:
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
                handler = tool_handlers.get(name)
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
            return msg.content or "", messages


# ── Startup ───────────────────────────────────────────────────────────────────

def init_mcp_servers() -> tuple[list[dict], dict]:
    """启动所有 MCP Server，返回 (tools_schema_list, tool_handlers)。"""
    config = load_or_create_mcp_config()
    servers_cfg = config.get("mcpServers", {})

    extra_schemas: list[dict] = []
    handlers: dict = {}

    for server_name, cfg in servers_cfg.items():
        command = cfg.get("command", "python")
        args = cfg.get("args", [])
        mcp = MCPClient(server_name, command, args)
        try:
            mcp.start()
            tools = mcp.initialize()
            mcp_clients[server_name] = mcp
            print(f"[mcp] 已连接 MCP Server: {server_name}，工具：{[t['name'] for t in tools]}")
            for tool in tools:
                full_name = mcp_tool_name(server_name, tool["name"])
                mcp_tool_map[full_name] = (mcp, tool["name"])
                extra_schemas.append(build_tool_schema(server_name, tool))
                handlers[full_name] = lambda a, fn=full_name: handle_mcp_tool(fn, a)
        except Exception as e:
            print(f"[mcp] 连接 Server '{server_name}' 失败: {e}")
            mcp.stop()

    return extra_schemas, handlers


def shutdown_all():
    for name, mcp in mcp_clients.items():
        mcp.stop()
        print(f"[mcp] 已关闭 Server: {name}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    mcp_schemas, mcp_handlers = init_mcp_servers()

    tools_schema = STATIC_TOOLS_SCHEMA + mcp_schemas
    tool_handlers = {
        "bash": lambda a: handle_bash(**a),
        "read_file": lambda a: handle_read_file(**a),
        "write_file": lambda a: handle_write_file(**a),
        "todo_write": lambda a: handle_todo_write(**a),
        **mcp_handlers,
    }

    messages = [{"role": "system", "content": BASE_SYSTEM_PROMPT}]

    print("\nNano Claude Code Agent - s06 mcp（输入 exit 或 quit 退出）\n")
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
        reply, messages = run_turn(messages, tools_schema, tool_handlers)
        print(f"助手: {reply}\n")

    shutdown_all()


if __name__ == "__main__":
    main()

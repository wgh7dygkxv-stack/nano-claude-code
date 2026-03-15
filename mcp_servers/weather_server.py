#!/usr/bin/env python3
"""极简 MCP Server - stdio + JSON-RPC，提供 get_weather Mock 工具。"""
import sys
import json

TOOLS = [
    {
        "name": "get_weather",
        "description": "获取指定城市的天气信息（Mock 数据）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "城市名称，例如：北京、上海",
                }
            },
            "required": ["city"],
        },
    }
]

MOCK_WEATHER = {
    "北京": {"temp": "8°C", "condition": "晴", "humidity": "30%", "wind": "北风3级"},
    "上海": {"temp": "15°C", "condition": "多云", "humidity": "65%", "wind": "东风2级"},
    "广州": {"temp": "22°C", "condition": "小雨", "humidity": "80%", "wind": "南风1级"},
    "成都": {"temp": "12°C", "condition": "阴", "humidity": "75%", "wind": "无风"},
}


def send(obj: dict):
    line = json.dumps(obj, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def handle(req: dict) -> dict | None:
    req_id = req.get("id")
    method = req.get("method", "")

    # 通知（无 id）直接忽略，不回复
    if req_id is None:
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "weather", "version": "1.0.0"},
            },
        }

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    if method == "tools/call":
        params = req.get("params", {})
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        if tool_name == "get_weather":
            city = args.get("city", "未知")
            data = MOCK_WEATHER.get(city)
            if data:
                text = (
                    f"📍 {city} 天气报告\n"
                    f"🌡️ 温度：{data['temp']}\n"
                    f"☁️ 天气：{data['condition']}\n"
                    f"💧 湿度：{data['humidity']}\n"
                    f"💨 风况：{data['wind']}"
                )
            else:
                text = f"暂无 {city} 的天气数据（支持：北京、上海、广州、成都）"
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": text}]},
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"未知工具: {tool_name}"},
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"未知方法: {method}"},
    }


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            resp = handle(req)
            if resp is not None:
                send(resp)
        except json.JSONDecodeError as e:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"JSON 解析失败: {e}"}})


if __name__ == "__main__":
    main()

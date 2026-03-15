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

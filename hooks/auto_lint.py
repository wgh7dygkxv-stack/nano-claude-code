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

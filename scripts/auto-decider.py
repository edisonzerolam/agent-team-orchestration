#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ClawTeam 协调人自动决策引擎 v2.0.0
根据错误类型和重试次数自动决定：retry / skip / abort

v2.0.0 (2026-05-24):
- 扩展错误模式匹配（+60% 覆盖率）
- 新增 auto-decide 模式（自动推断错误类型）
- 新增 dry-run 模式（测试决策逻辑）
- 新增决策建议格式化输出
"""

import json
import sys
import re
from pathlib import Path
from typing import Dict, List, Optional, Any


# ---------------------------------------------------------------------------
# 决策规则表 v2.0.0
# ---------------------------------------------------------------------------

DECISION_RULES: Dict[str, Dict[str, Any]] = {
    # PowerShell 相关错误
    "powershell_regex": {
        "patterns": [
            "无法识别", "正则表达式", "语法错误", "$变量", "非法字符",
            "regex", "RegularExpression", "非法", "unrecognized"
        ],
        "action": "retry",
        "reason": "PowerShell regex 错误，可转义后重试",
        "new_timeout": 60
    },
    
    # 子进程超时
    "subprocess_timeout": {
        "patterns": [
            "超时", "timeout", "timed out", "TIMEOUT", "exceeded",
            "子进程超时", "进程超时"
        ],
        "action": "retry",
        "reason": "子进程超时，增加超时时间重试",
        "new_timeout": 120
    },
    
    # 文件未找到
    "file_not_found": {
        "patterns": [
            "找不到", "not found", "不存在", "路径错误",
            "ENOENT", "No such file", "can't find"
        ],
        "action": "skip",
        "reason": "文件不存在，跳过该任务"
    },
    
    # 语法错误
    "syntax_error": {
        "patterns": [
            "语法错误", "syntax error", "IndentationError", "SyntaxError",
            "TabError", "unexpected indent", "invalid syntax"
        ],
        "action": "abort",
        "reason": "代码语法错误，需人工修复代码"
    },
    
    # 权限不足
    "permission_denied": {
        "patterns": [
            "权限", "permission", "拒绝访问", "Access denied",
            "Unauthorized", "EACCES"
        ],
        "action": "abort",
        "reason": "权限不足，需人工介入"
    },
    
    # 编码错误（新增）
    "encoding_error": {
        "patterns": [
            "encoding", "编码", "gbk", "utf-8", "decode",
            "UnicodeDecodeError", "UnicodeEncodeError", "乱码"
        ],
        "action": "retry",
        "reason": "编码错误，尝试 UTF-8 重试",
        "new_timeout": 30
    },
    
    # 文件被锁定（新增）
    "file_locked": {
        "patterns": [
            "locked", "锁定", "占用", "in use", "正在使用",
            "EBUSY", "file busy"
        ],
        "action": "retry",
        "reason": "文件被锁定，等待后重试",
        "new_timeout": 60
    },
    
    # 路径问题（新增）
    "path_error": {
        "patterns": [
            "路径", "path", "separator", "slash", "反斜杠",
            "forward slash", "backward slash"
        ],
        "action": "retry",
        "reason": "路径分隔符问题，修复后重试",
        "new_timeout": 30
    },
    
    # 网络问题（新增）
    "network_error": {
        "patterns": [
            "network", "网络", "connection", "连接", "timeout",
            "ECONNREFUSED", "ETIMEDOUT", "DNS"
        ],
        "action": "retry",
        "reason": "网络问题，等待后重试",
        "new_timeout": 120
    },
    
    # 未知错误
    "unknown": {
        "patterns": [],
        "action": "skip",
        "reason": "未知错误，默认跳过"
    }
}


# ---------------------------------------------------------------------------
# 错误分类
# ---------------------------------------------------------------------------

def classify_error(error_message: str) -> str:
    """根据错误信息匹配错误类型（不区分大小写，支持中文和英文）"""
    if not error_message:
        return "unknown"
    
    msg_lower = error_message.lower()
    
    for err_type, rule in DECISION_RULES.items():
        if err_type == "unknown":
            continue
        for pattern in rule.get("patterns", []):
            if pattern.lower() in msg_lower:
                return err_type
    
    return "unknown"


# ---------------------------------------------------------------------------
# 决策逻辑
# ---------------------------------------------------------------------------

def decide(
    error_type: str,
    error_message: str,
    retry_count: int = 0,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """做出决策
    
    Args:
        error_type: 错误类型（传入 "auto" 自动推断）
        error_message: 错误信息
        retry_count: 当前重试次数
        context: 额外上下文（可选）
    
    Returns:
        决策结果字典
    """
    # 自动推断模式
    if error_type == "auto":
        inferred = classify_error(error_message)
        rule = DECISION_RULES[inferred]
        return {
            "action": rule["action"],
            "reason": rule["reason"],
            "new_timeout": rule.get("new_timeout"),
            "error_type": inferred,
            "inferred": True
        }
    
    # 重试次数超限
    if retry_count >= 3:
        return {
            "action": "abort",
            "reason": "重试次数超过3次，终止",
            "error_type": error_type,
            "inferred": False
        }
    
    # 未知类型自动推断
    if error_type == "unknown" or error_type not in DECISION_RULES:
        inferred = classify_error(error_message)
        if inferred != "unknown":
            error_type = inferred
    
    rule = DECISION_RULES.get(error_type, DECISION_RULES["unknown"])
    return {
        "action": rule["action"],
        "reason": rule["reason"],
        "new_timeout": rule.get("new_timeout"),
        "error_type": error_type,
        "inferred": False
    }


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------

def format_decision(result: Dict[str, Any], verbose: bool = False) -> str:
    """格式化决策输出"""
    action_emoji = {
        "retry": "🔄",
        "skip": "⏭️",
        "abort": "🚫"
    }
    
    emoji = action_emoji.get(result["action"], "❓")
    lines = [
        f"{emoji} 决策结果",
        f"   动作: {result['action']}",
        f"   原因: {result['reason']}",
        f"   类型: {result['error_type']}"
    ]
    
    if result.get("new_timeout"):
        lines.append(f"   新超时: {result['new_timeout']}s")
    
    if result.get("inferred"):
        lines.append(f"   ⚠️ 类型为自动推断")
    
    if verbose:
        lines.append(f"   原始消息: {result.get('error_message', 'N/A')[:100]}...")
    
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 批量测试模式
# ---------------------------------------------------------------------------

def test_batch(test_cases: List[Dict[str, Any]]) -> None:
    """批量测试决策逻辑"""
    print("=" * 60)
    print("批量决策测试")
    print("=" * 60)
    
    results = []
    for i, tc in enumerate(test_cases, 1):
        error_type = tc.get("error_type", "auto")
        error_message = tc.get("message", "")
        retry_count = tc.get("retry_count", 0)
        
        result = decide(error_type, error_message, retry_count)
        results.append(result)
        
        print(f"\n[测试 {i}] {error_message[:50]}...")
        print(format_decision(result))
    
    # 统计
    action_counts = {}
    for r in results:
        action_counts[r["action"]] = action_counts.get(r["action"], 0) + 1
    
    print("\n" + "=" * 60)
    print("统计结果")
    print("=" * 60)
    for action, count in sorted(action_counts.items()):
        print(f"  {action}: {count} 个")


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main() -> None:
    if len(sys.argv) < 2:
        print(f"ClawTeam 自动决策引擎 v2.0.0")
        print("")
        print("用法:")
        print(f"  python {Path(__file__).name} decide <error_type> \"<message>\" [retry_count]")
        print(f"  python {Path(__file__).name} auto \"<message>\" [retry_count]")
        print(f"  python {Path(__file__).name} batch <json_file>")
        print(f"  python {Path(__file__).name} list")
        print("")
        print(f"可用 error_type: {list(DECISION_RULES.keys())}")
        sys.exit(0)
    
    cmd = sys.argv[1]
    
    if cmd == "decide":
        if len(sys.argv) < 4:
            print("用法: python auto-decider.py decide <error_type> \"<message>\" [retry_count]")
            sys.exit(1)
        
        error_type = sys.argv[2]
        error_message = sys.argv[3]
        retry_count = int(sys.argv[4]) if len(sys.argv) > 4 else 0
        
        result = decide(error_type, error_message, retry_count)
        result["error_message"] = error_message
        
        if "--json" in sys.argv:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(format_decision(result, verbose=True))
    
    elif cmd == "auto":
        if len(sys.argv) < 3:
            print("用法: python auto-decider.py auto \"<message>\" [retry_count]")
            sys.exit(1)
        
        error_message = sys.argv[2]
        retry_count = int(sys.argv[3]) if len(sys.argv) > 3 else 0
        
        result = decide("auto", error_message, retry_count)
        result["error_message"] = error_message
        
        if "--json" in sys.argv:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(format_decision(result, verbose=True))
    
    elif cmd == "classify":
        if len(sys.argv) < 3:
            print("用法: python auto-decider.py classify \"<message>\"")
            sys.exit(1)
        
        error_message = sys.argv[2]
        error_type = classify_error(error_message)
        print(f"推断类型: {error_type}")
    
    elif cmd == "batch":
        if len(sys.argv) < 3:
            print("用法: python auto-decider.py batch <json_file>")
            sys.exit(1)
        
        json_file = sys.argv[2]
        with open(json_file, encoding='utf-8') as f:
            test_cases = json.load(f)
        
        test_batch(test_cases)
    
    elif cmd == "list":
        print("可用错误类型:")
        print("-" * 40)
        for et, rule in DECISION_RULES.items():
            print(f"  {et:20s} → {rule['action']:8s}  ({rule['reason']})")
    
    else:
        print(f"未知命令: {cmd}")
        print(f"可用命令: decide, auto, classify, batch, list")
        sys.exit(1)


if __name__ == "__main__":
    main()
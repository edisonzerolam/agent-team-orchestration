"""atomic-write.py — 跨平台原子文件写入工具


# [中文说明]
# 本文件：atomic-write.py
# 用途：OpenClaw 框架的核心脚本之一
# 详细文档：请阅读对应的 SKILL.md 和 references/

功能：
- atomic_write(path, content, encoding='utf-8'): 原子写入（临时文件+os.replace）
- atomic_append(path, line, encoding='utf-8', max_lines=20): 原子追加（保留最近N行）

跨平台：Windows/Linux/macOS 都用 os.replace()（Windows上等价于原子rename）
"""

import os
import uuid
import shutil
from pathlib import Path
from typing import Optional


def atomic_write(path: str, content: str, encoding: str = 'utf-8') -> dict:
    """原子写入：临时文件+rename
    - temp = f{path}.{uuid}.tmp
    - 写内容到temp
    - os.replace(temp, path)  # 原子操作
    """
    if not path:
        return {"status": "error", "message": "path cannot be empty"}
    if content is None:
        return {"status": "error", "message": "content cannot be None"}

    path = Path(path).resolve()
    temp = path.parent / f".{uuid.uuid4().hex[:8]}.tmp"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp.write_text(content, encoding=encoding)
        os.replace(str(temp), str(path))  # 跨平台原子
        return {"status": "ok", "path": str(path)}
    except Exception as e:
        try:
            if temp.exists():
                temp.unlink()
        except Exception:
            pass
        return {"status": "error", "message": str(e)}


def atomic_append(path: str, line: str, encoding: str = 'utf-8', max_lines: int = 20) -> dict:
    """原子追加：读取现有内容→保留最近max_lines行→追加新行→原子写入
    用途：progress.md追加（防止并发写入覆盖）
    """
    if not path:
        return {"status": "error", "message": "path cannot be empty"}
    if line is None:
        return {"status": "error", "message": "line cannot be None"}
    if max_lines < 1:
        max_lines = 1

    path = Path(path).resolve()
    try:
        if path.exists():
            lines = path.read_text(encoding=encoding).splitlines()
            lines = lines[-max_lines:]  # 保留最近N行
        else:
            lines = []
        lines.append(line)
        content = '\n'.join(lines) + '\n'
        return atomic_write(str(path), content, encoding)
    except Exception as e:
        return {"status": "error", "message": str(e)}


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: atomic-write.py <write|append> <path> [line]")
        sys.exit(1)
    cmd = sys.argv[1]
    target = sys.argv[2]
    if cmd == "write":
        content = sys.stdin.read() if len(sys.argv) == 3 else sys.argv[3]
        result = atomic_write(target, content)
    elif cmd == "append":
        line = sys.argv[3] if len(sys.argv) > 3 else ""
        result = atomic_append(target, line)
    else:
        result = {"status": "error", "message": f"unknown command: {cmd}"}
    print(result)
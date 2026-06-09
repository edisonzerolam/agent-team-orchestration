#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent Self-Heal Module v2.0.0

v2.0.0 (2026-05-24):
- 实现 fix_powershell_regex 真正修复逻辑（转义 $ 等特殊字符）
- 增加 Windows 路径兼容性处理
- 增强错误分类（新增 5 种错误类型）
"""

__version__ = '2.0.0'

import json
import re
import os
import subprocess
from pathlib import Path
from typing import Tuple, Optional, Dict, Any


# ---------------------------------------------------------------------------
# 错误类型定义
# ---------------------------------------------------------------------------

ERROR_TYPES = {
    'powershell_regex': {
        'severity': 'medium',
        'recoverable': True,
        'fix_actions': ['escape_dollar_sign', 'quote_paths', 'log_and_skip'],
        'max_retries': 2,
        'description': 'PowerShell 正则表达式/变量解析错误'
    },
    'path_not_found': {
        'severity': 'high',
        'recoverable': True,
        'fix_actions': ['normalize_path', 'log_and_skip'],
        'max_retries': 1,
        'description': '路径未找到（Windows 路径分隔符问题）'
    },
    'encoding_error': {
        'severity': 'medium',
        'recoverable': True,
        'fix_actions': ['fix_encoding', 'log_and_skip'],
        'max_retries': 2,
        'description': '编码错误（中文/GBK 乱码）'
    },
    'subprocess_timeout': {
        'severity': 'low',
        'recoverable': True,
        'fix_actions': ['increase_timeout', 'retry'],
        'max_retries': 2,
        'description': '子进程超时'
    },
    'file_locked': {
        'severity': 'medium',
        'recoverable': True,
        'fix_actions': ['wait_and_retry', 'log_and_skip'],
        'max_retries': 3,
        'description': '文件被锁定'
    },
    'unknown': {
        'severity': 'low',
        'recoverable': False,
        'fix_actions': ['log_and_skip'],
        'max_retries': 1,
        'description': '未知错误'
    }
}


def classify_error(error_message: str) -> str:
    """根据错误信息推断错误类型"""
    msg_lower = error_message.lower()
    
    # PowerShell 相关
    if any(kw in msg_lower for kw in ['regex', '正则', '语法错误', '无法识别', '非法字符']):
        return 'powershell_regex'
    
    # 路径相关
    if any(kw in msg_lower for kw in ['找不到', 'not found', '不存在', '路径错误', "can't find", 'enoent']):
        return 'path_not_found'
    
    # 编码相关
    if any(kw in msg_lower for kw in ['encoding', '编码', 'gbk', 'utf-8', 'decode', 'UnicodeDecodeError']):
        return 'encoding_error'
    
    # 超时相关
    if any(kw in msg_lower for kw in ['timeout', '超时', 'timed out']):
        return 'subprocess_timeout'
    
    # 文件锁定
    if any(kw in msg_lower for kw in ['locked', '锁定', '占用', 'in use']):
        return 'file_locked'
    
    return 'unknown'


# ---------------------------------------------------------------------------
# 修复函数
# ---------------------------------------------------------------------------

def _escape_powershell_vars(cmd: str) -> str:
    """转义 PowerShell 中的 $ 变量引用
    
    常见问题：PowerShell 中 $HOME 等是内置变量，
    在 subprocess 调用时需要转义为 $$HOME 或单引号。
    """
    # 匹配未被引号包围的 $变量
    # 转义策略：使用单引号包裹（PowerShell 中单引号内 $ 不解释）
    result = cmd
    
    # 替换未引用的 $变量 为 $$（转义）
    # 简单策略：将不在单引号/双引号内的 $WORD 替换为 $$WORD
    def replacer(m):
        var = m.group(0)
        # 检查是否在引号内
        prefix = m.group(1)
        if prefix in ["'", '"']:
            return var  # 在引号内，保持原样
        return '$$' + var[1:]  # 转义 $
    
    # 匹配: 可选引号前缀 + $变量名
    result = re.sub(r"(?<!['\"])\$([A-Za-z_][A-Za-z0-9_]*)", 
                   lambda m: m.group(0) if m.group(0)[0] in ["'", '"'] else '$$' + m.group(0)[1:],
                   result)
    
    return result


def _fix_powershell_path(cmd: str) -> str:
    """修复 Windows PowerShell 路径问题
    
    - 将 / 路径转换为 \（PowerShell 默认反斜杠）
    - 规范化连续斜杠
    """
    # 替换正斜杠为反斜杠（Windows PowerShell）
    result = cmd.replace('/', '\\')
    
    # 规范化路径（连续反斜杠变单个）
    result = re.sub(r'\\+', r'\\', result)
    
    return result


def _fix_encoding_issues(cmd: str) -> str:
    """修复编码问题
    
    - 检测中文字符，确保使用 UTF-8
    - 对特殊中文字符加引号保护
    """
    # 检测是否有未包裹的中文
    # 简单策略：如果有中文且未被引号包围，用双引号包裹
    has_chinese = bool(re.search(r'[\u4e00-\u9fff]', cmd))
    
    if has_chinese:
        # 检查命令是否已有引号
        if not (cmd.startswith("'") or cmd.startswith('"')):
            # 找到第一个空格前的命令
            parts = cmd.split()
            if parts:
                # 用双引号包裹整个命令
                return '"' + cmd + '"'
    
    return cmd


def fix_powershell_regex(error_message: str, context: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str], str]:
    """修复 PowerShell 相关错误
    
    Returns:
        (fix_success, fixed_command, fix_action)
    """
    if context is None:
        context = {}
    
    cmd = context.get('command', '')
    if not cmd:
        return False, None, 'no_command_available'
    
    original = cmd
    fixes_applied = []
    
    # 1. 转义 $ 变量
    if '$' in error_message or any(kw in error_message.lower() for kw in ['dollar', '变量', '非法字符']):
        escaped = _escape_powershell_vars(cmd)
        if escaped != cmd:
            fixes_applied.append('escape_dollar')
            cmd = escaped
    
    # 2. 修复路径分隔符（Windows）
    if any(kw in error_message.lower() for kw in ['路径', 'path', 'separator', 'slash']):
        fixed_path = _fix_powershell_path(cmd)
        if fixed_path != cmd:
            fixes_applied.append('fix_path_separator')
            cmd = fixed_path
    
    # 3. 修复编码问题
    if any(kw in error_message.lower() for kw in ['encoding', '编码', 'gbk', 'decode']):
        fixed_encoding = _fix_encoding_issues(cmd)
        if fixed_encoding != cmd:
            fixes_applied.append('fix_encoding')
            cmd = fixed_encoding
    
    if fixes_applied:
        return True, cmd, '+'.join(fixes_applied)
    
    return False, None, 'no_fix_available'


def fix_path_not_found(error_message: str, context: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str], str]:
    """修复路径未找到错误"""
    if context is None:
        context = {}
    
    cmd = context.get('command', '')
    if not cmd:
        return False, None, 'no_command_available'
    
    original = cmd
    
    # 规范化路径
    fixed = _fix_powershell_path(cmd)
    
    if fixed != cmd:
        return True, fixed, 'normalize_path'
    
    return False, None, 'path_not_normalized'


def fix_encoding_error(error_message: str, context: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str], str]:
    """修复编码错误"""
    if context is None:
        context = {}
    
    cmd = context.get('command', '')
    if not cmd:
        return False, None, 'no_command_available'
    
    fixed = _fix_encoding_issues(cmd)
    
    if fixed != cmd:
        return True, fixed, 'fix_encoding'
    
    return False, None, 'encoding_not_fixable'


# ---------------------------------------------------------------------------
# 修复函数映射
# ---------------------------------------------------------------------------

FIX_FUNCTIONS = {
    'powershell_regex': fix_powershell_regex,
    'path_not_found': fix_path_not_found,
    'encoding_error': fix_encoding_error,
}


def apply_fix(error_type: str, error_message: str, context: Optional[Dict[str, Any]] = None) -> Tuple[bool, Optional[str], str]:
    """根据错误类型应用对应修复"""
    fix_func = FIX_FUNCTIONS.get(error_type)
    if fix_func:
        return fix_func(error_message, context)
    return False, None, f'no_fix_for_{error_type}'


# ---------------------------------------------------------------------------
# SelfHeal 主类
# ---------------------------------------------------------------------------

class SelfHeal:
    def __init__(self, team_id: str, agent_id: str, workspace: Optional[Path] = None):
        self.team_id = team_id
        self.agent_id = agent_id
        self.workspace = workspace or Path.home() / '.qclaw' / 'shared' / 'team-brain'
        self.error_dir = self.workspace / 'errors' / team_id / agent_id
        self.error_dir.mkdir(parents=True, exist_ok=True)
        self.retries: Dict[str, int] = {}
        self.fix_stats = {'success': 0, 'failed': 0, 'skipped': 0}

    def handle_error(
        self,
        error_message: str,
        error_type: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """处理错误，自动分类并尝试修复"""
        if error_type is None:
            error_type = classify_error(error_message)
        
        error_info = ERROR_TYPES.get(error_type, ERROR_TYPES['unknown'])
        max_retries = error_info['max_retries']
        current_retries = self.retries.get(error_type, 0)
        
        result = {
            'error_type': error_type,
            'error_message': error_message[:200],
            'severity': error_info['severity'],
            'retries': current_retries,
            'max_retries': max_retries,
            'handled': False,
            'fix_success': False,
            'fix_action': None,
            'fixed_command': None,
            'should_continue': True,
            'error_logged': False
        }
        
        # 超过最大重试次数
        if current_retries >= max_retries:
            result['should_continue'] = False
            result['fix_action'] = 'max_retries_exceeded'
            self._log_error(error_type, error_message, result)
            result['error_logged'] = True
            return result
        
        # 尝试修复
        fix_success, fixed_value, fix_action = apply_fix(error_type, error_message, context)
        result['fix_success'] = fix_success
        result['fix_action'] = fix_action
        result['fixed_command'] = fixed_value
        
        if fix_success:
            self.fix_stats['success'] += 1
            self.retries[error_type] = current_retries + 1
            result['handled'] = True
        else:
            self.fix_stats['skipped'] += 1
            result['fix_action'] = 'log_and_skip'
            result['should_continue'] = False
            self.fix_stats['skipped'] += 1
        
        self._log_error(error_type, error_message, result)
        result['error_logged'] = True
        return result

    def _log_error(self, error_type: str, error_message: str, result: Dict[str, Any]) -> None:
        """原子写入错误日志"""
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        log_file = self.error_dir / f'{timestamp}-{error_type}.json'
        
        log_entry = {
            'team_id': self.team_id,
            'agent_id': self.agent_id,
            'timestamp': datetime.now().isoformat(),
            'error_type': error_type,
            'error_message': error_message,
            'result': {k: v for k, v in result.items() if k != 'error_logged'},
            'fix_stats': dict(self.fix_stats)
        }
        
        # 原子写入
        import uuid
        tmp = log_file.parent / f'.{uuid.uuid4().hex[:8]}.tmp'
        log_file.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(log_entry, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(str(tmp), str(log_file))

    def get_stats(self) -> Dict[str, int]:
        """获取修复统计"""
        return dict(self.fix_stats)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 4 or sys.argv[1] != 'heal':
        print(f"用法: python {Path(__file__).name} heal <team_id> <agent_id> <error_message>")
        print(f"版本: {__version__}")
        print(f"错误类型: {list(ERROR_TYPES.keys())}")
        sys.exit(1)
    
    team_id = sys.argv[2]
    agent_id = sys.argv[3]
    error_message = sys.argv[4] if len(sys.argv) > 4 else ''
    
    healer = SelfHeal(team_id, agent_id)
    result = healer.handle_error(error_message)
    
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n修复统计: {healer.get_stats()}")
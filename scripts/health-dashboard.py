#!/usr/bin/env python3
"""
ClawTeam 健康检查 Dashboard v1.0.0
纯 Python 内置库实现，支持 serve 和 export 两种模式
"""

__version__ = "1.0.0"

import http.server
import json
import pathlib
import datetime
import socket
import sys
import os
import io
from typing import Optional

# 修复 Windows 终端编码
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 路径配置
TEAMS_DIR = pathlib.Path(os.environ.get("CLAWTEAM_SHARED", pathlib.Path(__file__).parent.parent.parent / "shared" / "team-brain" / "teams"))
SCRIPT_DIR = pathlib.Path(__file__).parent


def load_teams() -> list[dict]:
    """读取所有团队状态文件"""
    teams = []
    if not TEAMS_DIR.exists():
        return teams
    for f in TEAMS_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            data["_file"] = f.name
            teams.append(data)
        except Exception:
            pass
    return sorted(teams, key=lambda x: x.get("created_at", ""))


def get_health_status(agent_statuses: list) -> tuple[str, str]:
    """根据 agent 状态计算健康状态"""
    if not agent_statuses:
        return "🔴", "无 Agent"
    alive = sum(1 for s in agent_statuses if s.get("status") != "dead")
    total = len(agent_statuses)
    ratio = alive / total
    if ratio >= 0.8:
        return "🟢", f"{alive}/{total} 活跃"
    elif ratio >= 0.5:
        return "🟡", f"{alive}/{total} 活跃"
    else:
        return "🔴", f"{alive}/{total} 活跃"


def escape_html(text: str) -> str:
    """HTML 转义"""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;"))


def build_html(teams: list[dict], title: str = "ClawTeam 健康检查 Dashboard") -> str:
    """生成 HTML 页面"""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # 统计汇总
    total_teams = len(teams)
    total_agents = 0
    alive_agents = 0
    fail_count = 0
    
    team_rows = []
    for team in teams:
        agents = team.get("agents", [])
        total_agents += len(agents)
        alive_agents += sum(1 for a in agents if a.get("status") != "dead")
        
        health_icon, health_text = get_health_status(agents)
        phase = escape_html(team.get("phase", team.get("current_phase", team.get("stage", "—"))))
        task_name = escape_html(team.get("task_name", team.get("name", "—")))
        team_id = escape_html(team.get("team_id", "—"))
        
        # 收集错误信息
        errors = []
        for a in agents:
            err = a.get("error_message") or a.get("last_error")
            if err:
                errors.append(f"{escape_html(a.get('agent_id', a.get('name', '?')))}: {escape_html(err)}")
        
        error_cell = ""
        if errors:
            error_cell = f"<details class='errors'><summary>⚠ {len(errors)} 个错误</summary><ul>" + "".join(f"<li>{e}</li>" for e in errors) + "</ul></details>"
        
        # 计算存活时间
        created = team.get("created_at", "")
        age_text = ""
        if created:
            try:
                dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                age = datetime.datetime.now() - dt.replace(tzinfo=None)
                mins = int(age.total_seconds() / 60)
                age_text = f"{mins} 分钟"
            except Exception:
                age_text = "—"

        row_class = "fail" if health_icon == "🔴" else ("warn" if health_icon == "🟡" else "ok")
        team_rows.append(f"""<tr class="{row_class}">
            <td><code>{team_id}</code></td>
            <td>{task_name}</td>
            <td>{phase}</td>
            <td>{age_text}</td>
            <td class="health">{health_icon} {health_text}</td>
            <td>{error_cell}</td>
        </tr>""")
        
        if health_icon == "🔴":
            fail_count += 1

    if not team_rows:
        team_rows.append("<tr><td colspan='6' style='text-align:center;color:#888'>暂无团队数据</td></tr>")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape_html(title)}</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, "Segoe UI", Arial, sans-serif; background: #0f1419; color: #e7e9ea; min-height: 100vh; padding: 24px; }}
.header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; flex-wrap: wrap; gap: 12px; }}
h1 {{ font-size: 22px; font-weight: 600; color: #f7f9f9; }}
.timestamp {{ color: #71767b; font-size: 13px; }}
.summary {{ display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }}
.stat {{ background: #1c2732; border-radius: 8px; padding: 12px 20px; }}
.stat-label {{ font-size: 12px; color: #71767b; text-transform: uppercase; margin-bottom: 4px; }}
.stat-value {{ font-size: 22px; font-weight: 600; }}
.stat-ok {{ color: #00ba7c; }}
.stat-warn {{ color: #ffd60a; }}
.stat-fail {{ color: #f4212e; }}
.stat-total {{ color: #f7f9f9; }}
table {{ width: 100%; border-collapse: collapse; background: #1c2732; border-radius: 12px; overflow: hidden; }}
th {{ background: #27333d; color: #71767b; font-size: 12px; text-transform: uppercase; padding: 12px 16px; text-align: left; font-weight: 500; }}
td {{ padding: 12px 16px; border-top: 1px solid #2f3336; vertical-align: top; font-size: 14px; }}
tr.ok td {{ color: #e7e9ea; }}
tr.warn td {{ background: rgba(255,214,10,0.05); }}
tr.fail td {{ background: rgba(244,33,46,0.08); }}
td.health {{ font-weight: 600; white-space: nowrap; }}
code {{ background: #2f3336; padding: 2px 6px; border-radius: 4px; font-size: 12px; }}
.errors {{ margin-top: 4px; font-size: 12px; color: #f4212e; }}
.errors ul {{ margin-top: 4px; padding-left: 16px; color: #f4212e; }}
.errors summary {{ cursor: pointer; color: #f4212e; }}
.footer {{ margin-top: 24px; text-align: center; color: #71767b; font-size: 12px; }}
.refresh {{ color: #1d9bf0; text-decoration: none; }}
@media (max-width: 700px) {{ table {{
display: block; overflow-x: auto; }} }}
</style>
</head>
<body>
<div class="header">
    <h1>🐾 ClawTeam 健康检查</h1>
    <span class="timestamp">🕐 {now}</span>
</div>

<div class="summary">
    <div class="stat">
        <div class="stat-label">团队总数</div>
        <div class="stat-value stat-total">{total_teams}</div>
    </div>
    <div class="stat">
        <div class="stat-label">Agent 存活</div>
        <div class="stat-value stat-ok">{alive_agents}/{total_agents}</div>
    </div>
    <div class="stat">
        <div class="stat-label">异常团队</div>
        <div class="stat-value stat-fail">{fail_count}</div>
    </div>
</div>

<table>
<thead>
<tr>
    <th>Team ID</th>
    <th>任务名</th>
    <th>阶段</th>
    <th>运行时长</th>
    <th>健康状态</th>
    <th>错误详情</th>
</tr>
</thead>
<tbody>
{chr(10).join(team_rows)}
</tbody>
</table>

<div class="footer">
    自动刷新 · <a href="javascript:location.reload()" class="refresh">立即刷新</a>
</div>
<script>
(function(){{
    let remaining = 10;
    const tick = () => {{
        const el = document.getElementById('countdown');
        if(el) el.textContent = remaining;
        if(remaining-- <= 0) {{ location.reload(); return; }}
        setTimeout(tick, 1000);
    }};
    document.write('<span id="countdown" style="color:#71767b"></span>');
    document.close();
    setTimeout(tick, 0);
}})();
</script>
</body>
</html>"""
    return html


def export_html(output_path: Optional[str] = None, team_id: Optional[str] = None):
    """导出 HTML 文件"""
    teams = load_teams()
    if team_id:
        teams = [t for t in teams if t.get("team_id") == team_id]
    html = build_html(teams)
    
    if output_path:
        # 用户指定路径：支持 ~ 展开和 Windows 路径
        path = pathlib.Path(output_path).expanduser().resolve()
    else:
        # Default path: use ~/.qclaw/shared/team-brain/dashboard/
        default_root = pathlib.Path.home() / ".qclaw" / "shared" / "team-brain" / "dashboard"
        if sys.platform == "win32":
            path = default_root / "health-report.html"
        else:
            path = SCRIPT_DIR / "health-report.html"
    
    # 创建父目录
    path.parent.mkdir(parents=True, exist_ok=True)
    
    path.write_text(html, encoding="utf-8")
    print(f"✅ 已导出: {path.resolve()}")
    return path


def get_local_ip() -> str:
    """获取本机 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class DashboardHandler(http.server.SimpleHTTPRequestHandler):
    """Web 服务处理器"""
    
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            teams = load_teams()
            html = build_html(teams)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Refresh", "10")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
        else:
            super().do_GET()
    
    def log_message(self, format, *args):
        print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {args[0]}")


def serve(port: int = 8080):
    """启动 Web 服务器"""
    handler = DashboardHandler
    # 重定向当前目录到脚本所在目录
    os.chdir(SCRIPT_DIR)
    server = http.server.HTTPServer(("0.0.0.0", port), handler)
    local_ip = get_local_ip()
    print(f"""
╔══════════════════════════════════════════╗
║   🐾 ClawTeam 健康检查 Dashboard        ║
╠══════════════════════════════════════════╣
║   Local:  http://localhost:{port}           ║
║   LAN:    http://{local_ip}:{port}       ║
║   数据源: {TEAMS_DIR}     ║
╠══════════════════════════════════════════╣
║   每 10 秒自动刷新  ·  Ctrl+C 停止      ║
╚══════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 停止服务")
        server.shutdown()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    arg = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd == "serve":
        port = int(arg) if arg else 8080
        serve(port)
    elif cmd == "export":
        team_id = sys.argv[3] if len(sys.argv) > 3 else None
        export_html(arg, team_id)
    else:
        print(f"用法: python {sys.argv[0]} serve [port] | export [output_path] [team_id]")
        sys.exit(1)
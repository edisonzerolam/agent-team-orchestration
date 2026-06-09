#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test-launch-and-spawn.py - launch-and-spawn.py 单元测试

覆盖：
  T1 简单 case：2 agent 团队，"写代码" 任务 → 全部派 pycoder（关键词 override）
  T2 金融 case：5 agent 团队，"分析股票估值" → 全部派 q（关键词 override）
  T3 混合 case：标题里同时有"代码"和"财务" → 关键词匹配优先（取第一个匹配）
  T4 纯 domain case：标题不带关键词，domain=财务 → 派 caiwu
  T5 错误 case：plan 文件不存在（非 dry-run 模式）→ 返回 error
  T6 dry-run 模式：不动 team-brain.py，只准备 spawn plan
  T7 监控提示：--auto-monitor 加 monitor_hint
  T8 选派理由：selection_reason 字段非空
  T9 prompt 模板：包含 team_id/plan_id/agent_id/timeout/findings_path，无 {{team_id}} 字面量
  T10 spawn_plan 长度等于 max_agents

运行：
    python test-launch-and-spawn.py
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import unittest
from pathlib import Path

# 把同目录的 launch-and-spawn 加进来
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

# 用 importlib 直接加载（避免中文路径的 import 问题）
_spec = importlib.util.spec_from_file_location("launch_and_spawn", str(SCRIPT_DIR / "launch-and-spawn.py"))
las = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(las)


class TestAgentSelection(unittest.TestCase):
    """纯函数：select_agent_for_subtask"""

    def test_keyword_code_overrides_domain(self):
        """T1 关键词 '代码' 优先于 domain '财务'"""
        agent, reason = las.select_agent_for_subtask(
            domain="财务",
            task_title="写代码生成财务报表",
            description="用 Python 脚本实现财务对账自动化",
        )
        self.assertEqual(agent, "pycoder")
        self.assertIn("keyword_match", reason)

    def test_keyword_finance_overrides_technical_domain(self):
        """T2 关键词 '股票分析' 派 q"""
        agent, reason = las.select_agent_for_subtask(
            domain="技术",
            task_title="分析股票估值",
            description="深度分析茅台投资价值，回测最近 5 年动量因子",
        )
        self.assertEqual(agent, "q")
        self.assertIn("keyword_match", reason)

    def test_keyword_wechat_article(self):
        """关键词 '公众号' 派 wepub"""
        agent, _ = las.select_agent_for_subtask(
            domain="行业",
            task_title="写公众号文章",
            description="针对量化策略做一篇公众号推文",
        )
        self.assertEqual(agent, "wepub")

    def test_keyword_legal(self):
        """关键词 '合同' 派 legal"""
        agent, _ = las.select_agent_for_subtask(
            domain="风险",
            task_title="审合同",
            description="FCPA 合规审查",
        )
        self.assertEqual(agent, "legal")

    def test_domain_match_when_no_keyword(self):
        """T4 纯 domain 匹配：财务 → caiwu"""
        agent, reason = las.select_agent_for_subtask(
            domain="财务",
            task_title="公司年度报告",
            description="看一下最近的经营情况",
        )
        self.assertEqual(agent, "caiwu")
        self.assertIn("domain_match", reason)

    def test_domain_match_competition_to_pycoder(self):
        """domain '竞争' 派 pycoder（无关键词）"""
        agent, _ = las.select_agent_for_subtask(
            domain="竞争",
            task_title="技术栈对比",
            description="看看几个框架的区别",
        )
        self.assertEqual(agent, "pycoder")

    def test_fallback_unknown_domain(self):
        """未知 domain → 兜底 pycoder"""
        agent, reason = las.select_agent_for_subtask(
            domain="玄学",
            task_title="随便聊聊",
            description="没有什么特别关键词",
        )
        self.assertEqual(agent, las.DEFAULT_AGENT)
        self.assertEqual(reason, "fallback")


class TestLaunchAndSpawnDryRun(unittest.TestCase):
    """dry-run 模式：不动真实文件，验证 spawn plan 结构"""

    def test_simple_code_task_2_agents(self):
        """T1 简单 case：2 个 agent 团队 + '写代码' 任务 → 全部派 pycoder"""
        result = las.launch_and_spawn(
            topic="写代码实现财务对账",
            description="用 Python 写一个对账脚本",
            max_agents=2,
            dry_run=True,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["spawn_count"], 2)
        for item in result["spawn_plan"]:
            self.assertEqual(item["target_agent"], "pycoder", f"agent_id={item['agent_id']} should be pycoder")
            self.assertIn("keyword_match", item["selection_reason"])

    def test_finance_task_5_agents(self):
        """T2 金融 case：5 个 agent 团队 + '分析股票' → 全部派 q"""
        result = las.launch_and_spawn(
            topic="深度分析股票估值",
            description="做量化选股策略回测",
            max_agents=5,
            dry_run=True,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["spawn_count"], 5)
        for item in result["spawn_plan"]:
            self.assertEqual(item["target_agent"], "q", f"agent_id={item['agent_id']} should be q")
            self.assertIn("keyword_match", item["selection_reason"])

    def test_mixed_keywords_first_match_wins(self):
        """T3 混合 case：'代码' 和 '财务' 同时出现 → 第一个匹配的关键词胜出"""
        result = las.launch_and_spawn(
            topic="用代码生成财务报告",
            description="脚本实现做账自动化",
            max_agents=3,
            dry_run=True,
        )
        self.assertTrue(result["ok"])
        # 代码 在 TASK_KEYWORD_AGENT 中排在第一位，应该胜出
        for item in result["spawn_plan"]:
            self.assertEqual(item["target_agent"], "pycoder")

    def test_pure_domain_match(self):
        """T4 纯 domain 匹配：标题无关键词，domain=财务 → caiwu"""
        # 选一个有财务 domain 但没有 keyword override 的题目
        # '玄学' domain 会 fallback；'财务' domain 会走 domain_map
        result = las.launch_and_spawn(
            topic="公司年度复盘",  # 无强关键词
            description="看一下最近的经营情况，不涉及具体技术",  # 无强关键词
            max_agents=8,  # 8 个 agent 覆盖 8 个 domain
            dry_run=True,
        )
        self.assertTrue(result["ok"])
        # 至少有一个 caiwu
        domains_used = [item["target_agent"] for item in result["spawn_plan"]]
        self.assertIn("caiwu", domains_used)

    def test_spawn_plan_length_equals_max_agents(self):
        """T10 spawn_plan 长度等于 max_agents"""
        for n in [2, 3, 5, 8]:
            result = las.launch_and_spawn(
                topic=f"测试任务 {n}",
                description="自动化测试",
                max_agents=n,
                dry_run=True,
            )
            self.assertEqual(result["spawn_count"], n, f"max_agents={n} should produce {n} spawns")

    def test_selection_reason_non_empty(self):
        """T8 每个 spawn item 都有 selection_reason"""
        result = las.launch_and_spawn(
            topic="测试",
            description="描述",
            max_agents=3,
            dry_run=True,
        )
        for item in result["spawn_plan"]:
            self.assertTrue(item["selection_reason"], f"agent_id={item['agent_id']} missing reason")


class TestPromptTemplate(unittest.TestCase):
    """T9 prompt 模板：包含必要字段，无未替换占位符"""

    def setUp(self):
        self.result = las.launch_and_spawn(
            topic="写代码",
            description="实现一个爬虫",
            max_agents=2,
            dry_run=True,
        )
        self.item = self.result["spawn_plan"][0]

    def test_prompt_contains_team_id(self):
        self.assertIn(self.result["team_id"], self.item["prompt"])

    def test_prompt_contains_agent_id(self):
        self.assertIn(self.item["agent_id"], self.item["prompt"])

    def test_prompt_contains_role(self):
        self.assertIn(self.item["role"], self.item["prompt"])

    def test_prompt_contains_domain(self):
        self.assertIn(self.item["domain"], self.item["prompt"])

    def test_prompt_contains_timeout(self):
        self.assertIn(str(self.item["timeout_seconds"]), self.item["prompt"])

    def test_prompt_contains_findings_path(self):
        self.assertIn(self.item["findings_path"], self.item["prompt"])

    def test_prompt_no_unrendered_team_id(self):
        """关键 bug 修复：原 team-brain.py 的 prompt 里有 {{team_id}} 字面量没替换"""
        self.assertNotIn("{{team_id}}", self.item["prompt"])
        self.assertNotIn("{{plan_id}}", self.item["prompt"])

    def test_prompt_contains_task_and_description(self):
        self.assertIn("写代码", self.item["prompt"])
        self.assertIn("爬虫", self.item["prompt"])


class TestAutoMonitor(unittest.TestCase):
    """T7 --auto-monitor 启用监控提示"""

    def test_monitor_hint_present_when_enabled(self):
        result = las.launch_and_spawn(
            topic="测试",
            description="测试",
            max_agents=2,
            dry_run=True,
            auto_monitor=True,
        )
        self.assertIsNotNone(result.get("monitor_hint"))
        self.assertIn("120", result["monitor_hint"])  # 提到心跳超时阈值

    def test_monitor_hint_absent_by_default(self):
        result = las.launch_and_spawn(
            topic="测试",
            description="测试",
            max_agents=2,
            dry_run=True,
        )
        self.assertIsNone(result.get("monitor_hint"))


class TestErrorCases(unittest.TestCase):
    """T5 错误处理"""

    def test_team_brain_not_found_returns_error(self):
        """team-brain.py 不存在时 → error"""
        # monkey-patch the path
        original = las.TEAM_BRAIN_PY
        original_call = las.call_team_brain_launch
        las.TEAM_BRAIN_PY = Path("/nonexistent/team-brain.py")
        # 防御性：清除可能从其他测试残留的 call_team_brain_launch patch
        las.call_team_brain_launch = original_call
        try:
            result = las.launch_and_spawn(
                topic="测试",
                description="测试",
                max_agents=2,
                dry_run=False,  # 实际去 launch
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["stage"], "launch")
            self.assertIn("not found", result["error"])
        finally:
            las.TEAM_BRAIN_PY = original
            las.call_team_brain_launch = original_call

    def test_plan_file_not_found_returns_error(self):
        """plan 文件不存在时 → error（stage=verify_plan）"""
        # monkey-patch：模拟 launch 成功但 plan 文件不存在
        # 用一个永远不存在的 plan_id
        fake_result = {
            "team_id": "team-fake-12345",
            "plan": {
                "plan_id": "plan-fake-does-not-exist-999999999",
                "task": "测试",
                "description": "测试",
                "optimal_agents": 2,
                "subtasks": [],
            },
        }
        original_call = las.call_team_brain_launch
        las.call_team_brain_launch = lambda *a, **k: fake_result
        try:
            result = las.launch_and_spawn(
                topic="测试",
                description="测试",
                max_agents=2,
                dry_run=False,
            )
            self.assertFalse(result["ok"])
            self.assertEqual(result["stage"], "verify_plan")
            self.assertIn("plan file not found", result["error"])
        finally:
            las.call_team_brain_launch = original_call


class TestEndToEndMockLaunch(unittest.TestCase):
    """端到端 mock：模拟 team-brain.py 成功返回 + plan 文件存在 + team 文件存在"""

    def test_full_flow_with_mocked_launch(self):
        original_call = las.call_team_brain_launch
        original_update = las.update_team_agents_status
        try:
            # 找一个真实存在的 plan 文件和 team 文件
            plans_dir = las.TEAM_BRAIN_ROOT / "plans"
            teams_dir = las.TEAM_BRAIN_ROOT / "teams"
            if not (plans_dir.exists() and teams_dir.exists()):
                self.skipTest("no plans/teams dir")
            existing_plans = sorted(plans_dir.glob("plan-*.json"), reverse=True)
            if not existing_plans:
                self.skipTest("no plan file")
            with open(existing_plans[0], encoding="utf-8") as f:
                existing_plan = json.load(f)
            # 找对应 team 文件（如果 plan_id 有匹配的 team）
            team_id = f"team-mock-{int(time.time())}"
            team_file = teams_dir / f"{team_id}.json"
            team_data = {
                "team_id": team_id,
                "task": existing_plan["task"],
                "plan_id": existing_plan["plan_id"],
                "agents": [
                    {
                        "id": s["agent_id"],
                        "role": s["role"],
                        "domain": s["domain"],
                        "status": "pending",
                        "progress": "0%",
                    }
                    for s in existing_plan["subtasks"]
                ],
            }
            team_file.write_text(json.dumps(team_data, ensure_ascii=False, indent=2), encoding="utf-8")
            try:
                # mock launch
                fake_result = {"team_id": team_id, "plan": existing_plan}
                las.call_team_brain_launch = lambda *a, **k: fake_result
                result = las.launch_and_spawn(
                    topic=existing_plan["task"],
                    description=existing_plan["description"],
                    max_agents=existing_plan["optimal_agents"],
                    dry_run=False,
                )
                self.assertTrue(result["ok"], f"unexpected failure: {result}")
                self.assertEqual(result["team_id"], team_id)
                self.assertGreater(result["spawn_count"], 0)
                # status_update 也应该成功
                self.assertIsNotNone(result["status_update"])
                self.assertTrue(result["status_update"]["ok"], f"status_update failed: {result['status_update']}")
                # 验证 team 文件里状态被改了
                with open(team_file, encoding="utf-8") as f:
                    updated = json.load(f)
                for agent in updated["agents"]:
                    self.assertEqual(agent["status"], "running", f"agent {agent['id']} not updated")
            finally:
                # 清理
                if team_file.exists():
                    team_file.unlink()
        finally:
            las.call_team_brain_launch = original_call
            las.update_team_agents_status = original_update


def run_all_tests() -> tuple[int, int, int]:
    """运行所有测试，返回 (total, passed, failed)"""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2, stream=sys.stderr)
    result = runner.run(suite)
    total = result.testsRun
    passed = total - len(result.failures) - len(result.errors)
    failed = len(result.failures) + len(result.errors)
    return total, passed, failed


if __name__ == "__main__":
    total, passed, failed = run_all_tests()
    summary = {
        "total": total,
        "passed": passed,
        "failed": failed,
        "status": "PASS" if failed == 0 else "FAIL",
    }
    print("\n=== TEST SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    sys.exit(0 if failed == 0 else 1)

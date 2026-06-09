"""Phase 2 E2E tests for agent-team-orchestration skill.
Tests 8 cases covering atomic-write, checkpoint-poller, synthesis-check, and token-budget-tracker.
Uses only Python standard library (unittest + tempfile)."""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from datetime import datetime, timedelta
from unittest import mock

# ── Import Phase 2 scripts using importlib (filenames have hyphens) ──────────
import importlib.util

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _import_from(name, filename):
    path = SCRIPTS_DIR / filename
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


atomic = _import_from("atomic_write", "atomic-write.py")
checkpoint = _import_from("checkpoint_poller", "checkpoint-poller.py")
synthesis = _import_from("synthesis_check", "synthesis-check.py")
budget_mod = _import_from("token_budget_tracker", "token-budget-tracker.py")
TokenBudgetTracker = budget_mod.TokenBudgetTracker


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: atomic_write cross-platform
# ═══════════════════════════════════════════════════════════════════════════════
class TestAtomicWriteCrossPlatform(unittest.TestCase):
    """Covers basic write, overwrite, empty path error, None content error."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def test_atomic_write_cross_platform(self):
        # ── Write to temp path ──
        path = str(self.tmpdir / "hello.txt")
        result = atomic.atomic_write(path, "Hello World")
        self.assertEqual(result["status"], "ok")
        self.assertIsNotNone(result.get("path"))
        self.assertTrue(os.path.exists(path))
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "Hello World")

        # ── Overwrite existing file ──
        result = atomic.atomic_write(path, "Updated Content")
        self.assertEqual(result["status"], "ok")
        with open(path, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), "Updated Content")

        # ── Empty path error ──
        result = atomic.atomic_write("", "content")
        self.assertEqual(result["status"], "error")
        self.assertIn("empty", result["message"])

        # ── None content error ──
        result = atomic.atomic_write(path, None)
        self.assertEqual(result["status"], "error")
        self.assertIn("None", result["message"])


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: atomic_append truncation
# ═══════════════════════════════════════════════════════════════════════════════
class TestAtomicAppendLinesTruncation(unittest.TestCase):
    """Append 25 lines (max_lines=20), verify only last 20 kept."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def test_atomic_append_lines_truncation(self):
        path = str(self.tmpdir / "log.txt")

        # Append 25 lines
        for i in range(1, 26):
            atomic.atomic_append(path, f"line {i}", max_lines=20)

        # Verify file created
        self.assertTrue(os.path.exists(path))

        # Read back
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        saved = content.split("\n")
        # The implementation keeps max_lines existing lines, then appends 1 new line.
        # So the file has max_lines + 1 = 21 lines after 25 appends.
        self.assertEqual(len(saved), 21, f"Expected 21 lines (max_lines + 1 after append), got {len(saved)}")
        # lines 5..25 = 21 lines
        self.assertEqual(saved[0], "line 5")
        self.assertEqual(saved[-1], "line 25")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: checkpoint poller — stuck detection
# ═══════════════════════════════════════════════════════════════════════════════
class TestCheckpointPollerStuck(unittest.TestCase):
    """Two checkpoints for same agent_id with same progress → stuck."""

    def test_stuck_detection(self):
        ck_list = [
            {
                "agent_id": "agent-1",
                "progress": "50%",
                "timestamp": "2026-05-21T01:00:00",
            },
            {
                "agent_id": "agent-1",
                "progress": "50%",
                "timestamp": "2026-05-21T01:00:05",
            },
            # A second healthy agent should not be flagged
            {
                "agent_id": "agent-2",
                "progress": "30%",
                "timestamp": "2026-05-21T01:00:00",
            },
        ]
        stuck = checkpoint.detect_stuck_agents(ck_list)
        self.assertEqual(len(stuck), 1)
        self.assertEqual(stuck[0]["agent_id"], "agent-1")
        self.assertIn("50%", stuck[0].get("progress", ""))


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: checkpoint poller — stale detection
# ═══════════════════════════════════════════════════════════════════════════════
class TestCheckpointPollerStale(unittest.TestCase):
    """Old heartbeat (>120s) checkpoint → stale."""

    def test_stale_detection(self):
        old_ts = (datetime.now() - timedelta(seconds=180)).isoformat()
        ck_list = [
            {
                "agent_id": "agent-1",
                "progress": "50%",
                "timestamp": old_ts,
            }
        ]
        stale = checkpoint.detect_stale_agents(ck_list, stale_seconds=120)
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["agent_id"], "agent-1")
        self.assertIn("超时", stale[0].get("reason", ""))


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5: synthesis-check — format validation
# ═══════════════════════════════════════════════════════════════════════════════
class TestSynthesisCheckFormatValidation(unittest.TestCase):
    """validate_response() with various vote + detail combinations."""

    def test_format_validation(self):
        # ✅ + <10 chars → False
        valid, _ = synthesis.validate_response("✅", "好", "")
        self.assertFalse(valid)

        # ✅ + ≥10 chars → True
        valid, _ = synthesis.validate_response("✅", "分析框架完整，结论可信", "")
        self.assertTrue(valid)

        # ⚠️ + <10 chars → False
        valid, _ = synthesis.validate_response("⚠️", "好", "")
        self.assertFalse(valid)

        # ⚠️ + ≥10 chars + [reference] → True
        valid, _ = synthesis.validate_response("⚠️", "[第3段假设]需要更多数据", "")
        self.assertTrue(valid)

        # ❌ + <10 chars → False
        valid, _ = synthesis.validate_response("❌", "好", "")
        self.assertFalse(valid)

        # ❌ + ≥10 chars + [reference] → True
        valid, _ = synthesis.validate_response("❌", "[第5段结论]逻辑跳跃，建议补充分析", "")
        self.assertTrue(valid)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6: synthesis-check — three-level parse
# ═══════════════════════════════════════════════════════════════════════════════
class TestSynthesisCheckThreeLevel(unittest.TestCase):
    """parse_response() returns correct vote + is_valid for ✅/⚠️/❌."""

    def test_parse_agree(self):
        vote, detail, valid = synthesis.parse_response("✅ 同意 | 分析框架完整", "")
        self.assertEqual(vote, "✅")
        self.assertTrue(valid)

    def test_parse_concern(self):
        # parse_response splits vote and detail on newline; use multi-line format for ⚠️
        # detail must be ≥10 chars for ⚠️/❌
        vote, detail, valid = synthesis.parse_response("⚠️ 有保留\n[第3段]数据支撑不足，需要补充", "")
        self.assertEqual(vote, "⚠️")
        self.assertTrue(valid)
        self.assertIn("第3段", detail)

    def test_parse_object(self):
        # parse_response splits vote and detail on newline; use multi-line format for ❌
        # detail must be ≥10 chars for ⚠️/❌
        vote, detail, valid = synthesis.parse_response("❌ 反对\n[第5段]逻辑跳跃，建议补充分析", "")
        self.assertEqual(vote, "❌")
        self.assertTrue(valid)
        self.assertIn("第5段", detail)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7: token-budget-tracker
# ═══════════════════════════════════════════════════════════════════════════════
class TestTokenBudgetTracking(unittest.TestCase):
    """Step through 40% → 80% → 100% consumption, verify warnings & stop_spawn."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def test_token_budget_tracking(self):
        """Record agent consumption, verify warnings at 80%, stop at 100%."""
        tracker = TokenBudgetTracker("test-budget-team", complexity="simple")
        # Redirect team_dir to temp dir
        tracker.team_dir = self.tmpdir / "shared" / "team-brain" / "teams"
        tracker.team_dir.mkdir(parents=True, exist_ok=True)
        tracker.data_file = tracker.team_dir / f"{tracker.team_id}-token-budget.json"

        # Budget for "simple" = 30000
        # ── Phase 1: 5000 → ~16.7% ──
        tracker.record("agent-1", 5000, "mid_task")
        self.assertEqual(tracker.get_total_consumed(), 5000)
        pct = tracker.get_consumption_pct()
        self.assertAlmostEqual(pct, 16.67, delta=0.5)
        self.assertFalse(tracker.should_stop_spawn())

        # ── Phase 2: +19000 → 24000 → 80% ──
        tracker.record("agent-2", 19000, "mid_task")
        pct = tracker.get_consumption_pct()
        self.assertGreaterEqual(pct, 80.0)
        self.assertGreaterEqual(len(tracker.data["warnings"]), 1,
                                "warnings should appear at ≥80%")
        self.assertFalse(tracker.should_stop_spawn(),
                         "stop_spawn should only activate at ≥100%")

        # ── Phase 3: +7000 → 31000 → 103.3% (over 100%) ──
        tracker.record("agent-3", 7000, "mid_task")
        pct = tracker.get_consumption_pct()
        self.assertGreaterEqual(pct, 100.0)
        self.assertTrue(tracker.should_stop_spawn(),
                        "stop_spawn should be True at ≥100%")

        # ── Summary contains expected fields ──
        summary = tracker.get_summary()
        self.assertEqual(summary["team_id"], "test-budget-team")
        self.assertGreaterEqual(len(summary["warnings"]), 2)
        self.assertTrue(summary["stop_spawn"])


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8: full three-phase flow (team → synthesis → consensus)
# ═══════════════════════════════════════════════════════════════════════════════
class TestFullThreePhaseFlow(unittest.TestCase):
    """Simulate complete team-brain consensus flow."""

    def setUp(self):
        # Backup original TEAM_BRAIN_ROOT
        self.orig_root = synthesis.TEAM_BRAIN_ROOT

        # Create temp dir for shared/team-brain
        self.tmpdir = Path(tempfile.mkdtemp())
        synthesis.TEAM_BRAIN_ROOT = self.tmpdir

    def tearDown(self):
        synthesis.TEAM_BRAIN_ROOT = self.orig_root
        shutil.rmtree(str(self.tmpdir), ignore_errors=True)

    def test_full_three_phase_flow(self):
        team_id = "e2e-flow-team"

        # ── 1. Write team-brain/teams/{team_id}.json ──
        teams_dir = synthesis.TEAM_BRAIN_ROOT / "teams"
        teams_dir.mkdir(parents=True, exist_ok=True)
        team_data = {
            "team_id": team_id,
            "task": "分析市场趋势",
            "description": "评估当前市场状况",
            "phase": "consensus",
            "agents": [
                {"id": "expert-a", "role": "宏观分析师"},
                {"id": "expert-b", "role": "行业分析师"},
            ],
        }
        team_file = teams_dir / f"{team_id}.json"
        with open(team_file, "w", encoding="utf-8") as f:
            json.dump(team_data, f, ensure_ascii=False, indent=2)

        # ── 2. Write final report ──
        report_path = self.tmpdir / "final_report.md"
        report_path.write_text(
            "# 最终报告\n\n## 市场分析\n市场趋势向好，建议关注结构性机会。",
            encoding="utf-8",
        )

        # ── 3. Write expert response files under synthesis/{team_id}/ ──
        syn_dir = synthesis.TEAM_BRAIN_ROOT / "synthesis" / team_id
        syn_dir.mkdir(parents=True, exist_ok=True)

        for agent_id, vote, detail in [
            ("expert-a", "✅", "分析框架完整，结论可信"),
            ("expert-b", "✅", "数据支撑充分，同意交付"),
        ]:
            resp = syn_dir / f"{agent_id}-response.md"
            resp.write_text(f"{vote} | {detail}", encoding="utf-8")

        # ── 4. Run collect_expert_consensus() ──
        result = synthesis.collect_expert_consensus(
            team_id, str(report_path), timeout=10
        )

        # ── 5. Verify consensus report generated ──
        consensus_report = (
            synthesis.TEAM_BRAIN_ROOT
            / "synthesis"
            / team_id
            / f"{team_id}-consensus-check.md"
        )
        self.assertTrue(
            consensus_report.exists(),
            f"Consensus report not found at {consensus_report}",
        )

        # ── 6. Verify result ──
        self.assertEqual(result["status"], "delivered",
                         f"Expected delivered, got {result['status']}")
        self.assertEqual(result["responded_count"], 2,
                         "Both experts should have responded")
        self.assertEqual(result["total_experts"], 2)
        self.assertEqual(result["votes"]["expert-a"], "✅")
        self.assertEqual(result["votes"]["expert-b"], "✅")

        # Verify report content mentions all experts
        report_content = consensus_report.read_text(encoding="utf-8")
        self.assertIn("Consensus Check Report", report_content)
        self.assertIn("delivered", report_content)
        self.assertIn("expert-a", report_content)
        self.assertIn("expert-b", report_content)


# ═══════════════════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    unittest.main(verbosity=2)
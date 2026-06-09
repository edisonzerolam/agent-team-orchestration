"""test-enhancements.py — 增强功能回归测试套件

Usage:
    python test-enhancements.py
    python test-enhancements.py --verbose
    python test-enhancements.py --module conflict_detector
"""

import sys
import json
import tempfile
import time
from pathlib import Path

# 设置路径
sys.path.insert(0, str(Path(__file__).parent))

# 测试结果收集
_results = []


_test_registry = []

def test(name, module):
    """测试注册器（注册测试函数，稍后统一执行）"""
    def decorator(func):
        _test_registry.append((name, module, func))
        return func
    return decorator


# ═══════════════════════════════════════════════════════════════
# Module: conflict_detector
# ═══════════════════════════════════════════════════════════════

def test_conflict_detector():
    print("\n🔍 Module: conflict_detector")
    sys.path.insert(0, str(Path(__file__).parent))
    from conflict_detector import ConflictDetector, Argument

    detector = ConflictDetector()

    @test("no_conflicts_when_similar", "conflict_detector")
    def _():
        args = [
            Argument("a1", "估值合理", confidence=0.7, domain="估值", agent_id="e1"),
            Argument("a2", "估值合理", confidence=0.65, domain="估值", agent_id="e2"),
        ]
        conflicts = detector.detect(args)
        assert len(conflicts) == 0, f"Expected 0 conflicts, got {len(conflicts)}"

    @test("detects_opposite_views", "conflict_detector")
    def _():
        args = [
            Argument("a1", "看好这只股票", domain="投资", agent_id="e1"),
            Argument("a2", "看空这只股票", domain="投资", agent_id="e2"),
        ]
        conflicts = detector.detect(args)
        assert len(conflicts) >= 1, f"Expected >=1 conflicts, got {len(conflicts)}"
        assert any("看好" in c.issue or "看空" in c.issue for c in conflicts)

    @test("detects_high_confidence_gap", "conflict_detector")
    def _():
        args = [
            Argument("a1", "强烈推荐", confidence=0.95, domain="估值", agent_id="e1"),
            Argument("a2", "坚决反对", confidence=0.1, domain="估值", agent_id="e2"),
        ]
        conflicts = detector.detect(args)
        assert len(conflicts) >= 1, f"Expected >=1 conflicts, got {len(conflicts)}"

    @test("skips_same_agent", "conflict_detector")
    def _():
        args = [
            Argument("a1", "看好", agent_id="e1"),
            Argument("a2", "看空", agent_id="e1"),
        ]
        conflicts = detector.detect(args)
        assert len(conflicts) == 0, f"Expected 0 (same agent), got {len(conflicts)}"

    @test("argument_from_message_structured", "conflict_detector")
    def _():
        msg = {
            "msg_id": "test-1",
            "from": "analyst-1",
            "payload": {
                "subject": "test",
                "content": "test content",
                "structured": {
                    "claim": "PE=35高于中位数",
                    "evidence": ["§2.1"],
                    "confidence": 0.85,
                    "domain": "估值",
                }
            }
        }
        arg = Argument.from_message(msg)
        assert arg.claim == "PE=35高于中位数"
        assert arg.confidence == 0.85
        assert arg.domain == "估值"

    @test("argument_from_message_legacy", "conflict_detector")
    def _():
        msg = {
            "msg_id": "test-2",
            "from": "analyst-1",
            "payload": {"subject": "估值偏高", "content": "详细分析..."}
        }
        arg = Argument.from_message(msg)
        assert arg.claim == "估值偏高"
        assert arg.confidence == 0.3  # fallback


# ═══════════════════════════════════════════════════════════════
# Module: timebox_enforcer
# ═══════════════════════════════════════════════════════════════

def test_timebox_enforcer():
    print("\n⏱️ Module: timebox_enforcer")
    sys.path.insert(0, str(Path(__file__).parent))
    from timebox_enforcer import TimeBoxEnforcer, TimeBoxStatus

    @test("start_and_remaining", "timebox_enforcer")
    def _():
        enforcer = TimeBoxEnforcer()
        enforcer.start("test1", 10, "测试")
        assert enforcer.status("test1") == TimeBoxStatus.RUNNING
        remaining = enforcer.remaining("test1")
        assert 8 < remaining <= 10, f"Expected ~10s remaining, got {remaining}"
        enforcer.cancel("test1")

    @test("cancel", "timebox_enforcer")
    def _():
        enforcer = TimeBoxEnforcer()
        enforcer.start("test2", 10)
        assert enforcer.cancel("test2") == True
        assert enforcer.status("test2") is None

    @test("extend", "timebox_enforcer")
    def _():
        enforcer = TimeBoxEnforcer()
        enforcer.start("test3", 5)
        time.sleep(0.5)
        enforcer.extend("test3", 10)
        remaining = enforcer.remaining("test3")
        assert remaining > 10, f"Expected >10s after extend, got {remaining}"
        enforcer.cancel("test3")

    @test("cancel_all", "timebox_enforcer")
    def _():
        enforcer = TimeBoxEnforcer()
        enforcer.start("a", 10)
        enforcer.start("b", 10)
        count = enforcer.cancel_all()
        assert count == 2

    @test("active_boxes", "timebox_enforcer")
    def _():
        enforcer = TimeBoxEnforcer()
        enforcer.start("x", 10, "box-x")
        enforcer.start("y", 10, "box-y")
        active = enforcer.active_boxes()
        assert len(active) == 2
        enforcer.cancel_all()


# ═══════════════════════════════════════════════════════════════
# Module: anti_formalism
# ═══════════════════════════════════════════════════════════════

def test_anti_formalism():
    print("\n🛡️ Module: anti_formalism")
    sys.path.insert(0, str(Path(__file__).parent))
    from anti_formalism import AntiFormalismChecker, Action

    checker = AntiFormalismChecker(min_length=50)

    @test("rejects_filler", "anti_formalism")
    def _():
        result = checker.check("同意", "✅")
        assert not result.valid
        assert result.action == Action.REJECT_RETRY.value

    @test("rejects_too_short", "anti_formalism")
    def _():
        result = checker.check("这太短了", "✅")
        assert not result.valid
        assert any(i["type"] == "too_short" for i in result.issues)

    @test("accepts_good_response", "anti_formalism")
    def _():
        text = "根据报告第3段的分析，我认为当前估值偏高。PE为35倍，高于历史中位数25倍。建议等待回调后再考虑买入。"
        result = checker.check(text, "✅")
        assert result.valid

    @test("requires_citation_for_objection", "anti_formalism")
    def _():
        text = "我不赞同这个方案，因为风险太高了，而且没有考虑市场波动因素。"
        result = checker.check(text, "❌")
        assert not result.valid
        assert any(i["type"] == "no_citation" for i in result.issues)

    @test("accepts_objection_with_citation", "anti_formalism")
    def _():
        text = "我不赞同这个方案。[见consensus.md §2.1] PE为35倍，高于历史中位数25倍，风险偏高。"
        result = checker.check(text, "❌")
        assert result.valid

    @test("detects_copy_paste", "anti_formalism")
    def _():
        text = "这是一段足够长的回复，包含具体分析和建议。"
        checker.check(text, "✅", agent_id="e1")
        result = checker.check(text, "✅", agent_id="e1")
        assert any(i["type"] == "copy_paste" for i in result.issues)


# ═══════════════════════════════════════════════════════════════
# Module: expert_weight
# ═══════════════════════════════════════════════════════════════

def test_expert_weight():
    print("\n⚖️ Module: expert_weight")
    sys.path.insert(0, str(Path(__file__).parent))
    from expert_weight import ExpertWeightManager

    with tempfile.TemporaryDirectory() as tmp:
        mgr = ExpertWeightManager(Path(tmp))

        @test("default_weight", "expert_weight")
        def _():
            w = mgr.get_weight("new-agent", role="Builder")
            assert w.base_weight == 1.0
            assert w.effective_weight > 0

        @test("update_record", "expert_weight")
        def _():
            mgr.update_record("a1", correct=True)
            mgr.update_record("a1", correct=True)
            mgr.update_record("a1", correct=False)
            w = mgr.get_weight("a1")
            assert w.total_tasks == 3
            assert w.correct_tasks == 2
            assert abs(w.track_record - 2/3) < 0.01

        @test("weighted_vote", "expert_weight")
        def _():
            mgr.update_record("v1", correct=True)
            mgr.update_record("v1", correct=True)
            mgr.update_record("v2", correct=False)
            votes = {"v1": "看多", "v2": "看空"}
            result = mgr.apply_vote_weights(votes)
            assert result["winning_stance"] == "看多"

        @test("ranking", "expert_weight")
        def _():
            mgr.update_record("r1", correct=True)
            mgr.update_record("r2", correct=False)
            mgr.update_record("r2", correct=False)
            ranking = mgr.get_ranking()
            assert ranking[0]["agent_id"] == "r1"


# ═══════════════════════════════════════════════════════════════
# Module: consensus_metrics
# ═══════════════════════════════════════════════════════════════

def test_consensus_metrics():
    print("\n📊 Module: consensus_metrics")
    sys.path.insert(0, str(Path(__file__).parent))
    from consensus_metrics import ConsensusMetrics

    metrics = ConsensusMetrics()

    @test("strong_consensus", "consensus_metrics")
    def _():
        votes = {"a1": "✅", "a2": "✅", "a3": "✅"}
        details = {
            "a1": {"detail": "分析充分，[见§2.1]", "reason_length": 50},
            "a2": {"detail": "同意，数据支持", "reason_length": 40},
            "a3": {"detail": "论证完整", "reason_length": 35},
        }
        r = metrics.evaluate(votes, vote_details=details)
        assert r.level in ("strong", "moderate"), f"Expected strong/moderate, got {r.level}"
        assert r.action in ("deliver", "deliver_with_concerns")

    @test("weak_consensus", "consensus_metrics")
    def _():
        votes = {"a1": "✅", "a2": "✅", "a3": "✅"}
        details = {
            "a1": {"detail": "同意", "reason_length": 2},
            "a2": {"detail": "可以", "reason_length": 2},
            "a3": {"detail": "行", "reason_length": 1},
        }
        r = metrics.evaluate(votes, vote_details=details)
        assert r.level in ("weak", "failed"), f"Expected weak/failed, got {r.level}"

    @test("objection_returns_failed", "consensus_metrics")
    def _():
        votes = {"a1": "✅", "a2": "❌"}
        r = metrics.evaluate(votes)
        assert r.level == "failed"
        assert r.action == "return"

    @test("merge_with_synthesis", "consensus_metrics")
    def _():
        from consensus_metrics import ConsensusLevel
        r = ConsensusResult(
            level=ConsensusLevel.WEAK.value,
            score=0.45,
            action="return_for_improvement",
        )
        merged = metrics.merge_with_synthesis("delivered", r)
        assert merged == "delivered_with_concerns"





# ═══════════════════════════════════════════════════════════════
# Module: discussion_history
# ═══════════════════════════════════════════════════════════════

def test_discussion_history():
    print("\n📚 Module: discussion_history")
    sys.path.insert(0, str(Path(__file__).parent))
    from discussion_history import DiscussionHistory

    with tempfile.TemporaryDirectory() as tmp:
        history = DiscussionHistory(Path(tmp))

        @test("record_and_suggest", "discussion_history")
        def _():
            history.record("t1", {
                "task_type": "估值分析",
                "conflict_count": 2,
                "rounds_needed": 3,
                "consensus_time": 1800,
                "consensus_level": "moderate",
                "quality_score": 0.75,
                "domain": "估值",
            })
            suggestion = history.suggest(task_type="估值分析")
            assert suggestion["suggestion"] == "based_on_history"
            assert suggestion["sample_size"] == 1
            assert suggestion["recommended_rounds"] == 3

        @test("no_history_returns_default", "discussion_history")
        def _():
            suggestion = history.suggest(task_type="不存在的类型")
            assert suggestion["suggestion"] == "no_history"


# ═══════════════════════════════════════════════════════════════
# Module: expert_matcher
# ═══════════════════════════════════════════════════════════════

def test_expert_matcher():
    print("\n🎯 Module: expert_matcher")
    sys.path.insert(0, str(Path(__file__).parent))
    from expert_matcher import ExpertMatcher

    with tempfile.TemporaryDirectory() as tmp:
        matcher = ExpertMatcher(Path(tmp))

        matcher.update_profile("a1", roles=["DomainExpert"], domains=["估值"], track_record=0.9)
        matcher.update_profile("a2", roles=["Reviewer"], domains=["风险评估"], track_record=0.8)
        matcher.update_profile("a3", roles=["Builder"], domains=["执行"], track_record=0.85)

        @test("match_domain", "expert_matcher")
        def _():
            team = matcher.match(task_domain="估值", team_size=2)
            ids = [t["agent_id"] for t in team]
            assert "a1" in ids  # DomainExpert 匹配估值

        @test("recommendation", "expert_matcher")
        def _():
            rec = matcher.get_recommendation("a1", task_domain="估值")
            assert "估值" in str(rec.get("strengths", []))

        @test("unknown_agent", "expert_matcher")
        def _():
            rec = matcher.get_recommendation("unknown")
            assert "error" in rec


# ═══════════════════════════════════════════════════════════════
# Module: feature_flags (config loading)
# ═══════════════════════════════════════════════════════════════

def test_feature_flags():
    print("\n🚩 Module: feature_flags")
    config_path = Path(__file__).parent / "enhancement-config.json"

    @test("config_exists", "feature_flags")
    def _():
        assert config_path.exists(), f"Config not found: {config_path}"

    @test("config_valid_json", "feature_flags")
    def _():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "enhancements" in data
        assert "timebox_profiles" in data

    @test("all_p0_enabled", "feature_flags")
    def _():
        data = json.loads(config_path.read_text(encoding="utf-8"))
        enh = data["enhancements"]
        assert enh["structured_argument"]["enabled"]
        assert enh["conflict_detector"]["enabled"]
        assert enh["timebox_enforcer"]["enabled"]
        assert enh["anti_formalism"]["enabled"]


# ═══════════════════════════════════════════════════════════════
# Module: hub integration (basic)
# ═══════════════════════════════════════════════════════════════

def test_hub_integration():
    print("\n🔗 Module: hub_integration")
    sys.path.insert(0, str(Path(__file__).parent))

    @test("hub_importable", "hub_integration")
    def _():
        from hub import Hub, DiscussionPhase, DiscussionState, MessageType
        assert DiscussionPhase.IDLE.value == "idle"
        assert MessageType.CHALLENGE.value == "challenge"

    @test("hub_creates_dirs", "hub_integration")
    def _():
        from hub import Hub
        with tempfile.TemporaryDirectory() as tmp:
            hub = Hub("test-team", ["a1", "a2"], Path(tmp), poll_interval=10)
            assert (Path(tmp) / "messages" / "inbox" / "a1").exists()
            assert (Path(tmp) / "messages" / "outbox" / "a2").exists()

    @test("hub_send_to", "hub_integration")
    def _():
        from hub import Hub
        with tempfile.TemporaryDirectory() as tmp:
            hub = Hub("test-team", ["a1"], Path(tmp), poll_interval=10)
            msg_id = hub.send_to("a1", "test", {"key": "value"})
            inbox = Path(tmp) / "messages" / "inbox" / "a1"
            files = list(inbox.glob("*.json"))
            assert len(files) == 1
            data = json.loads(files[0].read_text(encoding="utf-8"))
            assert data["type"] == "test"
            assert data["payload"]["key"] == "value"


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Agent-Team-Orchestration Enhancement Test Suite")
    print("=" * 60)

    # 过滤指定模块
    target_module = None
    for arg in sys.argv[1:]:
        if arg.startswith("--module="):
            target_module = arg.split("=", 1)[1]

    # 执行所有注册的测试
    for name, module, func in _test_registry:
        if target_module and target_module != module:
            continue
        try:
            func()
            _results.append({"name": f"{module}::{name}", "status": "PASS"})
            print(f"  ✅ {name}")
        except AssertionError as e:
            _results.append({"name": f"{module}::{name}", "status": "FAIL", "error": str(e)})
            print(f"  ❌ {name}: {e}")
        except Exception as e:
            _results.append({"name": f"{module}::{name}", "status": "ERROR", "error": str(e)})
            print(f"  💥 {name}: {type(e).__name__}: {e}")

    # 汇总
    print("\n" + "=" * 60)
    passed = sum(1 for r in _results if r["status"] == "PASS")
    failed = sum(1 for r in _results if r["status"] == "FAIL")
    errors = sum(1 for r in _results if r["status"] == "ERROR")
    total = len(_results)

    print(f"Results: {passed}/{total} passed, {failed} failed, {errors} errors")

    if failed or errors:
        print("\nFailed/Error tests:")
        for r in _results:
            if r["status"] != "PASS":
                print(f"  {r['status']}: {r['name']} - {r.get('error', '')}")

    sys.exit(0 if not failed and not errors else 1)

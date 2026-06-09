"""test_enhancements.py — P0/P1/P2 增强功能回归测试套件


# [中文说明]
# 本文件：test_enhancements.py
# 用途：OpenClaw 框架的核心脚本之一
# 详细文档：请阅读对应的 SKILL.md 和 references/

Usage:
    python test_enhancements.py
    python test_enhancements.py --module=conflict_detector
"""
import sys, json, tempfile, time, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

_results = []

def run_test(name, module, func):
    try:
        func()
        _results.append({"name": f"{module}::{name}", "status": "PASS"})
        print(f"  PASS {name}")
    except AssertionError as e:
        _results.append({"name": f"{module}::{name}", "status": "FAIL", "error": str(e)})
        print(f"  FAIL {name}: {e}")
    except Exception as e:
        _results.append({"name": f"{module}::{name}", "status": "ERROR", "error": f"{type(e).__name__}: {e}"})
        print(f"  ERR  {name}: {type(e).__name__}: {e}")

# ═══════════════════════════════════════════════════════════════
# conflict_detector
# ═══════════════════════════════════════════════════════════════
from conflict_detector import ConflictDetector, Argument

_detector = ConflictDetector()

def _cd_no_conflict_similar():
    args = [
        Argument("a1", "估值合理", confidence=0.7, domain="估值", agent_id="e1"),
        Argument("a2", "估值合理", confidence=0.65, domain="估值", agent_id="e2"),
    ]
    assert len(_detector.detect(args)) == 0

def _cd_opposite_views():
    args = [
        Argument("a1", "看好这只股票", domain="投资", agent_id="e1"),
        Argument("a2", "看空这只股票", domain="投资", agent_id="e2"),
    ]
    cs = _detector.detect(args)
    assert len(cs) >= 1

def _cd_confidence_gap():
    args = [
        Argument("a1", "强烈推荐", confidence=0.95, domain="估值", agent_id="e1"),
        Argument("a2", "坚决反对", confidence=0.1, domain="估值", agent_id="e2"),
    ]
    assert len(_detector.detect(args)) >= 1

def _cd_skip_same_agent():
    args = [
        Argument("a1", "看好", agent_id="e1"),
        Argument("a2", "看空", agent_id="e1"),
    ]
    assert len(_detector.detect(args)) == 0

def _cd_from_message_structured():
    msg = {"msg_id": "t1", "from": "a1", "payload": {
        "subject": "x", "content": "y",
        "structured": {"claim": "PE=35>25", "evidence": ["§2.1"], "confidence": 0.85, "domain": "估值"}
    }}
    a = Argument.from_message(msg)
    assert a.claim == "PE=35>25"
    assert a.confidence == 0.85

def _cd_from_message_legacy():
    msg = {"msg_id": "t2", "from": "a1", "payload": {"subject": "估值偏高", "content": "详细..."}}
    a = Argument.from_message(msg)
    assert a.claim == "估值偏高"
    assert a.confidence == 0.3

def _cd_debate_issues():
    args = [
        Argument("a1", "看好", domain="投资", agent_id="e1"),
        Argument("a2", "看空", domain="投资", agent_id="e2"),
    ]
    cs = _detector.detect(args)
    issues = _detector.get_debate_issues(cs)
    assert len(issues) >= 1
    assert "agent_ids" in issues[0]

# ═══════════════════════════════════════════════════════════════
# timebox_enforcer
# ═══════════════════════════════════════════════════════════════
from timebox_enforcer import TimeBoxEnforcer, TimeBoxStatus

def _tb_start_remaining():
    e = TimeBoxEnforcer()
    e.start("t1", 10, "test")
    assert e.status("t1") == TimeBoxStatus.RUNNING
    r = e.remaining("t1")
    assert 8 < r <= 10
    e.cancel("t1")

def _tb_cancel():
    e = TimeBoxEnforcer()
    e.start("t2", 10)
    assert e.cancel("t2") == True
    assert e.status("t2") is None

def _tb_extend():
    e = TimeBoxEnforcer()
    e.start("t3", 5)
    time.sleep(0.3)
    e.extend("t3", 10)
    assert e.remaining("t3") > 8
    e.cancel("t3")

def _tb_cancel_all():
    e = TimeBoxEnforcer()
    e.start("a", 10); e.start("b", 10)
    assert e.cancel_all() == 2

def _tb_active_boxes():
    e = TimeBoxEnforcer()
    e.start("x", 10, "box-x"); e.start("y", 10, "box-y")
    assert len(e.active_boxes()) == 2
    e.cancel_all()

# ═══════════════════════════════════════════════════════════════
# anti_formalism
# ═══════════════════════════════════════════════════════════════
from anti_formalism import AntiFormalismChecker, Action

_af = AntiFormalismChecker(min_length=50)

def _af_rejects_filler():
    r = _af.check("同意", "✅")
    assert not r.valid
    assert r.action in (Action.REJECT_RETRY.value, Action.IGNORE.value)

def _af_rejects_short():
    r = _af.check("太短", "✅")
    assert not r.valid

def _af_accepts_good():
    t = "根据报告第3段分析，我认为当前估值偏高。PE为35倍，高于历史中位数25倍。建议等待回调后再考虑买入。"
    r = _af.check(t, "✅")
    assert r.valid

def _af_requires_citation_objection():
    t = "我不赞同，因为风险太高了而且没考虑市场因素。"
    r = _af.check(t, "❌")
    assert not r.valid
    assert any(i["type"] == "no_citation" for i in r.issues)

def _af_accepts_citation():
    t = "我强烈不赞同这个方案。[见consensus.md §2.1] PE为35倍，高于历史中位数25倍，风险明显偏高。"
    r = _af.check(t, "❌")
    assert r.valid

def _af_detects_copy_paste():
    t = "这是一段足够长的回复，包含具体分析和建议。"
    _af.check(t, "✅", agent_id="e1")
    r = _af.check(t, "✅", agent_id="e1")
    assert any(i["type"] == "copy_paste" for i in r.issues)

# ═══════════════════════════════════════════════════════════════
# expert_weight
# ═══════════════════════════════════════════════════════════════
from expert_weight import ExpertWeightManager

def _ew_default():
    with tempfile.TemporaryDirectory() as d:
        m = ExpertWeightManager(Path(d))
        w = m.get_weight("new", role="Builder")
        assert w.base_weight == 1.0

def _ew_update():
    with tempfile.TemporaryDirectory() as d:
        m = ExpertWeightManager(Path(d))
        m.update_record("a1", correct=True)
        m.update_record("a1", correct=True)
        m.update_record("a1", correct=False)
        w = m.get_weight("a1")
        assert w.total_tasks == 3
        assert w.correct_tasks == 2

def _ew_weighted_vote():
    with tempfile.TemporaryDirectory() as d:
        m = ExpertWeightManager(Path(d))
        m.update_record("v1", correct=True)
        m.update_record("v1", correct=True)
        m.update_record("v2", correct=False)
        r = m.apply_vote_weights({"v1": "看多", "v2": "看空"})
        assert r["winning_stance"] == "看多"

# ═══════════════════════════════════════════════════════════════
# consensus_metrics
# ═══════════════════════════════════════════════════════════════
from consensus_metrics import ConsensusMetrics, ConsensusResult, ConsensusLevel

_cm = ConsensusMetrics()

def _cm_strong():
    v = {"a1": "✅", "a2": "✅", "a3": "✅"}
    d = {"a1": {"detail": "[§2.1] 分析充分", "reason_length": 50},
         "a2": {"detail": "同意数据支持", "reason_length": 40},
         "a3": {"detail": "论证完整", "reason_length": 35}}
    r = _cm.evaluate(v, vote_details=d)
    assert r.level in ("strong", "moderate")

def _cm_weak():
    v = {"a1": "✅", "a2": "✅", "a3": "✅"}
    d = {"a1": {"detail": "同意", "reason_length": 2},
         "a2": {"detail": "可以", "reason_length": 2},
         "a3": {"detail": "行", "reason_length": 1}}
    r = _cm.evaluate(v, vote_details=d)
    assert r.level in ("weak", "failed")

def _cm_objection():
    r = _cm.evaluate({"a1": "✅", "a2": "❌"})
    assert r.level == "failed"
    assert r.action == "return"

def _cm_merge():
    r = ConsensusResult(level=ConsensusLevel.WEAK.value, score=0.45, action="return_for_improvement")
    m = _cm.merge_with_synthesis("delivered", r)
    assert m == "delivered_with_concerns"

# ═══════════════════════════════════════════════════════════════
# discussion_history
# ═══════════════════════════════════════════════════════════════
from discussion_history import DiscussionHistory

def _dh_record_suggest():
    with tempfile.TemporaryDirectory() as d:
        h = DiscussionHistory(Path(d))
        h.record("t1", {"task_type": "估值", "conflict_count": 2, "rounds_needed": 3,
                         "consensus_time": 1800, "consensus_level": "moderate", "quality_score": 0.75, "domain": "估值"})
        s = h.suggest(task_type="估值")
        assert s["suggestion"] == "based_on_history"
        assert s["recommended_rounds"] == 3

def _dh_no_history():
    with tempfile.TemporaryDirectory() as d:
        h = DiscussionHistory(Path(d))
        s = h.suggest(task_type="不存在")
        assert s["suggestion"] == "no_history"

# ═══════════════════════════════════════════════════════════════
# expert_matcher
# ═══════════════════════════════════════════════════════════════
from expert_matcher import ExpertMatcher

def _em_match():
    with tempfile.TemporaryDirectory() as d:
        m = ExpertMatcher(Path(d))
        m.update_profile("a1", roles=["DomainExpert"], domains=["估值"], track_record=0.9)
        m.update_profile("a2", roles=["Reviewer"], domains=["风险"], track_record=0.8)
        team = m.match(task_domain="估值", team_size=2)
        assert "a1" in [t["agent_id"] for t in team]

def _em_recommendation():
    with tempfile.TemporaryDirectory() as d:
        m = ExpertMatcher(Path(d))
        m.update_profile("a1", roles=["DomainExpert"], domains=["估值"], track_record=0.9)
        r = m.get_recommendation("a1", task_domain="估值")
        assert "strengths" in r

# ═══════════════════════════════════════════════════════════════
# feature_flags
# ═══════════════════════════════════════════════════════════════
def _ff_exists():
    p = Path(__file__).parent / "enhancement_config.json"
    assert p.exists()

def _ff_valid():
    p = Path(__file__).parent / "enhancement_config.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert "enhancements" in d

def _ff_p0_enabled():
    d = json.loads((Path(__file__).parent / "enhancement_config.json").read_text(encoding="utf-8"))
    e = d["enhancements"]
    assert e["structured_argument"]["enabled"]
    assert e["conflict_detector"]["enabled"]
    assert e["timebox_enforcer"]["enabled"]
    assert e["anti_formalism"]["enabled"]

# ═══════════════════════════════════════════════════════════════
# hub integration
# ═══════════════════════════════════════════════════════════════
from hub import Hub, DiscussionPhase, MessageType

def _hub_import():
    assert DiscussionPhase.IDLE.value == "idle"
    assert MessageType.CHALLENGE.value == "challenge"

def _hub_dirs():
    with tempfile.TemporaryDirectory() as d:
        h = Hub("t", ["a1", "a2"], Path(d), poll_interval=10)
        assert (Path(d) / "messages" / "inbox" / "a1").exists()

def _hub_send():
    with tempfile.TemporaryDirectory() as d:
        h = Hub("t", ["a1"], Path(d), poll_interval=10)
        h.send_to("a1", "test", {"k": "v"})
        files = list((Path(d) / "messages" / "inbox" / "a1").glob("*.json"))
        assert len(files) == 1
        data = json.loads(files[0].read_text(encoding="utf-8"))
        assert data["payload"]["k"] == "v"

# ═══════════════════════════════════════════════════════════════
# Run all
# ═══════════════════════════════════════════════════════════════
ALL_TESTS = [
    ("conflict_detector", [
        ("no_conflict_similar", _cd_no_conflict_similar),
        ("opposite_views", _cd_opposite_views),
        ("confidence_gap", _cd_confidence_gap),
        ("skip_same_agent", _cd_skip_same_agent),
        ("from_message_structured", _cd_from_message_structured),
        ("from_message_legacy", _cd_from_message_legacy),
        ("debate_issues", _cd_debate_issues),
    ]),
    ("timebox_enforcer", [
        ("start_remaining", _tb_start_remaining),
        ("cancel", _tb_cancel),
        ("extend", _tb_extend),
        ("cancel_all", _tb_cancel_all),
        ("active_boxes", _tb_active_boxes),
    ]),
    ("anti_formalism", [
        ("rejects_filler", _af_rejects_filler),
        ("rejects_short", _af_rejects_short),
        ("accepts_good", _af_accepts_good),
        ("requires_citation", _af_requires_citation_objection),
        ("accepts_citation", _af_accepts_citation),
        ("copy_paste", _af_detects_copy_paste),
    ]),
    ("expert_weight", [
        ("default", _ew_default),
        ("update", _ew_update),
        ("weighted_vote", _ew_weighted_vote),
    ]),
    ("consensus_metrics", [
        ("strong", _cm_strong),
        ("weak", _cm_weak),
        ("objection", _cm_objection),
        ("merge", _cm_merge),
    ]),
    ("discussion_history", [
        ("record_suggest", _dh_record_suggest),
        ("no_history", _dh_no_history),
    ]),
    ("expert_matcher", [
        ("match", _em_match),
        ("recommendation", _em_recommendation),
    ]),
    ("feature_flags", [
        ("exists", _ff_exists),
        ("valid", _ff_valid),
        ("p0_enabled", _ff_p0_enabled),
    ]),
    ("hub_integration", [
        ("import", _hub_import),
        ("dirs", _hub_dirs),
        ("send", _hub_send),
    ]),
]

if __name__ == "__main__":
    target = None
    for arg in sys.argv[1:]:
        if arg.startswith("--module="):
            target = arg.split("=", 1)[1]

    print("=" * 60)
    print("Agent-Team-Orchestration Enhancement Tests")
    print("=" * 60)

    for module, tests in ALL_TESTS:
        if target and target != module:
            continue
        print(f"\n[{module}]")
        for name, func in tests:
            run_test(name, module, func)

    print("\n" + "=" * 60)
    passed = sum(1 for r in _results if r["status"] == "PASS")
    failed = sum(1 for r in _results if r["status"] == "FAIL")
    errors = sum(1 for r in _results if r["status"] == "ERROR")
    total = len(_results)
    print(f"Results: {passed}/{total} passed, {failed} failed, {errors} errors")

    if failed or errors:
        print("\nFailed/Error:")
        for r in _results:
            if r["status"] != "PASS":
                print(f"  {r['status']}: {r['name']} - {r.get('error','')}")

    sys.exit(0 if not failed and not errors else 1)

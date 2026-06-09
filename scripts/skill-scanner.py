#!/usr/bin/env python3
"""

# [中文说明]
# 本文件：skill-scanner.py
# 用途：OpenClaw 框架的核心脚本之一
# 详细文档：请阅读对应的 SKILL.md 和 references/

Skill Scanner - 动态技能发现工具（jieba分词版 v1.2）
支持中英文混合分词和TF-IDF语义匹配

使用方式：
    python skill-scanner.py scan              # 扫描所有技能
    python skill-scanner.py find <任务描述>   # TF-IDF语义匹配
    python skill-scanner.py clear-cache       # 清除缓存
    python skill-scanner.py feedback <skill> <task>  # 记录人工校正
"""

import json, re, math
from pathlib import Path
from typing import List, Dict, Optional, Set
import sys
import time

# 尝试导入jieba，失败则降级到简单分词
try:
    import jieba
    JIEBA_AVAILABLE = True
except ImportError:
    JIEBA_AVAILABLE = False

# 路径配置
SKILLS_DIRS = [
    Path.home() / ".qclaw" / "skills",
    Path.home() / ".openclaw" / "workspace" / "skills",
]
CACHE_FILE = Path.home() / ".qclaw" / ".skill-perception-cache.json"
FEEDBACK_FILE = Path.home() / ".qclaw" / ".skill-perception-feedback.json"
CACHE_TTL = 24 * 3600  # 24小时

# 置信度阈值（调整后）
CONF_AUTO = 0.50   # 原来是0.85，调整后更实用
CONF_SUGGEST = 0.30  # 原来是0.60

# 停用词
STOPWORDS = {
    "the", "and", "for", "with", "use", "when", "this", "that", "is", "are",
    "技能", "工具", "能力", "支持", "可以", "进行", "以及", "或者"
}


def tokenize_jieba(text: str) -> List[str]:
    """jieba分词：支持中文语义切分+英文单词"""
    if not text:
        return []
    english = re.findall(r'[a-zA-Z]{2,}', text.lower())
    if JIEBA_AVAILABLE:
        chinese_tokens = [w for w in jieba.cut(text) if '\u4e00' <= w[0] <= '\u9fff']
    else:
        chinese_tokens = [text[i:i+2] for i in range(len(text)-1)
                         if '\u4e00' <= text[i] <= '\u9fff' and '\u4e00' <= text[i+1] <= '\u9fff']
    result = english + chinese_tokens
    return [w for w in result if w.lower() not in STOPWORDS and len(w) >= 2]


def cosine_similarity(vec1: Dict[str, float], vec2: Dict[str, float]) -> float:
    if not vec1 or not vec2:
        return 0.0
    common = set(vec1.keys()) & set(vec2.keys())
    if not common:
        return 0.0
    dot = sum(vec1[t] * vec2[t] for t in common)
    norm1 = math.sqrt(sum(v * v for v in vec1.values()))
    norm2 = math.sqrt(sum(v * v for v in vec2.values()))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)


def parse_skill_meta(skill_path: Path) -> Optional[Dict]:
    try:
        content = skill_path.read_text(encoding="utf-8")
    except Exception:
        return None

    if content.startswith("---"):
        parts = content.split("---", 2)
        frontmatter = parts[1] if len(parts) >= 2 else ""
        body = parts[2] if len(parts) >= 3 else content
    else:
        frontmatter = ""
        body = content

    name, description = None, None
    for line in frontmatter.split("\n"):
        if line.startswith("name:"):
            name = line.split("name:", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("description:"):
            description = line.split("description:", 1)[1].strip().strip('"').strip("'")

    if not name:
        name = skill_path.parent.name
    if not description:
        first_para = body.strip().split("\n\n")[0] if body.strip() else ""
        description = re.sub(r"\[.*?\]", "", first_para)[:200]

    return {
        "name": name,
        "description": description or "",
        "path": str(skill_path.parent),
        "tokens": tokenize_jieba(description)
    }


def scan_skills() -> List[Dict]:
    registry = []
    seen: Set[str] = set()
    for skills_dir in SKILLS_DIRS:
        if not skills_dir.exists():
            continue
        for skill_path in skills_dir.glob("*/SKILL.md"):
            meta = parse_skill_meta(skill_path)
            if meta and meta["name"] not in seen:
                seen.add(meta["name"])
                registry.append(meta)
    return sorted(registry, key=lambda x: x["name"])


def find_matching_skills(
    task_description: str,
    registry: List[Dict],
    top_n: int = 5
) -> List[Dict]:
    """TF-IDF语义匹配"""
    task_tokens = tokenize_jieba(task_description)
    if not task_tokens:
        return registry[:top_n]

    doc_count = len(registry)
    task_tf = {}
    for token in task_tokens:
        task_tf[token] = task_tf.get(token, 0) + 1

    task_idf = {}
    for token in set(task_tokens):
        count = sum(1 for s in registry if token in s.get("tokens", []))
        task_idf[token] = math.log(doc_count / (count + 1)) + 1

    task_tfidf = {token: freq * task_idf.get(token, 1) for token, freq in task_tf.items()}
    norm = math.sqrt(sum(v * v for v in task_tfidf.values()))
    if norm > 0:
        task_tfidf = {t: v / norm for t, v in task_tfidf.items()}

    # 应用反馈boost
    feedback_boost = load_feedback_boost(task_description)

    scored = []
    for skill in registry:
        tokens = skill.get("tokens", [])
        skill_tf = {}
        for t in tokens:
            skill_tf[t] = skill_tf.get(t, 0) + 1

        skill_idf = {}
        for t in set(tokens):
            c = sum(1 for s in registry if t in s.get("tokens", []))
            skill_idf[t] = math.log(doc_count / (c + 1)) + 1

        skill_tfidf = {t: freq * skill_idf.get(t, 1) for t, freq in skill_tf.items()}
        s_norm = math.sqrt(sum(v * v for v in skill_tfidf.values()))
        if s_norm > 0:
            skill_tfidf = {t: v / s_norm for t, v in skill_tfidf.items()}

        score = cosine_similarity(task_tfidf, skill_tfidf)

        # 应用反馈boost
        boost = feedback_boost.get(skill["name"], 0)
        score = min(1.0, score + boost)

        if score > 0:
            scored.append((score, skill))

    scored.sort(key=lambda x: -x[0])
    results = []
    for score, skill in scored[:top_n]:
        conf = "auto" if score >= CONF_AUTO else ("suggest" if score >= CONF_SUGGEST else "low")
        results.append({
            "name": skill["name"],
            "description": skill.get("description", "")[:100],
            "relevance": round(score, 3),
            "confidence": conf,
            "match_reason": f"TF-IDF匹配度 {score:.1%}"
        })
    return results


def load_feedback_boost(task_context: str = "") -> Dict[str, float]:
    """加载反馈boost"""
    if not FEEDBACK_FILE.exists():
        return {}
    try:
        feedback = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        boost = {}
        for entry in feedback:
            skill = entry.get("skill_name", "")
            adjustment = entry.get("adjustment", 0)
            if skill:
                boost[skill] = boost.get(skill, 0) + adjustment
        return boost
    except Exception:
        return {}


def save_feedback(skill_name: str, task: str, accepted: bool):
    """记录人工校正反馈"""
    FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    feedback = []
    if FEEDBACK_FILE.exists():
        try:
            feedback = json.loads(FEEDBACK_FILE.read_text(encoding="utf-8"))
        except Exception:
            feedback = []

    # 采纳=+0.2 boost，拒绝=-0.1 boost
    adjustment = 0.2 if accepted else -0.1
    feedback.append({
        "skill_name": skill_name,
        "task": task,
        "adjustment": adjustment,
        "timestamp": time.time()
    })

    FEEDBACK_FILE.write_text(json.dumps(feedback, ensure_ascii=False, indent=2), encoding="utf-8")


def get_cached_registry() -> Optional[List[Dict]]:
    if not CACHE_FILE.exists():
        return None
    try:
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        if time.time() - cache.get("timestamp", 0) < CACHE_TTL:
            return cache.get("skills")
    except Exception:
        pass
    return None


def save_registry_to_cache(registry: List[Dict]):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    cache = {"timestamp": time.time(), "skills": registry, "version": "1.2"}
    CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    action = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if action == "scan":
        registry = get_cached_registry()
        if not registry:
            registry = scan_skills()
            save_registry_to_cache(registry)
            print(f"[skill-scanner] Scanned {len(registry)} skills (jieba={JIEBA_AVAILABLE})", file=sys.stderr)
        else:
            print(f"[skill-scanner] Using cached registry ({len(registry)} skills)", file=sys.stderr)
        print(json.dumps(registry, ensure_ascii=False, indent=2))

    elif action == "find":
        if len(sys.argv) < 3:
            print("Usage: skill-scanner.py find <task_description>", file=sys.stderr)
            sys.exit(1)
        registry = get_cached_registry()
        if not registry:
            registry = scan_skills()
            save_registry_to_cache(registry)
        matches = find_matching_skills(sys.argv[2], registry)
        print(f"[skill-scanner] Found {len(matches)} matches for: {sys.argv[2]}", file=sys.stderr)
        print(json.dumps(matches, ensure_ascii=False, indent=2))

    elif action == "clear-cache":
        if CACHE_FILE.exists():
            CACHE_FILE.unlink()
            print("[skill-scanner] Cache cleared")
        else:
            print("[skill-scanner] No cache to clear")

    elif action == "feedback":
        # feedback <skill_name> <task_query> <accepted:yes|no>
        if len(sys.argv) < 4:
            print("Usage: skill-scanner.py feedback <skill> <task> <yes|no>", file=sys.stderr)
            sys.exit(1)
        skill_name = sys.argv[2]
        task = sys.argv[3]
        accepted = sys.argv[4].lower() == "yes"
        save_feedback(skill_name, task, accepted)
        print(f"[skill-scanner] Feedback recorded: {skill_name} {'+' if accepted else '-'}", file=sys.stderr)

    elif action == "test":
        # 内置测试
        registry = get_cached_registry()
        if not registry:
            registry = scan_skills()
            save_registry_to_cache(registry)

        test_queries = [
            "审计代码质量",
            "stock market analysis",
            "文件处理",
            "定时任务提醒"
        ]
        results = {}
        for q in test_queries:
            matches = find_matching_skills(q, registry, 3)
            results[q] = matches

        print(json.dumps(results, ensure_ascii=False, indent=2), file=sys.stderr)
        print("[skill-scanner] Test completed", file=sys.stderr)

    else:
        print(f"Unknown action: {action}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
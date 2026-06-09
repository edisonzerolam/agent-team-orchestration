"""
MIMO 大模型限速器 - 适用于 agent-team-orchestration 和多线程并行技能

速率限制配置:
- RPM: 100 (每分钟最大请求数)
- TPM: 10,000,000 (每分钟最大 token 数)

使用方式:
    from mimo_rate_limiter import MimoRateLimiter
    
    limiter = MimoRateLimiter()
    
    # 获取许可
    await limiter.acquire(agent_id="agent-1", estimated_tokens=5000)
    
    # 或同步方式
    limiter.acquire_sync(agent_id="agent-1", estimated_tokens=5000)
"""

import time
import threading
import asyncio
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from collections import deque
from enum import Enum
import json
from pathlib import Path


class Priority(Enum):
    """任务优先级"""
    CRITICAL = 0    # 关键任务（orchestrator 决策）
    HIGH = 1        # 高优先级（reviewer 检查）
    NORMAL = 2      # 普通任务（builder 执行）
    LOW = 3         # 低优先级（ops 监控）
    BACKGROUND = 4  # 后台任务（日志、统计）


@dataclass
class TokenBucket:
    """令牌桶"""
    capacity: int                    # 桶容量
    tokens: float                    # 当前令牌数
    refill_rate: float               # 令牌补充速率（每秒）
    last_refill_time: float          # 上次补充时间
    
    def refill(self):
        """补充令牌"""
        now = time.time()
        elapsed = now - self.last_refill_time
        new_tokens = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + new_tokens)
        self.last_refill_time = now
    
    def consume(self, tokens: int) -> bool:
        """尝试消费令牌"""
        self.refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
    
    def wait_time(self, tokens: int) -> float:
        """计算需要等待的时间（秒）"""
        self.refill()
        if self.tokens >= tokens:
            return 0.0
        needed = tokens - self.tokens
        return needed / self.refill_rate


@dataclass
class RateLimitConfig:
    """限速配置"""
    rpm_limit: int = 100             # 每分钟最大请求数
    tpm_limit: int = 10_000_000      # 每分钟最大 token 数
    burst_rpm: int = 20              # 突发请求允许量
    burst_tpm: int = 1_000_000       # 突发 token 允许量
    
    # 每个 agent 的最小配额
    min_rpm_per_agent: int = 5
    min_tpm_per_agent: int = 100_000
    
    # 队列配置
    max_queue_size: int = 100
    queue_timeout: int = 300         # 队列超时（秒）
    
    # 退避配置
    base_backoff: float = 1.0        # 基础退避时间（秒）
    max_backoff: float = 60.0        # 最大退避时间（秒）
    backoff_multiplier: float = 2.0  # 退避倍数
    
    # 监控配置
    metrics_window: int = 60         # 滑动窗口（秒）
    alert_threshold_rpm: float = 0.8 # RPM 告警阈值（80%）
    alert_threshold_tpm: float = 0.8 # TPM 告警阈值（80%）


@dataclass
class QueuedRequest:
    """排队请求"""
    request_id: str
    agent_id: str
    estimated_tokens: int
    priority: Priority
    enqueue_time: float
    callback: Optional[callable] = None
    
    def __lt__(self, other):
        """优先级队列比较"""
        return self.priority.value < other.priority.value


class MimoRateLimiter:
    """MIMO 大模型限速器"""
    
    def __init__(self, config: Optional[RateLimitConfig] = None, metrics_dir: Optional[Path] = None):
        self.config = config or RateLimitConfig()
        self.metrics_dir = metrics_dir
        
        # RPM 令牌桶（每秒补充 rpm_limit/60 个令牌）
        self.rpm_bucket = TokenBucket(
            capacity=self.config.rpm_limit,
            tokens=self.config.rpm_limit,
            refill_rate=self.config.rpm_limit / 60.0,
            last_refill_time=time.time()
        )
        
        # TPM 令牌桶（每秒补充 tpm_limit/60 个令牌）
        self.tpm_bucket = TokenBucket(
            capacity=self.config.tpm_limit,
            tokens=self.config.tpm_limit,
            refill_rate=self.config.tpm_limit / 60.0,
            last_refill_time=time.time()
        )
        
        # 优先级队列
        self.queue: deque[QueuedRequest] = deque()
        self.queue_lock = threading.Lock()
        
        # Agent 配额追踪
        self.agent_rpm: Dict[str, deque] = {}  # agent_id -> 请求时间戳队列
        self.agent_tpm: Dict[str, deque] = {}  # agent_id -> token 使用队列
        
        # 退避追踪
        self.agent_backoff: Dict[str, float] = {}  # agent_id -> 退避结束时间
        
        # 监控指标
        self.metrics = {
            "total_requests": 0,
            "rejected_requests": 0,
            "queued_requests": 0,
            "processed_requests": 0,
            "total_tokens": 0,
            "rpk_rejections": 0,
            "tpm_rejections": 0,
            "timeout_rejections": 0
        }
        self.metrics_lock = threading.Lock()
        
        # 滑动窗口指标
        self.request_times: deque = deque()
        self.token_usage: deque = deque()
        
        # 后台队列处理线程
        self._queue_processor_running = False
        self._queue_processor_thread: Optional[threading.Thread] = None
        
        # 状态文件路径
        self.state_file = Path("mimo_limiter_state.json")
    
    def _cleanup_windows(self):
        """清理滑动窗口过期数据"""
        now = time.time()
        cutoff = now - self.config.metrics_window
        
        # 清理请求时间窗口
        while self.request_times and self.request_times[0] < cutoff:
            self.request_times.popleft()
        
        # 清理 token 使用窗口
        while self.token_usage and self.token_usage[0][0] < cutoff:
            self.token_usage.popleft()
    
    def _get_current_rpm(self) -> float:
        """获取当前 RPM"""
        self._cleanup_windows()
        if not self.request_times:
            return 0.0
        return len(self.request_times) / (self.config.metrics_window / 60.0)
    
    def _get_current_tpm(self) -> float:
        """获取当前 TPM"""
        self._cleanup_windows()
        if not self.token_usage:
            return 0.0
        total_tokens = sum(t[1] for t in self.token_usage)
        return total_tokens / (self.config.metrics_window / 60.0)
    
    def _check_agent_quota(self, agent_id: str, tokens: int) -> bool:
        """检查 agent 是否超过配额"""
        now = time.time()
        cutoff = now - 60.0
        
        # 检查 agent RPM
        if agent_id not in self.agent_rpm:
            self.agent_rpm[agent_id] = deque()
        agent_rpm_queue = self.agent_rpm[agent_id]
        
        # 清理过期记录
        while agent_rpm_queue and agent_rpm_queue[0] < cutoff:
            agent_rpm_queue.popleft()
        
        # 检查是否超过 agent 配额
        if len(agent_rpm_queue) >= self.config.min_rpm_per_agent:
            # 检查全局 RPM 是否有余量
            if self._get_current_rpm() >= self.config.rpm_limit * 0.9:
                return False
        
        # 检查 agent TPM
        if agent_id not in self.agent_tpm:
            self.agent_tpm[agent_id] = deque()
        agent_tpm_queue = self.agent_tpm[agent_id]
        
        # 清理过期记录
        while agent_tpm_queue and agent_tpm_queue[0][0] < cutoff:
            agent_tpm_queue.popleft()
        
        # 检查是否超过 agent 配额
        agent_current_tpm = sum(t[1] for t in agent_tpm_queue)
        if agent_current_tpm >= self.config.min_tpm_per_agent:
            # 检查全局 TPM 是否有余量
            if self._get_current_tpm() >= self.config.tpm_limit * 0.9:
                return False
        
        return True
    
    def _check_backoff(self, agent_id: str) -> bool:
        """检查 agent 是否在退避期间"""
        if agent_id in self.agent_backoff:
            if time.time() < self.agent_backoff[agent_id]:
                return False
        return True
    
    def _apply_backoff(self, agent_id: str):
        """应用退避策略"""
        current_backoff = self.agent_backoff.get(agent_id, 0)
        if current_backoff == 0:
            new_backoff = self.config.base_backoff
        else:
            new_backoff = min(
                current_backoff * self.config.backoff_multiplier,
                self.config.max_backoff
            )
        self.agent_backoff[agent_id] = time.time() + new_backoff
    
    def _reset_backoff(self, agent_id: str):
        """重置退避"""
        if agent_id in self.agent_backoff:
            del self.agent_backoff[agent_id]
    
    def acquire_sync(self, agent_id: str, estimated_tokens: int, 
                     priority: Priority = Priority.NORMAL) -> bool:
        """
        同步获取许可
        
        Args:
            agent_id: Agent ID
            estimated_tokens: 预估 token 数
            priority: 任务优先级
        
        Returns:
            是否获取成功
        """
        # 检查退避
        if not self._check_backoff(agent_id):
            return False
        
        # 检查队列是否已满
        with self.queue_lock:
            if len(self.queue) >= self.config.max_queue_size:
                with self.metrics_lock:
                    self.metrics["rejected_requests"] += 1
                    self.metrics["timeout_rejections"] += 1
                return False
        
        # 尝试获取 RPM 和 TPM 令牌
        if self.rpm_bucket.consume(1) and self.tpm_bucket.consume(estimated_tokens):
            # 记录请求
            now = time.time()
            self.request_times.append(now)
            self.token_usage.append((now, estimated_tokens))
            
            # 记录 agent 使用
            if agent_id not in self.agent_rpm:
                self.agent_rpm[agent_id] = deque()
            if agent_id not in self.agent_tpm:
                self.agent_tpm[agent_id] = deque()
            self.agent_rpm[agent_id].append(now)
            self.agent_tpm[agent_id].append((now, estimated_tokens))
            
            # 重置退避
            self._reset_backoff(agent_id)
            
            # 更新指标
            with self.metrics_lock:
                self.metrics["total_requests"] += 1
                self.metrics["processed_requests"] += 1
                self.metrics["total_tokens"] += estimated_tokens
            
            return True
        
        # 令牌不足，加入队列
        self._enqueue_request(agent_id, estimated_tokens, priority)
        return False
    
    async def acquire(self, agent_id: str, estimated_tokens: int,
                      priority: Priority = Priority.NORMAL) -> bool:
        """
        异步获取许可（带等待）
        
        Args:
            agent_id: Agent ID
            estimated_tokens: 预估 token 数
            priority: 任务优先级
        
        Returns:
            是否获取成功
        """
        start_time = time.time()
        
        while True:
            # 检查超时
            if time.time() - start_time > self.config.queue_timeout:
                with self.metrics_lock:
                    self.metrics["timeout_rejections"] += 1
                return False
            
            # 尝试同步获取
            if self.acquire_sync(agent_id, estimated_tokens, priority):
                return True
            
            # 计算等待时间
            rpm_wait = self.rpm_bucket.wait_time(1)
            tpm_wait = self.tpm_bucket.wait_time(estimated_tokens)
            wait_time = max(rpm_wait, tpm_wait, 0.1)
            
            # 等待
            await asyncio.sleep(min(wait_time, 1.0))
    
    def _enqueue_request(self, agent_id: str, estimated_tokens: int, 
                         priority: Priority):
        """将请求加入队列"""
        request_id = f"req-{int(time.time() * 1000)}-{agent_id}"
        request = QueuedRequest(
            request_id=request_id,
            agent_id=agent_id,
            estimated_tokens=estimated_tokens,
            priority=priority,
            enqueue_time=time.time()
        )
        
        with self.queue_lock:
            self.queue.append(request)
            # 按优先级排序
            self.queue = deque(sorted(self.queue))
        
        with self.metrics_lock:
            self.metrics["queued_requests"] += 1
    
    def start_queue_processor(self):
        """启动队列处理器"""
        if self._queue_processor_running:
            return
        
        self._queue_processor_running = True
        self._queue_processor_thread = threading.Thread(
            target=self._process_queue_loop,
            daemon=True
        )
        self._queue_processor_thread.start()
    
    def stop_queue_processor(self):
        """停止队列处理器"""
        self._queue_processor_running = False
        if self._queue_processor_thread:
            self._queue_processor_thread.join(timeout=5)
    
    def _process_queue_loop(self):
        """队列处理循环"""
        while self._queue_processor_running:
            self._process_queue()
            time.sleep(0.1)  # 100ms 检查间隔
    
    def _process_queue(self):
        """处理队列中的请求"""
        with self.queue_lock:
            if not self.queue:
                return
            
            # 检查队头请求
            request = self.queue[0]
            
            # 检查超时
            if time.time() - request.enqueue_time > self.config.queue_timeout:
                self.queue.popleft()
                with self.metrics_lock:
                    self.metrics["timeout_rejections"] += 1
                return
            
            # 尝试处理
            if self.rpm_bucket.consume(1) and self.tpm_bucket.consume(request.estimated_tokens):
                self.queue.popleft()
                
                # 记录请求
                now = time.time()
                self.request_times.append(now)
                self.token_usage.append((now, request.estimated_tokens))
                
                # 记录 agent 使用
                if request.agent_id not in self.agent_rpm:
                    self.agent_rpm[request.agent_id] = deque()
                if request.agent_id not in self.agent_tpm:
                    self.agent_tpm[request.agent_id] = deque()
                
                self.agent_rpm[request.agent_id].append(now)
                self.agent_tpm[request.agent_id].append((now, request.estimated_tokens))
                
                # 重置退避
                self._reset_backoff(request.agent_id)
                
                # 更新指标
                with self.metrics_lock:
                    self.metrics["processed_requests"] += 1
                    self.metrics["total_tokens"] += request.estimated_tokens
                
                # 执行回调
                if request.callback:
                    try:
                        request.callback()
                    except Exception:
                        pass
    
    def handle_rate_limit_error(self, agent_id: str, error_type: str = "rpm"):
        """
        处理限速错误
        
        Args:
            agent_id: Agent ID
            error_type: 错误类型 ("rpm" 或 "tpm")
        """
        self._apply_backoff(agent_id)
        
        with self.metrics_lock:
            self.metrics["rejected_requests"] += 1
            if error_type == "rpm":
                self.metrics["rpk_rejections"] += 1
            else:
                self.metrics["tpm_rejections"] += 1
    
    def get_metrics(self) -> Dict:
        """获取当前指标"""
        self._cleanup_windows()
        
        with self.metrics_lock:
            metrics = self.metrics.copy()
        
        metrics["current_rpm"] = self._get_current_rpm()
        metrics["current_tpm"] = self._get_current_tpm()
        metrics["queue_size"] = len(self.queue)
        metrics["rpm_utilization"] = metrics["current_rpm"] / self.config.rpm_limit
        metrics["tpm_utilization"] = metrics["current_tpm"] / self.config.tpm_limit
        
        # 告警检查
        metrics["alerts"] = []
        if metrics["rpm_utilization"] >= self.config.alert_threshold_rpm:
            metrics["alerts"].append(f"RPM 接近限制: {metrics['current_rpm']:.1f}/{self.config.rpm_limit}")
        if metrics["tpm_utilization"] >= self.config.alert_threshold_tpm:
            metrics["alerts"].append(f"TPM 接近限制: {metrics['current_tpm']:.0f}/{self.config.tpm_limit}")
        
        return metrics
    
    def save_state(self):
        """保存状态到文件"""
        state = {
            "config": {
                "rpm_limit": self.config.rpm_limit,
                "tpm_limit": self.config.tpm_limit,
                "burst_rpm": self.config.burst_rpm,
                "burst_tpm": self.config.burst_tpm
            },
            "metrics": self.metrics,
            "agent_backoff": self.agent_backoff,
            "timestamp": time.time()
        }
        
        self.state_file.write_text(
            json.dumps(state, indent=2),
            encoding="utf-8"
        )
    
    def load_state(self):
        """从文件加载状态"""
        if not self.state_file.exists():
            return
        
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.metrics.update(state.get("metrics", {}))
            self.agent_backoff = state.get("agent_backoff", {})
        except Exception:
            pass
    
    def allocate_budget(self, agent_count: int) -> Dict[str, Dict]:
        """
        为多个 agent 分配配额
        
        Args:
            agent_count: Agent 数量
        
        Returns:
            每个 agent 的配额字典
        """
        # 基础配额分配
        base_rpm_per_agent = self.config.rpm_limit // agent_count
        base_tpm_per_agent = self.config.tpm_limit // agent_count
        
        # 确保不低于最小配额
        rpm_per_agent = max(base_rpm_per_agent, self.config.min_rpm_per_agent)
        tpm_per_agent = max(base_tpm_per_agent, self.config.min_tpm_per_agent)
        
        budget = {}
        for i in range(agent_count):
            agent_id = f"agent-{i+1}"
            budget[agent_id] = {
                "rpm_quota": rpm_per_agent,
                "tpm_quota": tpm_per_agent,
                "max_concurrent": min(3, rpm_per_agent),
                "priority_boost": 0
            }
        
        # 为 orchestrator 提升优先级
        if "agent-1" in budget:
            budget["agent-1"]["priority_boost"] = 1
            budget["agent-1"]["rpm_quota"] = int(rpm_per_agent * 1.2)
        
        return budget
    
    def get_recommended_settings(self, agent_count: int) -> Dict:
        """
        获取推荐设置
        
        Args:
            agent_count: Agent 数量
        
        Returns:
            推荐配置
        """
        budget = self.allocate_budget(agent_count)
        
        return {
            "agent_count": agent_count,
            "total_rpm": self.config.rpm_limit,
            "total_tpm": self.config.tpm_limit,
            "per_agent_budget": budget,
            "recommendations": {
                "max_concurrent_agents": min(agent_count, 8),
                "suggested_delay_between_spawns": max(0.5, agent_count * 0.1),
                "queue_timeout": self.config.queue_timeout,
                "backoff_base": self.config.base_backoff,
                "use_priority_queue": True,
                "enable_token_estimation": True
            },
            "warnings": self._generate_warnings(agent_count)
        }
    
    def _generate_warnings(self, agent_count: int) -> List[str]:
        """生成警告信息"""
        warnings = []
        
        if agent_count > 10:
            warnings.append(f"Agent 数量 ({agent_count}) 较多，可能导致频繁限速")
        
        if agent_count > 5:
            warnings.append("建议使用优先级队列，确保关键任务优先执行")
        
        rpm_per_agent = self.config.rpm_limit // agent_count
        if rpm_per_agent < 10:
            warnings.append(f"每个 agent 仅 {rpm_per_agent} RPM，建议减少 agent 数量或增加 RPM 限制")
        
        return warnings


# 全局实例
_global_limiter: Optional[MimoRateLimiter] = None
_limiter_lock = threading.Lock()


def get_limiter(config: Optional[RateLimitConfig] = None) -> MimoRateLimiter:
    """获取全局限速器实例"""
    global _global_limiter
    
    with _limiter_lock:
        if _global_limiter is None:
            _global_limiter = MimoRateLimiter(config)
        return _global_limiter


def acquire_rate_limit(agent_id: str, estimated_tokens: int = 1000,
                       priority: Priority = Priority.NORMAL) -> bool:
    """
    便捷函数：同步获取速率限制许可
    
    Args:
        agent_id: Agent ID
        estimated_tokens: 预估 token 数
        priority: 任务优先级
    
    Returns:
        是否获取成功
    """
    limiter = get_limiter()
    return limiter.acquire_sync(agent_id, estimated_tokens, priority)


async def acquire_rate_limit_async(agent_id: str, estimated_tokens: int = 1000,
                                   priority: Priority = Priority.NORMAL) -> bool:
    """
    便捷函数：异步获取速率限制许可
    
    Args:
        agent_id: Agent ID
        estimated_tokens: 预估 token 数
        priority: 任务优先级
    
    Returns:
        是否获取成功
    """
    limiter = get_limiter()
    return await limiter.acquire(agent_id, estimated_tokens, priority)


def estimate_tokens(text: str) -> int:
    """
    估算文本的 token 数量
    
    中文: 约 1.5 token/字
    英文: 约 0.75 token/word
    
    Args:
        text: 输入文本
    
    Returns:
        预估 token 数
    """
    # 简单估算：中文字符数 + 英文单词数 * 1.5
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    english_words = len(text.split()) - chinese_chars
    
    return int(chinese_chars * 1.5 + english_words * 0.75) + 100  # +100 for overhead


def estimate_prompt_tokens(system_prompt: str, user_message: str, 
                           context: str = "") -> int:
    """估算完整 prompt 的 token 数"""
    total_text = system_prompt + user_message + context
    return estimate_tokens(total_text)


# 测试函数
def test_rate_limiter():
    """测试限速器"""
    print("=== MIMO 限速器测试 ===")
    
    limiter = MimoRateLimiter()
    
    # 测试配额分配
    budget = limiter.allocate_budget(5)
    print(f"\n5 个 agent 的配额分配:")
    for agent_id, quota in budget.items():
        print(f"  {agent_id}: RPM={quota['rpm_quota']}, TPM={quota['tpm_quota']}")
    
    # 测试获取许可
    print(f"\n测试获取许可:")
    for i in range(5):
        agent_id = f"agent-{i+1}"
        success = limiter.acquire_sync(agent_id, 5000)
        status = "SUCCESS" if success else "FAILED"
        print(f"  {agent_id}: {status}")
    
    # 测试指标
    metrics = limiter.get_metrics()
    print(f"\n当前指标:")
    print(f"  RPM: {metrics['current_rpm']:.1f}/{limiter.config.rpm_limit}")
    print(f"  TPM: {metrics['current_tpm']:.0f}/{limiter.config.tpm_limit}")
    print(f"  队列大小: {metrics['queue_size']}")
    
    # 测试推荐设置
    recommendations = limiter.get_recommended_settings(5)
    print(f"\n推荐设置:")
    print(f"  最大并发 agent: {recommendations['recommendations']['max_concurrent_agents']}")
    print(f"  生成间隔: {recommendations['recommendations']['suggested_delay_between_spawns']}s")
    
    if recommendations['warnings']:
        print(f"\n⚠️ 警告:")
        for warning in recommendations['warnings']:
            print(f"  - {warning}")
    
    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    test_rate_limiter()

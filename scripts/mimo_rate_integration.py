"""
MIMO 限速器集成模块 - 将限速器集成到 agent-team-orchestration

使用方式:
    from mimo_rate_integration import MimoAwareOrchestrator
    
    orchestrator = MimoAwareOrchestrator()
    orchestrator.launch_team_with_rate_limit(topic, description, max_agents)
"""

import time
import asyncio
from typing import Dict, List, Optional, Any
from pathlib import Path

# 导入限速器
from mimo_rate_limiter import (
    MimoRateLimiter, RateLimitConfig, Priority,
    get_limiter, acquire_rate_limit, estimate_tokens,
    estimate_prompt_tokens
)


class MimoAwareOrchestrator:
    """MIMO 感知的编排器"""
    
    def __init__(self, config: Optional[RateLimitConfig] = None):
        self.limiter = get_limiter(config)
        self.agent_budgets: Dict[str, Dict] = {}
        self.agent_token_usage: Dict[str, int] = {}
        self.agent_request_counts: Dict[str, int] = {}
        
        # 启动队列处理器
        self.limiter.start_queue_processor()
    
    def plan_team_with_budget(self, topic: str, description: str, 
                               max_agents: int = 5) -> Dict:
        """
        规划团队并分配预算
        
        Args:
            topic: 任务主题
            description: 任务描述
            max_agents: 最大 agent 数量
        
        Returns:
            带预算的团队计划
        """
        # 根据任务复杂度确定 agent 数量
        agent_count = self._determine_agent_count(topic, description, max_agents)
        
        # 分配预算
        self.agent_budgets = self.limiter.allocate_budget(agent_count)
        
        # 生成团队计划
        plan = {
            "topic": topic,
            "description": description,
            "agent_count": agent_count,
            "budgets": self.agent_budgets,
            "agents": self._generate_agent_assignments(topic, description, agent_count),
            "rate_limit_config": {
                "rpm_limit": self.limiter.config.rpm_limit,
                "tpm_limit": self.limiter.config.tpm_limit,
                "per_agent_rpm": self.agent_budgets.get("agent-1", {}).get("rpm_quota", 20),
                "per_agent_tpm": self.agent_budgets.get("agent-1", {}).get("tpm_quota", 2_000_000)
            }
        }
        
        return plan
    
    def _determine_agent_count(self, topic: str, description: str, 
                                max_agents: int) -> int:
        """根据任务复杂度确定 agent 数量"""
        text = f"{topic} {description}".lower()
        
        # 复杂度关键词
        high_complexity = ["深度", "全面", "系统", "多维度", "综合", "架构"]
        medium_complexity = ["分析", "研究", "调研", "规划", "策略"]
        low_complexity = ["检查", "审核", "简单", "快速"]
        
        score = 0
        for keyword in high_complexity:
            if keyword in text:
                score += 3
        
        for keyword in medium_complexity:
            if keyword in text:
                score += 2
        
        for keyword in low_complexity:
            if keyword in text:
                score += 1
        
        # 根据分数确定 agent 数量
        if score >= 8:
            agent_count = min(max_agents, 5)
        elif score >= 5:
            agent_count = min(max_agents, 4)
        elif score >= 3:
            agent_count = min(max_agents, 3)
        else:
            agent_count = min(max_agents, 2)
        
        return agent_count
    
    def _generate_agent_assignments(self, topic: str, description: str,
                                     agent_count: int) -> List[Dict]:
        """生成 agent 任务分配"""
        assignments = []
        
        # 角色定义
        roles = [
            {"id": "orchestrator", "name": "编排器", "role": "任务协调与优先级管理", "priority": Priority.CRITICAL},
            {"id": "builder", "name": "构建者", "role": "执行核心任务", "priority": Priority.NORMAL},
            {"id": "reviewer", "name": "审查者", "role": "质量检查与验证", "priority": Priority.HIGH},
            {"id": "analyst", "name": "分析师", "role": "数据分析与洞察", "priority": Priority.NORMAL},
            {"id": "ops", "name": "运维", "role": "环境与部署支持", "priority": Priority.LOW}
        ]
        
        # 选择角色
        selected_roles = roles[:agent_count]
        
        for i, role in enumerate(selected_roles):
            agent_id = f"agent-{i+1}"
            budget = self.agent_budgets.get(agent_id, {})
            
            assignments.append({
                "agent_id": agent_id,
                "role": role["name"],
                "description": role["role"],
                "priority": role["priority"].name,
                "budget": {
                    "rpm_quota": budget.get("rpm_quota", 20),
                    "tpm_quota": budget.get("tpm_quota", 2_000_000),
                    "max_concurrent": budget.get("max_concurrent", 2)
                },
                "task": self._generate_task_description(topic, role["role"])
            })
        
        return assignments
    
    def _generate_task_description(self, topic: str, role: str) -> str:
        """生成任务描述"""
        task_templates = {
            "任务协调与优先级管理": f"协调团队完成 {topic} 任务，管理优先级和资源分配",
            "执行核心任务": f"执行 {topic} 的核心工作，产出主要成果",
            "质量检查与验证": f"审查 {topic} 的产出物，确保质量和准确性",
            "数据分析与洞察": f"分析 {topic} 相关数据，提供洞察和建议",
            "环境与部署支持": f"提供 {topic} 所需的环境和技术支持"
        }
        
        return task_templates.get(role, f"参与 {topic} 任务")
    
    def spawn_agent_with_rate_limit(self, agent_id: str, task: str,
                                     system_prompt: str = "",
                                     estimated_tokens: int = 2000) -> bool:
        """
        带限速的 agent 派发
        
        Args:
            agent_id: Agent ID
            task: 任务描述
            system_prompt: 系统提示
            estimated_tokens: 预估 token 数
        
        Returns:
            是否成功派发
        """
        # 获取预算信息
        budget = self.agent_budgets.get(agent_id, {})
        
        # 调整优先级
        priority_name = budget.get("priority", "NORMAL")
        priority = Priority[priority_name]
        
        # 尝试获取速率限制
        success = acquire_rate_limit(agent_id, estimated_tokens, priority)
        
        if success:
            # 记录使用
            self._record_usage(agent_id, estimated_tokens)
            return True
        
        return False
    
    async def spawn_agent_with_rate_limit_async(self, agent_id: str, task: str,
                                                 system_prompt: str = "",
                                                 estimated_tokens: int = 2000) -> bool:
        """异步带限速的 agent 派发"""
        budget = self.agent_budgets.get(agent_id, {})
        priority_name = budget.get("priority", "NORMAL")
        priority = Priority[priority_name]
        
        success = await self.limiter.acquire(agent_id, estimated_tokens, priority)
        
        if success:
            self._record_usage(agent_id, estimated_tokens)
            return True
        
        return False
    
    def _record_usage(self, agent_id: str, tokens: int):
        """记录使用情况"""
        if agent_id not in self.agent_token_usage:
            self.agent_token_usage[agent_id] = 0
        if agent_id not in self.agent_request_counts:
            self.agent_request_counts[agent_id] = 0
        
        self.agent_token_usage[agent_id] += tokens
        self.agent_request_counts[agent_id] += 1
    
    def get_agent_usage_report(self) -> Dict:
        """获取 agent 使用报告"""
        report = {
            "total_tokens": sum(self.agent_token_usage.values()),
            "total_requests": sum(self.agent_request_counts.values()),
            "agents": {}
        }
        
        for agent_id in set(list(self.agent_token_usage.keys()) + 
                           list(self.agent_request_counts.keys())):
            report["agents"][agent_id] = {
                "tokens": self.agent_token_usage.get(agent_id, 0),
                "requests": self.agent_request_counts.get(agent_id, 0),
                "avg_tokens_per_request": (
                    self.agent_token_usage.get(agent_id, 0) / 
                    max(1, self.agent_request_counts.get(agent_id, 1))
                )
            }
        
        return report
    
    def get_rate_limit_status(self) -> Dict:
        """获取限速状态"""
        metrics = self.limiter.get_metrics()
        
        return {
            "current_rpm": metrics["current_rpm"],
            "current_tpm": metrics["current_tpm"],
            "rpm_limit": self.limiter.config.rpm_limit,
            "tpm_limit": self.limiter.config.tpm_limit,
            "rpm_utilization": metrics["rpm_utilization"],
            "tpm_utilization": metrics["tpm_utilization"],
            "queue_size": metrics["queue_size"],
            "alerts": metrics.get("alerts", []),
            "agent_budgets": self.agent_budgets
        }
    
    def optimize_for_rate_limit(self, tasks: List[Dict]) -> List[Dict]:
        """
        优化任务列表以适应限速
        
        Args:
            tasks: 原始任务列表
        
        Returns:
            优化后的任务列表
        """
        optimized = []
        
        for task in tasks:
            agent_id = task.get("agent_id", "agent-1")
            budget = self.agent_budgets.get(agent_id, {})
            
            # 根据预算调整 token 预估
            max_tpm_per_request = budget.get("tpm_quota", 2_000_000) // 10
            
            # 估算 token
            estimated_tokens = estimate_tokens(
                task.get("system_prompt", "") + 
                task.get("task", "") + 
                task.get("context", "")
            )
            
            # 调整到预算范围内
            if estimated_tokens > max_tpm_per_request:
                estimated_tokens = max_tpm_per_request
                task["token_truncated"] = True
            
            task["estimated_tokens"] = estimated_tokens
            optimized.append(task)
        
        return optimized
    
    def generate_rate_limit_report(self) -> str:
        """生成限速报告"""
        status = self.get_rate_limit_status()
        usage = self.get_agent_usage_report()
        
        report = f"""# MIMO 限速器状态报告

## 当前状态
- RPM: {status['current_rpm']:.1f}/{status['rpm_limit']} ({status['rpm_utilization']*100:.1f}%)
- TPM: {status['current_tpm']:.0f}/{status['tpm_limit']} ({status['tpm_utilization']*100:.1f}%)
- 队列大小: {status['queue_size']}

## Agent 配额分配
"""
        
        for agent_id, budget in status['agent_budgets'].items():
            report += f"- {agent_id}: RPM={budget['rpm_quota']}, TPM={budget['tpm_quota']}\n"
        
        report += f"\n## 使用统计\n"
        report += f"- 总请求: {usage['total_requests']}\n"
        report += f"- 总 Token: {usage['total_tokens']}\n"
        
        if status['alerts']:
            report += f"\n## ⚠️ 告警\n"
            for alert in status['alerts']:
                report += f"- {alert}\n"
        
        return report


# 便捷函数
def create_orchestrator(config: Optional[RateLimitConfig] = None) -> MimoAwareOrchestrator:
    """创建 MIMO 感知的编排器"""
    return MimoAwareOrchestrator(config)


def quick_team_plan(topic: str, max_agents: int = 5) -> Dict:
    """快速生成团队计划"""
    orchestrator = create_orchestrator()
    return orchestrator.plan_team_with_budget(topic, topic, max_agents)


# 测试函数
def test_integration():
    """测试集成"""
    print("=== MIMO 限速器集成测试 ===")
    
    # 创建编排器
    orchestrator = create_orchestrator()
    
    # 规划团队
    plan = orchestrator.plan_team_with_budget(
        topic="分析 AI 市场趋势",
        description="深度分析当前 AI 市场的发展趋势和未来方向",
        max_agents=4
    )
    
    print(f"\n团队计划:")
    print(f"  Agent 数量: {plan['agent_count']}")
    print(f"  配额: RPM={plan['rate_limit_config']['per_agent_rpm']}, "
          f"TPM={plan['rate_limit_config']['per_agent_tpm']}")
    
    print(f"\nAgent 分配:")
    for agent in plan['agents']:
        print(f"  {agent['agent_id']}: {agent['role']} (优先级: {agent['priority']})")
    
    # 测试派发
    print(f"\n测试 agent 派发:")
    for agent in plan['agents']:
        success = orchestrator.spawn_agent_with_rate_limit(
            agent_id=agent['agent_id'],
            task=agent['task'],
            estimated_tokens=3000
        )
        status = "SUCCESS" if success else "FAILED"
        print(f"  {agent['agent_id']}: {status}")
    
    # 获取报告
    print(f"\n限速报告:")
    report = orchestrator.generate_rate_limit_report()
    print(report)
    
    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    test_integration()

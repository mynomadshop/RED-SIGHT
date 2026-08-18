"""
RedSight - High-Performance Local AI Intelligence Platform
Advanced Monitoring & Alerting System

Real-time monitoring of:
- GPU utilization and VRAM
- System resources (CPU, memory, disk)
- API response times and error rates
- Agent task performance
- Learning system metrics
- Custom alerting rules
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertStatus(str, Enum):
    """Alert status."""
    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


@dataclass
class MetricPoint:
    """A single metric data point."""
    name: str
    value: float
    timestamp: float = field(default_factory=time.time)
    tags: Dict[str, str] = field(default_factory=dict)
    unit: str = ""


@dataclass
class AlertRule:
    """A rule for triggering alerts."""
    rule_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""
    metric_name: str = ""
    condition: str = "gt"  # gt, lt, eq, gte, lte
    threshold: float = 0.0
    severity: AlertSeverity = AlertSeverity.WARNING
    enabled: bool = True
    cooldown_seconds: int = 300  # Minimum time between alerts
    last_alert_time: float = 0.0
    description: str = ""


@dataclass
class Alert:
    """An alert instance."""
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    rule_id: str = ""
    rule_name: str = ""
    metric_name: str = ""
    metric_value: float = 0.0
    threshold: float = 0.0
    severity: AlertSeverity = AlertSeverity.WARNING
    status: AlertStatus = AlertStatus.ACTIVE
    message: str = ""
    timestamp: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    acknowledged_by: Optional[str] = None


@dataclass
class SystemHealth:
    """Overall system health status."""
    timestamp: float = field(default_factory=time.time)
    status: str = "healthy"  # healthy, degraded, unhealthy
    components: Dict[str, str] = field(default_factory=dict)
    metrics: Dict[str, float] = field(default_factory=dict)
    active_alerts: int = 0
    total_alerts: int = 0


class MetricCollector:
    """Collects and stores metrics."""
    
    def __init__(self, max_points_per_metric: int = 1000):
        self._metrics: Dict[str, List[MetricPoint]] = {}
        self._max_points = max_points_per_metric
    
    def record(self, name: str, value: float, tags: Optional[Dict[str, str]] = None, unit: str = ""):
        """Record a metric point."""
        if name not in self._metrics:
            self._metrics[name] = []
        
        point = MetricPoint(name=name, value=value, tags=tags or {}, unit=unit)
        self._metrics[name].append(point)
        
        # Trim old points
        if len(self._metrics[name]) > self._max_points:
            self._metrics[name] = self._metrics[name][-self._max_points:]
    
    def get_latest(self, name: str) -> Optional[float]:
        """Get the latest value for a metric."""
        points = self._metrics.get(name, [])
        if points:
            return points[-1].value
        return None
    
    def get_average(self, name: str, last_n: int = 10) -> Optional[float]:
        """Get average of last N values."""
        points = self._metrics.get(name, [])
        if not points:
            return None
        recent = points[-last_n:]
        return sum(p.value for p in recent) / len(recent)
    
    def get_history(self, name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get metric history."""
        points = self._metrics.get(name, [])
        return [
            {
                "timestamp": p.timestamp,
                "value": p.value,
                "tags": p.tags,
                "unit": p.unit,
            }
            for p in points[-limit:]
        ]
    
    def get_all_metrics(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all metrics."""
        return {
            name: self.get_history(name, limit=10)
            for name in self._metrics
        }


class AlertManager:
    """Manages alert rules and triggers."""
    
    def __init__(self, metric_collector: MetricCollector):
        self._collector = metric_collector
        self._rules: Dict[str, AlertRule] = {}
        self._alerts: List[Alert] = []
        self._callbacks: List[Callable[[Alert], None]] = []
    
    def add_rule(self, rule: AlertRule):
        """Add an alert rule."""
        self._rules[rule.rule_id] = rule
        logger.info(f"Added alert rule: {rule.name} ({rule.metric_name} {rule.condition} {rule.threshold})")
    
    def remove_rule(self, rule_id: str):
        """Remove an alert rule."""
        self._rules.pop(rule_id, None)
    
    def add_callback(self, callback: Callable[[Alert], None]):
        """Add a callback for when alerts are triggered."""
        self._callbacks.append(callback)
    
    def evaluate(self):
        """Evaluate all rules against current metrics."""
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            
            # Check cooldown
            if time.time() - rule.last_alert_time < rule.cooldown_seconds:
                continue
            
            # Get metric value
            latest = self._collector.get_latest(rule.metric_name)
            if latest is None:
                continue
            
            # Check condition
            triggered = False
            if rule.condition == "gt" and latest > rule.threshold:
                triggered = True
            elif rule.condition == "lt" and latest < rule.threshold:
                triggered = True
            elif rule.condition == "eq" and latest == rule.threshold:
                triggered = True
            elif rule.condition == "gte" and latest >= rule.threshold:
                triggered = True
            elif rule.condition == "lte" and latest <= rule.threshold:
                triggered = True
            
            if triggered:
                self._trigger_alert(rule, latest)
    
    def _trigger_alert(self, rule: AlertRule, value: float):
        """Trigger an alert."""
        alert = Alert(
            rule_id=rule.rule_id,
            rule_name=rule.name,
            metric_name=rule.metric_name,
            metric_value=value,
            threshold=rule.threshold,
            severity=rule.severity,
            message=f"{rule.name}: {rule.metric_name} = {value} (threshold: {rule.threshold})",
        )
        self._alerts.append(alert)
        rule.last_alert_time = time.time()
        
        logger.warning(f"Alert triggered: {alert.message}")
        
        # Call callbacks
        for callback in self._callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"Alert callback failed: {e}")
    
    def acknowledge_alert(self, alert_id: str, user: str = "system"):
        """Acknowledge an alert."""
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                alert.status = AlertStatus.ACKNOWLEDGED
                alert.acknowledged_by = user
                return True
        return False
    
    def resolve_alert(self, alert_id: str):
        """Resolve an alert."""
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                alert.status = AlertStatus.RESOLVED
                alert.resolved_at = time.time()
                return True
        return False
    
    def get_active_alerts(self) -> List[Dict[str, Any]]:
        """Get all active alerts."""
        return [
            {
                "alert_id": a.alert_id,
                "rule_name": a.rule_name,
                "metric_name": a.metric_name,
                "metric_value": a.metric_value,
                "threshold": a.threshold,
                "severity": a.severity.value,
                "message": a.message,
                "timestamp": a.timestamp,
            }
            for a in self._alerts
            if a.status == AlertStatus.ACTIVE
        ]
    
    def get_all_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all alerts."""
        return [
            {
                "alert_id": a.alert_id,
                "rule_name": a.rule_name,
                "metric_name": a.metric_name,
                "metric_value": a.metric_value,
                "threshold": a.threshold,
                "severity": a.severity.value,
                "status": a.status.value,
                "message": a.message,
                "timestamp": a.timestamp,
                "resolved_at": a.resolved_at,
                "acknowledged_by": a.acknowledged_by,
            }
            for a in self._alerts[-limit:]
        ]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get alert statistics."""
        active = sum(1 for a in self._alerts if a.status == AlertStatus.ACTIVE)
        acknowledged = sum(1 for a in self._alerts if a.status == AlertStatus.ACKNOWLEDGED)
        resolved = sum(1 for a in self._alerts if a.status == AlertStatus.RESOLVED)
        
        return {
            "total_rules": len(self._rules),
            "total_alerts": len(self._alerts),
            "active_alerts": active,
            "acknowledged_alerts": acknowledged,
            "resolved_alerts": resolved,
        }


class SystemMonitor:
    """Monitors system health and resources."""
    
    def __init__(self):
        self._collector = MetricCollector()
        self._alert_manager = AlertManager(self._collector)
        self._health_checks: Dict[str, Callable[[], Tuple[str, bool, str]]] = {}
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
    
    @property
    def alert_manager(self) -> AlertManager:
        return self._alert_manager
    
    @property
    def metric_collector(self) -> MetricCollector:
        return self._collector
    
    def add_health_check(self, name: str, check_fn: Callable[[], Tuple[str, bool, str]]):
        """Add a health check function.
        
        Args:
            name: Check name
            check_fn: Function that returns (status, healthy, message)
        """
        self._health_checks[name] = check_fn
    
    async def start_monitoring(self, interval: float = 5.0):
        """Start continuous monitoring."""
        if self._monitoring:
            return
        
        self._monitoring = True
        self._monitor_task = asyncio.create_task(self._monitor_loop(interval))
        logger.info(f"System monitoring started (interval={interval}s)")
    
    async def stop_monitoring(self):
        """Stop continuous monitoring."""
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        logger.info("System monitoring stopped")
    
    async def _monitor_loop(self, interval: float):
        """Main monitoring loop."""
        while self._monitoring:
            try:
                await self._collect_metrics()
                await self._evaluate_health()
                self._alert_manager.evaluate()
            except Exception as e:
                logger.error(f"Monitoring error: {e}")
            
            await asyncio.sleep(interval)
    
    async def _collect_metrics(self):
        """Collect system metrics."""
        import psutil
        
        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        self._collector.record("cpu_percent", cpu_percent, unit="%")
        
        # Memory
        memory = psutil.virtual_memory()
        self._collector.record("memory_percent", memory.percent, unit="%")
        self._collector.record("memory_available_mb", memory.available / 1024 / 1024, unit="MB")
        
        # Disk
        disk = psutil.disk_usage("/")
        self._collector.record("disk_percent", disk.percent, unit="%")
        self._collector.record("disk_free_gb", disk.free / 1024 / 1024 / 1024, unit="GB")
        
        # Network
        net = psutil.net_io_counters()
        self._collector.record("network_bytes_sent", net.bytes_sent, unit="bytes")
        self._collector.record("network_bytes_recv", net.bytes_recv, unit="bytes")
    
    async def _evaluate_health(self):
        """Evaluate system health."""
        components = {}
        all_healthy = True
        
        # Check registered health checks
        for name, check_fn in self._health_checks.items():
            try:
                status, healthy, message = check_fn()
                components[name] = status
                if not healthy:
                    all_healthy = False
            except Exception as e:
                components[name] = f"error: {e}"
                all_healthy = False
        
        # Determine overall status
        if all_healthy:
            status = "healthy"
        elif any(v == "degraded" for v in components.values()):
            status = "degraded"
        else:
            status = "unhealthy"
        
        # Record health metric
        health_value = 1.0 if all_healthy else 0.0
        self._collector.record("system_health", health_value)
    
    def get_health(self) -> SystemHealth:
        """Get current system health."""
        components = {}
        for name, check_fn in self._health_checks.items():
            try:
                status, healthy, message = check_fn()
                components[name] = status
            except Exception as e:
                components[name] = f"error: {e}"
        
        active_alerts = len(self._alert_manager.get_active_alerts())
        
        # Determine overall status
        healthy_count = sum(1 for v in components.values() if v == "healthy")
        total_count = len(components) if components else 1
        
        if healthy_count == total_count:
            status = "healthy"
        elif healthy_count > total_count / 2:
            status = "degraded"
        else:
            status = "unhealthy"
        
        return SystemHealth(
            status=status,
            components=components,
            metrics={
                "cpu_percent": self._collector.get_latest("cpu_percent") or 0,
                "memory_percent": self._collector.get_latest("memory_percent") or 0,
                "disk_percent": self._collector.get_latest("disk_percent") or 0,
                "system_health": self._collector.get_latest("system_health") or 1.0,
            },
            active_alerts=active_alerts,
            total_alerts=len(self._alert_manager.get_all_alerts()),
        )
    
    def get_metrics(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all collected metrics."""
        return self._collector.get_all_metrics()
    
    def get_alert_stats(self) -> Dict[str, Any]:
        """Get alert statistics."""
        return self._alert_manager.get_stats()
    
    def reset(self):
        """Reset monitor state."""
        self._collector = MetricCollector()
        self._alert_manager = AlertManager(self._collector)

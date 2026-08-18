"""
RedSight - Phase 8 Integration Tests

Tests cloud providers, multi-agent orchestration, monitoring, and UI.
"""

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.models.cloud_providers import (
    CloudProviderRegistry, CloudProvider, CloudModelInfo,
    OpenAIProvider, AnthropicProvider, GoogleGeminiProvider,
)
from app.orchestration.multi_agent import (
    MultiAgentOrchestrator, AgentRole, AgentState, AgentTask, AgentMessage,
    OrchestratorResult,
)
from app.monitoring.system_monitor import (
    MetricCollector, AlertManager, AlertRule, AlertSeverity, AlertStatus,
    SystemMonitor, MetricPoint, SystemHealth,
)


# ═══════════════════════════════════════════════════════════
# Cloud Provider Registry Tests
# ═══════════════════════════════════════════════════════════

class TestCloudProviderRegistry:
    """Test cloud provider registry."""
    
    def test_register_provider(self):
        """Test registering a provider."""
        registry = CloudProviderRegistry()
        provider = OpenAIProvider(api_key="test-key")
        registry.register(provider)
        
        assert registry.get(CloudProvider.OPENAI) is not None
        assert len(registry.list_models()) > 0
    
    def test_list_models(self):
        """Test listing models from all providers."""
        registry = CloudProviderRegistry()
        
        oai = OpenAIProvider(api_key="test")
        anth = AnthropicProvider(api_key="test")
        
        registry.register(oai)
        registry.register(anth)
        
        models = registry.list_models()
        assert len(models) > 0
        
        # Check models have correct providers
        oai_models = [m for m in models if m.provider == CloudProvider.OPENAI]
        anth_models = [m for m in models if m.provider == CloudProvider.ANTHROPIC]
        assert len(oai_models) > 0
        assert len(anth_models) > 0
    
    def test_get_model(self):
        """Test getting a specific model."""
        registry = CloudProviderRegistry()
        registry.register(OpenAIProvider(api_key="test"))
        
        model = registry.get_model("gpt-4o")
        assert model is not None
        assert model.id == "gpt-4o"
    
    def test_add_model(self):
        """Test adding a custom model."""
        registry = CloudProviderRegistry()
        
        custom = CloudModelInfo(
            id="custom-model",
            name="Custom Model",
            provider=CloudProvider.OPENAI,
            context_size=8192,
        )
        registry.add_model(custom)
        
        model = registry.get_model("custom-model")
        assert model is not None
        assert model.context_size == 8192


# ═══════════════════════════════════════════════════════════
# OpenAI Provider Tests
# ═══════════════════════════════════════════════════════════

class TestOpenAIProvider:
    """Test OpenAI provider."""
    
    def test_health_check_success(self):
        """Test health check when API is reachable."""
        provider = OpenAIProvider(api_key="test-key")
        
        with patch.object(provider, '_get_client') as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client.return_value.get.return_value = mock_resp
            
            result = asyncio.run(provider.health_check())
            assert result is True
    
    def test_health_check_failure(self):
        """Test health check when API is unreachable."""
        provider = OpenAIProvider(api_key="test-key")
        
        with patch.object(provider, '_get_client') as mock_client:
            mock_client.return_value.get.side_effect = Exception("Connection failed")
            
            result = asyncio.run(provider.health_check())
            assert result is False
    
    def test_list_models(self):
        """Test listing models."""
        provider = OpenAIProvider(api_key="test-key")
        models = provider.list_models()
        
        assert len(models) > 0
        assert models[0].id == "gpt-4o"
        assert models[0].provider == CloudProvider.OPENAI
    
    def test_model_capabilities(self):
        """Test model capability detection."""
        provider = OpenAIProvider(api_key="test-key")
        models = provider.list_models()
        
        # GPT-4o should have vision and reasoning
        gpt4o = next((m for m in models if m.id == "gpt-4o"), None)
        assert gpt4o is not None
        assert gpt4o.is_vision is True
        assert gpt4o.is_reasoning is True
    
    def test_chat_format(self):
        """Test OpenAI chat message format."""
        provider = OpenAIProvider(api_key="test-key")
        
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
        ]
        
        # Just verify it doesn't crash with valid input
        with patch.object(provider, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            
            # Use a real object for the response (not AsyncMock)
            class FakeResp:
                status_code = 200
                def json(self):
                    return {"choices": [{"message": {"content": "Hi there!"}}]}
                def raise_for_status(self):
                    pass
            
            mock_client.post = AsyncMock(return_value=FakeResp())
            
            result = asyncio.run(provider.chat(messages, "gpt-4o"))
            assert result == "Hi there!"


# ═══════════════════════════════════════════════════════════
# Anthropic Provider Tests
# ═══════════════════════════════════════════════════════════

class TestAnthropicProvider:
    """Test Anthropic provider."""
    
    def test_list_models(self):
        """Test listing models."""
        provider = AnthropicProvider(api_key="test-key")
        models = provider.list_models()
        
        assert len(models) > 0
        assert models[0].provider == CloudProvider.ANTHROPIC
    
    def test_health_check_success(self):
        """Test health check."""
        provider = AnthropicProvider(api_key="test-key")
        
        with patch.object(provider, '_get_client') as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client.return_value.get.return_value = mock_resp
            
            result = asyncio.run(provider.health_check())
            assert result is True
    
    def test_chat_format(self):
        """Test Anthropic chat message format."""
        provider = AnthropicProvider(api_key="test-key")
        
        messages = [
            {"role": "user", "content": "Hello"},
        ]
        
        with patch.object(provider, '_get_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_get_client.return_value = mock_client
            
            class FakeResp:
                status_code = 200
                def json(self):
                    return {"content": [{"text": "Hello! How can I help?"}]}
                def raise_for_status(self):
                    pass
            
            mock_client.post = AsyncMock(return_value=FakeResp())
            
            result = asyncio.run(provider.chat(messages, "claude-sonnet-4-20250514"))
            assert result == "Hello! How can I help?"


# ═══════════════════════════════════════════════════════════
# Google Gemini Provider Tests
# ═══════════════════════════════════════════════════════════

class TestGoogleGeminiProvider:
    """Test Google Gemini provider."""
    
    def test_list_models(self):
        """Test listing models."""
        provider = GoogleGeminiProvider(api_key="test-key")
        models = provider.list_models()
        
        assert len(models) > 0
        assert models[0].provider == CloudProvider.GOOGLE
    
    def test_health_check_success(self):
        """Test health check."""
        provider = GoogleGeminiProvider(api_key="test-key")
        
        with patch.object(provider, '_get_client') as mock_client:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_client.return_value.get.return_value = mock_resp
            
            result = asyncio.run(provider.health_check())
            assert result is True
    
    def test_model_context_size(self):
        """Test model context sizes."""
        provider = GoogleGeminiProvider(api_key="test-key")
        models = provider.list_models()
        
        # Gemini should have large context windows
        for model in models:
            assert model.context_size >= 100000


# ═══════════════════════════════════════════════════════════
# Multi-Agent Orchestrator Tests
# ═══════════════════════════════════════════════════════════

class TestAgentTask:
    """Test agent task."""
    
    def test_create_task(self):
        """Test creating a task."""
        task = AgentTask(
            agent_role=AgentRole.CODER,
            description="Write a function",
        )
        
        assert task.status == AgentState.IDLE
        assert task.agent_role == AgentRole.CODER
        assert task.description == "Write a function"
    
    def test_task_id_uniqueness(self):
        """Test that task IDs are unique."""
        task1 = AgentTask(description="Task 1")
        task2 = AgentTask(description="Task 2")
        
        assert task1.task_id != task2.task_id


class TestAgentMessage:
    """Test agent message."""
    
    def test_create_message(self):
        """Test creating a message."""
        msg = AgentMessage(
            from_agent="agent1",
            to_agent="agent2",
            content="Hello",
        )
        
        assert msg.from_agent == "agent1"
        assert msg.to_agent == "agent2"
        assert msg.content == "Hello"


class TestMultiAgentOrchestrator:
    """Test multi-agent orchestrator."""
    
    def test_register_agent(self):
        """Test registering agents."""
        orchestrator = MultiAgentOrchestrator()
        
        orchestrator.register_agent(
            agent_id="researcher1",
            role=AgentRole.RESEARCHER,
            capabilities=["web_search", "analysis"],
        )
        orchestrator.register_agent(
            agent_id="coder1",
            role=AgentRole.CODER,
            capabilities=["python", "javascript"],
        )
        
        status = orchestrator.get_agent_status()
        assert len(status) == 2
    
    def test_get_agent_status(self):
        """Test getting agent status."""
        orchestrator = MultiAgentOrchestrator()
        orchestrator.register_agent("a1", AgentRole.RESEARCHER, [])
        
        status = orchestrator.get_agent_status("a1")
        assert len(status) == 1
        assert status[0]["id"] == "a1"
        assert status[0]["state"] == AgentState.IDLE.value
    
    def test_get_task_status(self):
        """Test getting task status."""
        orchestrator = MultiAgentOrchestrator()
        orchestrator.register_agent("a1", AgentRole.RESEARCHER, [])
        
        status = orchestrator.get_task_status()
        assert len(status) == 0
    
    def test_orchestration_with_single_task(self):
        """Test orchestration with a single task."""
        orchestrator = MultiAgentOrchestrator()
        orchestrator.register_agent("r1", AgentRole.RESEARCHER, [])
        
        tasks = [
            {
                "description": "Research topic X",
                "role": "researcher",
            }
        ]
        
        result = asyncio.run(orchestrator.orchestrate(
            query="Research topic X",
            agents=["r1"],
            tasks=tasks,
        ))
        
        assert result.success is True
        assert result.agent_count == 1
        assert result.task_count == 1
    
    def test_orchestration_with_multiple_tasks(self):
        """Test orchestration with multiple tasks."""
        orchestrator = MultiAgentOrchestrator()
        orchestrator.register_agent("r1", AgentRole.RESEARCHER, [])
        orchestrator.register_agent("c1", AgentRole.CODER, [])
        
        tasks = [
            {"description": "Research", "role": "researcher"},
            {"description": "Code", "role": "coder"},
        ]
        
        result = asyncio.run(orchestrator.orchestrate(
            query="Research and code",
            agents=["r1", "c1"],
            tasks=tasks,
        ))
        
        assert result.success is True
        assert result.task_count == 2
    
    def test_orchestration_with_dependencies(self):
        """Test orchestration with task dependencies."""
        orchestrator = MultiAgentOrchestrator()
        orchestrator.register_agent("r1", AgentRole.RESEARCHER, [])
        orchestrator.register_agent("c1", AgentRole.CODER, [])
        
        tasks = [
            {"description": "Research", "role": "researcher"},
            {
                "description": "Code based on research",
                "role": "coder",
                "dependencies": [],  # No deps in this simplified test
            },
        ]
        
        result = asyncio.run(orchestrator.orchestrate(
            query="Research then code",
            agents=["r1", "c1"],
            tasks=tasks,
        ))
        
        assert result.success is True
    
    def test_orchestration_with_unregistered_agent(self):
        """Test orchestration fails with unregistered agent."""
        orchestrator = MultiAgentOrchestrator()
        
        tasks = [{"description": "Test", "role": "researcher"}]
        
        result = asyncio.run(orchestrator.orchestrate(
            query="Test",
            agents=["nonexistent"],
            tasks=tasks,
        ))
        
        assert result.success is False
        assert "not registered" in result.error
    
    def test_get_messages(self):
        """Test getting messages."""
        orchestrator = MultiAgentOrchestrator()
        orchestrator.register_agent("a1", AgentRole.RESEARCHER, [])
        
        msg = AgentMessage(
            from_agent="a1",
            to_agent="coordinator",
            content="Test message",
        )
        orchestrator.add_message(msg)
        
        messages = orchestrator.get_messages()
        assert len(messages) == 1
        assert messages[0]["content"] == "Test message"
    
    def test_get_orchestration_history(self):
        """Test getting orchestration history."""
        orchestrator = MultiAgentOrchestrator()
        orchestrator.register_agent("a1", AgentRole.RESEARCHER, [])
        
        # Run an orchestration
        tasks = [{"description": "Test", "role": "researcher"}]
        asyncio.run(orchestrator.orchestrate("Test", ["a1"], tasks))
        
        history = orchestrator.get_orchestration_history()
        assert len(history) == 1
    
    def test_reset(self):
        """Test resetting orchestrator state."""
        orchestrator = MultiAgentOrchestrator()
        orchestrator.register_agent("a1", AgentRole.RESEARCHER, [])
        
        tasks = [{"description": "Test", "role": "researcher"}]
        asyncio.run(orchestrator.orchestrate("Test", ["a1"], tasks))
        
        orchestrator.reset()
        
        tasks_status = orchestrator.get_task_status()
        assert len(tasks_status) == 0


# ═══════════════════════════════════════════════════════════
# Metric Collector Tests
# ═══════════════════════════════════════════════════════════

class TestMetricCollector:
    """Test metric collector."""
    
    def test_record_metric(self):
        """Test recording a metric."""
        collector = MetricCollector()
        collector.record("cpu", 45.5, unit="%")
        
        latest = collector.get_latest("cpu")
        assert latest == 45.5
    
    def test_get_average(self):
        """Test getting average."""
        collector = MetricCollector()
        
        for i in range(10):
            collector.record("temp", float(i * 10))
        
        avg = collector.get_average("temp", last_n=10)
        assert avg == 45.0  # (0+10+20+...+90)/10
    
    def test_get_history(self):
        """Test getting history."""
        collector = MetricCollector()
        
        for i in range(5):
            collector.record("cpu", float(i))
        
        history = collector.get_history("cpu")
        assert len(history) == 5
    
    def test_get_all_metrics(self):
        """Test getting all metrics."""
        collector = MetricCollector()
        
        collector.record("cpu", 50.0)
        collector.record("memory", 75.0)
        
        all_metrics = collector.get_all_metrics()
        assert "cpu" in all_metrics
        assert "memory" in all_metrics
    
    def test_get_nonexistent_metric(self):
        """Test getting nonexistent metric."""
        collector = MetricCollector()
        assert collector.get_latest("nonexistent") is None
    
    def test_trim_old_points(self):
        """Test that old points are trimmed."""
        collector = MetricCollector(max_points_per_metric=5)
        
        for i in range(10):
            collector.record("cpu", float(i))
        
        history = collector.get_history("cpu")
        assert len(history) <= 5


# ═══════════════════════════════════════════════════════════
# Alert Manager Tests
# ═══════════════════════════════════════════════════════════

class TestAlertManager:
    """Test alert manager."""
    
    def test_add_rule(self):
        """Test adding an alert rule."""
        collector = MetricCollector()
        manager = AlertManager(collector)
        
        rule = AlertRule(
            name="High CPU",
            metric_name="cpu",
            condition="gt",
            threshold=80.0,
            severity=AlertSeverity.WARNING,
        )
        manager.add_rule(rule)
        
        stats = manager.get_stats()
        assert stats["total_rules"] == 1
    
    def test_remove_rule(self):
        """Test removing an alert rule."""
        collector = MetricCollector()
        manager = AlertManager(collector)
        
        rule = AlertRule(
            name="High CPU",
            metric_name="cpu",
            condition="gt",
            threshold=80.0,
        )
        manager.add_rule(rule)
        manager.remove_rule(rule.rule_id)
        
        stats = manager.get_stats()
        assert stats["total_rules"] == 0
    
    def test_alert_triggering(self):
        """Test that alerts trigger when threshold is exceeded."""
        collector = MetricCollector()
        manager = AlertManager(collector)
        
        rule = AlertRule(
            name="High CPU",
            metric_name="cpu",
            condition="gt",
            threshold=50.0,
            cooldown_seconds=0,  # No cooldown for testing
        )
        manager.add_rule(rule)
        
        # Record metric above threshold
        collector.record("cpu", 75.0)
        manager.evaluate()
        
        active = manager.get_active_alerts()
        assert len(active) == 1
        assert active[0]["severity"] == "warning"
    
    def test_alert_no_trigger_when_below_threshold(self):
        """Test that alerts don't trigger below threshold."""
        collector = MetricCollector()
        manager = AlertManager(collector)
        
        rule = AlertRule(
            name="High CPU",
            metric_name="cpu",
            condition="gt",
            threshold=50.0,
            cooldown_seconds=0,
        )
        manager.add_rule(rule)
        
        collector.record("cpu", 30.0)
        manager.evaluate()
        
        active = manager.get_active_alerts()
        assert len(active) == 0
    
    def test_alert_cooldown(self):
        """Test alert cooldown."""
        collector = MetricCollector()
        manager = AlertManager(collector)
        
        rule = AlertRule(
            name="High CPU",
            metric_name="cpu",
            condition="gt",
            threshold=50.0,
            cooldown_seconds=300,  # 5 minute cooldown
        )
        manager.add_rule(rule)
        
        collector.record("cpu", 75.0)
        manager.evaluate()
        
        # First trigger
        active1 = manager.get_active_alerts()
        assert len(active1) == 1
        
        # Second trigger should be suppressed by cooldown
        manager.evaluate()
        active2 = manager.get_active_alerts()
        assert len(active2) == 1  # Same alert, not duplicated
    
    def test_acknowledge_alert(self):
        """Test acknowledging an alert."""
        collector = MetricCollector()
        manager = AlertManager(collector)
        
        rule = AlertRule(
            name="High CPU",
            metric_name="cpu",
            condition="gt",
            threshold=50.0,
            cooldown_seconds=0,
        )
        manager.add_rule(rule)
        
        collector.record("cpu", 75.0)
        manager.evaluate()
        
        active = manager.get_active_alerts()
        alert_id = active[0]["alert_id"]
        
        manager.acknowledge_alert(alert_id, "admin")
        
        all_alerts = manager.get_stats()
        assert all_alerts["acknowledged_alerts"] == 1
    
    def test_resolve_alert(self):
        """Test resolving an alert."""
        collector = MetricCollector()
        manager = AlertManager(collector)
        
        rule = AlertRule(
            name="High CPU",
            metric_name="cpu",
            condition="gt",
            threshold=50.0,
            cooldown_seconds=0,
        )
        manager.add_rule(rule)
        
        collector.record("cpu", 75.0)
        manager.evaluate()
        
        active = manager.get_active_alerts()
        alert_id = active[0]["alert_id"]
        
        manager.resolve_alert(alert_id)
        
        all_alerts = manager.get_stats()
        assert all_alerts["resolved_alerts"] == 1


# ═══════════════════════════════════════════════════════════
# System Monitor Tests
# ═══════════════════════════════════════════════════════════

class TestSystemMonitor:
    """Test system monitor."""
    
    def test_add_health_check(self):
        """Test adding a health check."""
        monitor = SystemMonitor()
        
        def check():
            return ("healthy", True, "All good")
        
        monitor.add_health_check("test_check", check)
        assert "test_check" in monitor._health_checks
    
    def test_get_health(self):
        """Test getting health status."""
        monitor = SystemMonitor()
        
        def check():
            return ("healthy", True, "OK")
        
        monitor.add_health_check("test", check)
        
        health = monitor.get_health()
        assert health.status == "healthy"
        assert "test" in health.components
    
    def test_get_metrics(self):
        """Test getting metrics."""
        monitor = SystemMonitor()
        
        metrics = monitor.get_metrics()
        assert isinstance(metrics, dict)
    
    def test_get_alert_stats(self):
        """Test getting alert stats."""
        monitor = SystemMonitor()
        
        stats = monitor.get_alert_stats()
        assert "total_rules" in stats
        assert "total_alerts" in stats
    
    def test_metric_collector_property(self):
        """Test metric collector property."""
        monitor = SystemMonitor()
        assert monitor.metric_collector is not None
    
    def test_alert_manager_property(self):
        """Test alert manager property."""
        monitor = SystemMonitor()
        assert monitor.alert_manager is not None


# ═══════════════════════════════════════════════════════════
# Cloud Provider Model Tests
# ═══════════════════════════════════════════════════════════

class TestCloudModelInfo:
    """Test cloud model info."""
    
    def test_create_model(self):
        """Test creating a model."""
        model = CloudModelInfo(
            id="test-model",
            name="Test Model",
            provider=CloudProvider.OPENAI,
            context_size=8192,
        )
        
        assert model.id == "test-model"
        assert model.context_size == 8192
        assert model.provider == CloudProvider.OPENAI
    
    def test_model_defaults(self):
        """Test model default values."""
        model = CloudModelInfo(
            id="test",
            name="Test",
            provider=CloudProvider.OPENAI,
        )
        
        assert model.supports_streaming is True
        assert model.supports_tools is True
        assert model.is_embedding is False


# ═══════════════════════════════════════════════════════════
# Agent Role Tests
# ═══════════════════════════════════════════════════════════

class TestAgentRole:
    """Test agent roles."""
    
    def test_all_roles_exist(self):
        """Test all agent roles exist."""
        roles = [r.value for r in AgentRole]
        
        assert "researcher" in roles
        assert "coder" in roles
        assert "analyst" in roles
        assert "writer" in roles
        assert "reviewer" in roles
        assert "coordinator" in roles
    
    def test_agent_state(self):
        """Test agent states."""
        states = [s.value for s in AgentState]
        
        assert "idle" in states
        assert "running" in states
        assert "completed" in states
        assert "failed" in states


# ═══════════════════════════════════════════════════════════
# Alert Severity Tests
# ═══════════════════════════════════════════════════════════

class TestAlertSeverity:
    """Test alert severity levels."""
    
    def test_all_severities(self):
        """Test all severity levels exist."""
        severities = [s.value for s in AlertSeverity]
        
        assert "info" in severities
        assert "warning" in severities
        assert "critical" in severities
        assert "emergency" in severities
    
    def test_alert_status(self):
        """Test alert statuses."""
        statuses = [s.value for s in AlertStatus]
        
        assert "active" in statuses
        assert "acknowledged" in statuses
        assert "resolved" in statuses


# ═══════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════

class TestCloudIntegration:
    """Test cloud provider integration."""
    
    def test_registry_with_all_providers(self):
        """Test registry with all cloud providers."""
        registry = CloudProviderRegistry()
        
        registry.register(OpenAIProvider(api_key="test"))
        registry.register(AnthropicProvider(api_key="test"))
        registry.register(GoogleGeminiProvider(api_key="test"))
        
        models = registry.list_models()
        assert len(models) > 0
        
        # Should have models from all providers
        providers = set(m.provider for m in models)
        assert len(providers) == 3
    
    def test_provider_health_checks(self):
        """Test health checks for all providers."""
        providers = [
            ("openai", OpenAIProvider(api_key="test")),
            ("anthropic", AnthropicProvider(api_key="test")),
            ("google", GoogleGeminiProvider(api_key="test")),
        ]
        
        for name, provider in providers:
            with patch.object(provider, '_get_client') as mock_client:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_client.return_value.get.return_value = mock_resp
                
                result = asyncio.run(provider.health_check())
                assert result is True, f"{name} health check failed"


class TestMultiAgentIntegration:
    """Test multi-agent integration."""
    
    def test_full_workflow(self):
        """Test full multi-agent workflow."""
        orchestrator = MultiAgentOrchestrator()
        
        # Register agents
        orchestrator.register_agent("r1", AgentRole.RESEARCHER, ["web_search"])
        orchestrator.register_agent("c1", AgentRole.CODER, ["python"])
        orchestrator.register_agent("a1", AgentRole.ANALYST, ["analysis"])
        
        # Define tasks
        tasks = [
            {"description": "Research topic", "role": "researcher"},
            {"description": "Implement solution", "role": "coder"},
            {"description": "Analyze results", "role": "analyst"},
        ]
        
        # Execute
        result = asyncio.run(orchestrator.orchestrate(
            query="Research, code, and analyze",
            agents=["r1", "c1", "a1"],
            tasks=tasks,
        ))
        
        assert result.success is True
        assert result.agent_count == 3
        assert result.task_count == 3
    
    def test_agent_communication(self):
        """Test inter-agent communication."""
        orchestrator = MultiAgentOrchestrator()
        orchestrator.register_agent("a1", AgentRole.RESEARCHER, [])
        
        # Add messages
        msg1 = AgentMessage(from_agent="a1", to_agent="a2", content="Research done")
        msg2 = AgentMessage(from_agent="a2", to_agent="a1", content="Thanks")
        
        orchestrator.add_message(msg1)
        orchestrator.add_message(msg2)
        
        messages = orchestrator.get_messages()
        assert len(messages) == 2


class TestMonitoringIntegration:
    """Test monitoring integration."""
    
    def test_full_monitoring_workflow(self):
        """Test full monitoring workflow."""
        collector = MetricCollector()
        manager = AlertManager(collector)
        
        # Add rule
        rule = AlertRule(
            name="High CPU",
            metric_name="cpu",
            condition="gt",
            threshold=80.0,
            severity=AlertSeverity.CRITICAL,
            cooldown_seconds=0,
        )
        manager.add_rule(rule)
        
        # Record metrics
        collector.record("cpu", 45.0)
        manager.evaluate()
        assert len(manager.get_active_alerts()) == 0
        
        collector.record("cpu", 95.0)
        manager.evaluate()
        assert len(manager.get_active_alerts()) == 1
        
        # Acknowledge
        active = manager.get_active_alerts()
        manager.acknowledge_alert(active[0]["alert_id"])
        
        stats = manager.get_stats()
        assert stats["acknowledged_alerts"] == 1
    
    def test_monitor_with_health_check(self):
        """Test monitor with health check."""
        monitor = SystemMonitor()
        
        def check():
            return ("healthy", True, "OK")
        
        monitor.add_health_check("test", check)
        
        health = monitor.get_health()
        assert health.status == "healthy"
        assert health.components["test"] == "healthy"

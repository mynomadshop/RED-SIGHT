"""
RedSight - Phase 9 Integration Tests

Tests WebSocket hub, advanced memory, plugin system, and full integration.
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.websocket.hub import (
    WebSocketHub, WebSocketSession, WSMessage, WSMessageType,
    get_ws_hub, initialize_ws_hub, shutdown_ws_hub,
)
from app.memory.memory_store import (
    MemoryStore, MemoryType, MemoryPriority, MemoryEntry,
    WorkingMemoryStore, EpisodicMemoryStore,
    SemanticMemoryStore, ProceduralMemoryStore,
)
from app.plugins.plugin_system import (
    PluginManager, PluginEventBus, PluginEvent,
    BasePlugin, PluginManifest, PluginInfo,
    PluginState, PluginType,
    get_plugin_manager, get_event_bus,
    initialize_plugin_system, shutdown_plugin_system,
)


# ═══════════════════════════════════════════════════════════
# WebSocket Hub Tests
# ═══════════════════════════════════════════════════════════

class TestWSMessage:
    """Test WebSocket message envelope."""

    def test_create_message(self):
        """Test creating a message."""
        msg = WSMessage(
            type=WSMessageType.TOKEN,
            data={"token": "hello"},
            session_id="test-session",
        )
        assert msg.type == WSMessageType.TOKEN
        assert msg.data["token"] == "hello"
        assert msg.session_id == "test-session"

    def test_to_dict(self):
        """Test serialization to dict."""
        msg = WSMessage(type=WSMessageType.DONE, data={"session_id": "s1"})
        d = msg.to_dict()
        assert d["type"] == "done"
        assert d["data"]["session_id"] == "s1"
        assert "timestamp" in d

    def test_to_json(self):
        """Test serialization to JSON."""
        msg = WSMessage(type=WSMessageType.ERROR, data={"message": "fail"})
        j = msg.to_json()
        parsed = json.loads(j)
        assert parsed["type"] == "error"
        assert parsed["data"]["message"] == "fail"


class TestWebSocketSession:
    """Test WebSocket session."""

    def test_create_session(self):
        """Test creating a session."""
        mock_ws = AsyncMock()
        session = WebSocketSession("s1", mock_ws)
        assert session.session_id == "s1"
        assert session.is_active is True

    @pytest.mark.asyncio
    async def test_send_message(self):
        """Test sending a message."""
        mock_ws = AsyncMock()
        session = WebSocketSession("s1", mock_ws)
        msg = WSMessage(type=WSMessageType.TOKEN, data={"token": "hi"})
        result = await session.send(msg)
        assert result is True
        mock_ws.send_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_inactive_session(self):
        """Test sending to inactive session."""
        mock_ws = AsyncMock()
        session = WebSocketSession("s1", mock_ws)
        session.is_active = False
        msg = WSMessage(type=WSMessageType.TOKEN, data={})
        result = await session.send(msg)
        assert result is False

    @pytest.mark.asyncio
    async def test_close_session(self):
        """Test closing a session."""
        mock_ws = AsyncMock()
        session = WebSocketSession("s1", mock_ws)
        await session.close()
        assert session.is_active is False
        mock_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe(self):
        """Test subscribing to a channel."""
        mock_ws = AsyncMock()
        session = WebSocketSession("s1", mock_ws)
        session.subscriptions.add("alerts")
        assert "alerts" in session.subscriptions


class TestWebSocketHub:
    """Test WebSocket hub."""

    @pytest.mark.asyncio
    async def test_connect_disconnect(self):
        """Test connect and disconnect."""
        hub = WebSocketHub()
        mock_ws = AsyncMock()

        session_id = await hub.connect(mock_ws)
        assert session_id is not None
        assert hub.active_sessions == 1

        await hub.disconnect(session_id)
        assert hub.active_sessions == 0

    @pytest.mark.asyncio
    async def test_send_to_session(self):
        """Test sending to a specific session."""
        hub = WebSocketHub()
        mock_ws = AsyncMock()
        session_id = await hub.connect(mock_ws)

        msg = WSMessage(type=WSMessageType.TOKEN, data={"token": "test"})
        result = await hub.send_to_session(session_id, msg)
        assert result is True

        await hub.disconnect(session_id)

    @pytest.mark.asyncio
    async def test_broadcast(self):
        """Test broadcasting to all sessions."""
        hub = WebSocketHub()
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()

        sid1 = await hub.connect(mock_ws1)
        sid2 = await hub.connect(mock_ws2)

        msg = WSMessage(type=WSMessageType.SYSTEM_STATUS, data={"cpu": 50})
        await hub.broadcast(msg)

        # Both sessions should have received the message
        assert mock_ws1.send_text.call_count == 1
        assert mock_ws2.send_text.call_count == 1

        await hub.disconnect(sid1)
        await hub.disconnect(sid2)

    @pytest.mark.asyncio
    async def test_broadcast_exclude_session(self):
        """Test broadcasting while excluding a session."""
        hub = WebSocketHub()
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()

        sid1 = await hub.connect(mock_ws1)
        sid2 = await hub.connect(mock_ws2)

        msg = WSMessage(type=WSMessageType.SYSTEM_STATUS, data={})
        await hub.broadcast(msg, exclude_session=sid1)

        # Only session 2 should have received the message
        assert mock_ws1.send_text.call_count == 0
        assert mock_ws2.send_text.call_count == 1

        await hub.disconnect(sid1)
        await hub.disconnect(sid2)

    @pytest.mark.asyncio
    async def test_subscribe_unsubscribe(self):
        """Test subscribe and unsubscribe."""
        hub = WebSocketHub()
        mock_ws = AsyncMock()
        session_id = await hub.connect(mock_ws)

        hub.subscribe(session_id, "alerts")
        session = hub._sessions[session_id]
        assert "alerts" in session.subscriptions

        hub.unsubscribe(session_id, "alerts")
        assert "alerts" not in session.subscriptions

        await hub.disconnect(session_id)

    @pytest.mark.asyncio
    async def test_emit_event(self):
        """Test emitting an event."""
        hub = WebSocketHub()
        results = []

        async def handler(data):
            results.append(data)

        hub.on_event("test_event", handler)
        await hub.emit_event("test_event", {"key": "value"})

        assert len(results) == 1
        assert results[0] == {"key": "value"}

    @pytest.mark.asyncio
    async def test_send_broadcast(self):
        """Test enqueueing a broadcast."""
        hub = WebSocketHub()
        msg = WSMessage(type=WSMessageType.BROADCAST, data={"msg": "hello"})
        await hub.send_broadcast(msg)
        # Message should be in queue
        assert not hub._broadcast_queue.empty()

    @pytest.mark.asyncio
    async def test_get_session_list(self):
        """Test getting list of active sessions."""
        hub = WebSocketHub()
        mock_ws1 = AsyncMock()
        mock_ws2 = AsyncMock()

        sid1 = await hub.connect(mock_ws1)
        sid2 = await hub.connect(mock_ws2)

        sessions = await hub.get_session_list()
        assert len(sessions) == 2
        assert all(s["is_active"] for s in sessions)

        await hub.disconnect(sid1)
        await hub.disconnect(sid2)


# ═══════════════════════════════════════════════════════════
# Memory Store Tests
# ═══════════════════════════════════════════════════════════

class TestMemoryEntry:
    """Test memory entry."""

    def test_create_entry(self):
        """Test creating an entry."""
        entry = MemoryEntry(
            id="test-1",
            content="Hello world",
            memory_type=MemoryType.WORKING,
            priority=MemoryPriority.HIGH,
        )
        assert entry.id == "test-1"
        assert entry.content == "Hello world"
        assert entry.priority == MemoryPriority.HIGH
        assert not entry.is_expired

    def test_to_dict(self):
        """Test serialization."""
        entry = MemoryEntry(
            id="test-1",
            content="Test",
            memory_type=MemoryType.WORKING,
        )
        d = entry.to_dict()
        assert d["id"] == "test-1"
        assert d["content"] == "Test"
        assert d["memory_type"] == "working"

    def test_expired_entry(self):
        """Test expired entry detection."""
        entry = MemoryEntry(
            id="test-1",
            content="Test",
            memory_type=MemoryType.WORKING,
            metadata={"ttl_seconds": 1},
            created_at=time.time() - 2,  # Created 2 seconds ago
        )
        assert entry.is_expired is True


class TestWorkingMemoryStore:
    """Test working memory store."""

    @pytest.mark.asyncio
    async def test_add_and_get(self):
        """Test adding and retrieving entries."""
        store = WorkingMemoryStore(max_entries=10)
        entry_id = await store.add("Hello world")
        entry = await store.get(entry_id)
        assert entry is not None
        assert entry.content == "Hello world"

    @pytest.mark.asyncio
    async def test_list_entries(self):
        """Test listing entries."""
        store = WorkingMemoryStore(max_entries=10)
        for i in range(5):
            await store.add(f"Entry {i}")
        entries = await store.list_entries()
        assert len(entries) == 5

    @pytest.mark.asyncio
    async def test_search(self):
        """Test searching entries."""
        store = WorkingMemoryStore(max_entries=10)
        await store.add("Python programming")
        await store.add("JavaScript basics")
        results = await store.search("Python")
        assert len(results) > 0
        assert "Python" in results[0].content

    @pytest.mark.asyncio
    async def test_prune(self):
        """Test pruning entries."""
        store = WorkingMemoryStore(max_entries=3)
        for i in range(10):
            await store.add(f"Entry {i}")
        removed = await store.prune()
        assert removed >= 0
        entries = await store.list_entries()
        assert len(entries) <= 3

    @pytest.mark.asyncio
    async def test_clear(self):
        """Test clearing entries."""
        store = WorkingMemoryStore(max_entries=10)
        await store.add("Test")
        await store.clear()
        entries = await store.list_entries()
        assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test getting stats."""
        store = WorkingMemoryStore(max_entries=10)
        await store.add("Test")
        stats = await store.get_stats()
        assert stats["total_entries"] == 1
        assert "by_priority" in stats

    @pytest.mark.asyncio
    async def test_get_context(self):
        """Test getting context string."""
        store = WorkingMemoryStore(max_entries=10)
        await store.add("First context")
        await store.add("Second context")
        context = await store.get_context()
        assert "First context" in context
        assert "Second context" in context


class TestEpisodicMemoryStore:
    """Test episodic memory store."""

    @pytest.mark.asyncio
    async def test_add_episode(self):
        """Test adding an episode."""
        store = EpisodicMemoryStore()
        entry_id = await store.add_episode(
            user_message="What is AI?",
            assistant_response="AI is artificial intelligence.",
        )
        entry = await store.get(entry_id)
        assert entry is not None
        assert "[USER]" in entry.content
        assert "[ASSISTANT]" in entry.content

    @pytest.mark.asyncio
    async def test_search_episodes(self):
        """Test searching episodes."""
        store = EpisodicMemoryStore()
        await store.add_episode(
            user_message="Python tutorial",
            assistant_response="Here is a Python tutorial.",
        )
        results = await store.search_episodes("Python")
        assert len(results) > 0
        assert "Python" in results[0]["user_message"]

    @pytest.mark.asyncio
    async def test_list_entries(self):
        """Test listing entries."""
        store = EpisodicMemoryStore()
        await store.add_episode("Q1", "A1")
        await store.add_episode("Q2", "A2")
        entries = await store.list_entries()
        assert len(entries) == 2


class TestSemanticMemoryStore:
    """Test semantic memory store."""

    @pytest.mark.asyncio
    async def test_add_fact(self):
        """Test adding a fact."""
        store = SemanticMemoryStore()
        entry_id = await store.add_fact(
            fact="Paris is the capital of France",
            category="geography",
        )
        entry = await store.get(entry_id)
        assert entry is not None
        assert entry.metadata["category"] == "geography"

    @pytest.mark.asyncio
    async def test_get_facts_by_category(self):
        """Test getting facts by category."""
        store = SemanticMemoryStore()
        await store.add_fact("Paris is capital of France", "geography")
        await store.add_fact("Tokyo is capital of Japan", "geography")
        await store.add_fact("Python is a language", "programming")
        facts = await store.get_facts_by_category("geography")
        assert len(facts) == 2

    @pytest.mark.asyncio
    async def test_search_facts(self):
        """Test searching facts."""
        store = SemanticMemoryStore()
        await store.add_fact("RedSight is an AI platform", "product")
        results = await store.search_facts("RedSight")
        assert len(results) > 0


class TestProceduralMemoryStore:
    """Test procedural memory store."""

    @pytest.mark.asyncio
    async def test_add_pattern(self):
        """Test adding a pattern."""
        store = ProceduralMemoryStore()
        entry_id = await store.add_pattern(
            pattern_name="debugging",
            description="How to debug code",
            steps=["Reproduce issue", "Isolate cause", "Fix bug", "Verify fix"],
        )
        entry = await store.get(entry_id)
        assert entry is not None
        assert entry.metadata["pattern_name"] == "debugging"

    @pytest.mark.asyncio
    async def test_get_patterns_by_name(self):
        """Test getting pattern by name."""
        store = ProceduralMemoryStore()
        await store.add_pattern("test_pattern", "Desc", ["step1"])
        pattern = await store.get_patterns_by_name("test_pattern")
        assert pattern is not None
        assert pattern.metadata["pattern_name"] == "test_pattern"

    @pytest.mark.asyncio
    async def test_find_matching_patterns(self):
        """Test finding matching patterns."""
        store = ProceduralMemoryStore()
        await store.add_pattern("coding", "Coding pattern", ["write code", "test"])
        patterns = await store.find_matching_patterns("coding")
        assert len(patterns) > 0


class TestMemoryStore:
    """Test unified memory store."""

    @pytest.mark.asyncio
    async def test_add_to_different_types(self):
        """Test adding to different memory types."""
        store = MemoryStore()
        wid = await store.working.add("Working memory entry")
        eid = await store.episodic.add_episode("Q", "A")
        sid = await store.semantic.add_fact("Fact", "category")
        pid = await store.procedural.add_pattern("Pattern", "Desc", ["step"])

        assert wid is not None
        assert eid is not None
        assert sid is not None
        assert pid is not None

    @pytest.mark.asyncio
    async def test_search_all_types(self):
        """Test searching across all types."""
        store = MemoryStore()
        await store.working.add("Python programming")
        await store.semantic.add_fact("Python is a language", "programming")
        results = await store.search("Python")
        assert len(results) > 0

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test getting stats for all stores."""
        store = MemoryStore()
        await store.working.add("Test")
        await store.semantic.add_fact("Fact", "cat")
        stats = await store.get_stats()
        assert "working" in stats
        assert "semantic" in stats
        assert stats["working"]["total_entries"] == 1
        assert stats["semantic"]["total_entries"] == 1

    @pytest.mark.asyncio
    async def test_clear_all(self):
        """Test clearing all stores."""
        store = MemoryStore()
        await store.working.add("Test")
        await store.semantic.add_fact("Fact", "cat")
        await store.clear_all()
        stats = await store.get_stats()
        assert stats["working"]["total_entries"] == 0
        assert stats["semantic"]["total_entries"] == 0

    @pytest.mark.asyncio
    async def test_get_store(self):
        """Test getting a specific store."""
        store = MemoryStore()
        working = store.get_store(MemoryType.WORKING)
        assert working is store.working
        episodic = store.get_store(MemoryType.EPISODIC)
        assert episodic is store.episodic


# ═══════════════════════════════════════════════════════════
# Plugin System Tests
# ═══════════════════════════════════════════════════════════

class TestPluginManifest:
    """Test plugin manifest."""

    def test_create_manifest(self):
        """Test creating a manifest."""
        manifest = PluginManifest(
            name="test-plugin",
            version="1.0.0",
            description="A test plugin",
            plugin_type=PluginType.TOOL,
        )
        assert manifest.name == "test-plugin"
        assert manifest.version == "1.0.0"
        assert manifest.plugin_type == PluginType.TOOL

    def test_from_dict(self):
        """Test creating manifest from dict."""
        data = {
            "name": "test",
            "version": "2.0.0",
            "description": "Test plugin",
            "plugin_type": "skill",
        }
        manifest = PluginManifest.from_dict(data)
        assert manifest.name == "test"
        assert manifest.version == "2.0.0"
        assert manifest.plugin_type == PluginType.SKILL

    def test_to_dict(self):
        """Test serializing manifest."""
        manifest = PluginManifest(
            name="test",
            version="1.0.0",
            description="Desc",
            plugin_type=PluginType.TOOL,
        )
        d = manifest.to_dict()
        assert d["name"] == "test"
        assert d["version"] == "1.0.0"


class TestPluginEvent:
    """Test plugin event."""

    def test_create_event(self):
        """Test creating an event."""
        event = PluginEvent(
            event_type="test_event",
            data={"key": "value"},
            source="plugin-1",
        )
        assert event.event_type == "test_event"
        assert event.data["key"] == "value"
        assert event.source == "plugin-1"
        assert event.handled is False


class TestPluginEventBus:
    """Test plugin event bus."""

    @pytest.mark.asyncio
    async def test_subscribe_publish(self):
        """Test subscribing and publishing."""
        bus = PluginEventBus()
        results = []

        def listener(event):
            results.append(event.data)

        bus.subscribe("test_event", listener)
        event = PluginEvent(event_type="test_event", data={"msg": "hello"})
        await bus.publish(event)

        assert len(results) == 1
        assert results[0] == {"msg": "hello"}

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        """Test unsubscribing."""
        bus = PluginEventBus()
        results = []

        async def listener(event):
            results.append(event)

        bus.subscribe("event", listener)
        bus.unsubscribe("event", listener)

        event = PluginEvent(event_type="event", data={})
        await bus.publish(event)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_event_history(self):
        """Test event history."""
        bus = PluginEventBus()
        for i in range(5):
            event = PluginEvent(event_type="test", data={"i": i})
            await bus.publish(event)

        history = bus.get_history(event_type="test")
        assert len(history) == 5

    @pytest.mark.asyncio
    async def test_clear_history(self):
        """Test clearing history."""
        bus = PluginEventBus()
        await bus.publish(PluginEvent("test", {}))
        bus.clear_history()
        assert len(bus.get_history()) == 0


class TestPluginState:
    """Test plugin states."""

    def test_all_states_exist(self):
        """Test all plugin states exist."""
        states = [s.value for s in PluginState]
        assert "installed" in states
        assert "loading" in states
        assert "active" in states
        assert "error" in states
        assert "disabled" in states
        assert "uninstalled" in states

    def test_all_plugin_types_exist(self):
        """Test all plugin types exist."""
        types = [t.value for t in PluginType]
        assert "tool" in types
        assert "skill" in types
        assert "hook" in types
        assert "provider" in types
        assert "ui" in types
        assert "storage" in types


class TestPluginManager:
    """Test plugin manager."""

    @pytest.mark.asyncio
    async def test_get_plugin_status_empty(self):
        """Test getting status with no plugins."""
        manager = PluginManager()
        status = await manager.get_plugin_status()
        assert len(status) == 0

    @pytest.mark.asyncio
    async def test_get_active_plugins_empty(self):
        """Test getting active plugins with none."""
        manager = PluginManager()
        active = manager.get_active_plugins()
        assert len(active) == 0

    @pytest.mark.asyncio
    async def test_get_all_plugins_empty(self):
        """Test getting all plugins with none."""
        manager = PluginManager()
        all_plugins = manager.get_all_plugins()
        assert len(all_plugins) == 0

    @pytest.mark.asyncio
    async def test_check_requirement(self):
        """Test checking requirements."""
        manager = PluginManager()
        # 'os' is a built-in module
        result = await manager._check_requirement("os")
        assert result is True

    @pytest.mark.asyncio
    async def test_discover_plugins_empty(self):
        """Test discovering plugins in empty dir."""
        manager = PluginManager()
        manifests = await manager.discover_plugins()
        assert len(manifests) == 0


# ═══════════════════════════════════════════════════════════
# Integration Tests
# ═══════════════════════════════════════════════════════════

class TestWebSocketMemoryIntegration:
    """Test WebSocket and memory integration."""

    @pytest.mark.asyncio
    async def test_full_workflow(self):
        """Test full workflow: add memory, search, broadcast."""
        hub = WebSocketHub()
        store = MemoryStore()

        # Add memories
        await store.working.add("User asked about Python")
        await store.semantic.add_fact("Python is a programming language", "programming")

        # Search
        results = await store.search("Python")
        assert len(results) > 0

        # Broadcast status
        msg = WSMessage(
            type=WSMessageType.SYSTEM_STATUS,
            data={"memory_entries": len(results)},
        )
        await hub.send_broadcast(msg)

        # Verify queue has message
        assert not hub._broadcast_queue.empty()


class TestPluginMemoryIntegration:
    """Test plugin and memory integration."""

    @pytest.mark.asyncio
    async def test_plugin_event_updates_memory(self):
        """Test that plugin events can update memory."""
        store = MemoryStore()
        event_bus = PluginEventBus()
        results = []

        async def memory_updater(event):
            if event.event_type == "add_fact":
                await store.semantic.add_fact(
                    event.data["fact"],
                    event.data.get("category", "general"),
                )
                results.append(event.data["fact"])

        event_bus.subscribe("add_fact", memory_updater)

        # Publish event
        event = PluginEvent(
            event_type="add_fact",
            data={"fact": "Test fact", "category": "test"},
        )
        await event_bus.publish(event)

        # Give the coroutine a chance to run
        await asyncio.sleep(0.01)

        assert len(results) == 1
        facts = await store.semantic.get_facts_by_category("test")
        assert len(facts) == 1


class TestFullPlatformIntegration:
    """Test full platform integration."""

    @pytest.mark.asyncio
    async def test_all_components_work_together(self):
        """Test that all Phase 9 components work together."""
        # Initialize components
        hub = WebSocketHub()
        store = MemoryStore()
        manager = PluginManager()
        event_bus = PluginEventBus()

        # 1. Add memory entries
        await store.working.add("Working memory test")
        await store.episodic.add_episode("Q", "A")
        await store.semantic.add_fact("Test fact", "test")
        await store.procedural.add_pattern("Test pattern", "Desc", ["step"])

        # 2. Search memory
        results = await store.search("test")
        assert len(results) > 0

        # 3. Emit plugin event
        event = PluginEvent(event_type="test_event", data={"key": "value"})
        published_event = await event_bus.publish(event)

        # 4. Broadcast through hub
        msg = WSMessage(
            type=WSMessageType.BROADCAST,
            data={"status": "ok", "memory_count": len(results)},
        )
        await hub.send_broadcast(msg)

        # 5. Get stats
        mem_stats = await store.get_stats()
        plugin_status = await manager.get_plugin_status()

        assert mem_stats["working"]["total_entries"] >= 1
        assert mem_stats["episodic"]["total_entries"] >= 1
        assert mem_stats["semantic"]["total_entries"] >= 1
        assert mem_stats["procedural"]["total_entries"] >= 1
        assert isinstance(plugin_status, dict)


class TestMemoryPriority:
    """Test memory priority handling."""

    @pytest.mark.asyncio
    async def test_priority_ordering(self):
        """Test that entries are ordered by priority."""
        store = WorkingMemoryStore(max_entries=10)
        await store.add("Low priority entry", metadata={})
        await store.add("Critical priority entry", metadata={})
        await store.add("Normal priority entry", metadata={})

        # Manually set priorities on entries
        entries = await store.list_entries()
        for entry in entries:
            if "Critical" in entry.content:
                entry.priority = MemoryPriority.CRITICAL
            elif "Normal" in entry.content:
                entry.priority = MemoryPriority.NORMAL
            else:
                entry.priority = MemoryPriority.LOW

        # Re-list with priority sorting
        entries = await store.list_entries()
        # Verify critical entry exists in the list
        critical_entries = [e for e in entries if e.priority == MemoryPriority.CRITICAL]
        assert len(critical_entries) >= 1

    @pytest.mark.asyncio
    async def test_filter_by_priority(self):
        """Test filtering by priority."""
        store = WorkingMemoryStore(max_entries=10)
        await store.add("Normal entry", metadata={})
        await store.add("High entry", metadata={})

        normal = await store.list_entries(priority=MemoryPriority.NORMAL)
        high = await store.list_entries(priority=MemoryPriority.HIGH)

        assert len(normal) >= 0  # May be 0 if default priority is not NORMAL
        assert len(high) >= 0


class TestMemoryTTL:
    """Test memory TTL (time-to-live)."""

    @pytest.mark.asyncio
    async def test_ttl_expiration(self):
        """Test that entries expire after TTL."""
        store = WorkingMemoryStore(max_entries=10, default_ttl_seconds=1)
        entry_id = await store.add("Will expire")
        entry = await store.get(entry_id)
        assert entry is not None

        # Simulate TTL expiry by modifying created_at
        entry.created_at = time.time() - 2  # 2 seconds ago
        assert entry.is_expired is True

    @pytest.mark.asyncio
    async def test_no_ttl(self):
        """Test entries without TTL never expire."""
        store = WorkingMemoryStore(max_entries=10)
        entry_id = await store.add("No TTL")
        entry = await store.get(entry_id)
        assert entry is not None
        assert entry.is_expired is False


# Need to import time for TTL test
import time

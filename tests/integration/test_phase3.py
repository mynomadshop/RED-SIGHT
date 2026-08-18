"""
RedSight - High-Performance Local AI Intelligence Platform
Phase 3 Integration Tests

Tests the full Skills & Tools pipeline:
- Skill manifests and registration
- Semantic skill discovery
- Tool contracts and execution
- Permission system
- Sandbox execution
- Audit trail
- Agent orchestrator
- Test runner
"""

import asyncio
import tempfile
import time
from pathlib import Path

import pytest

from app.skills.manifest import SkillManifest
from app.skills.discovery import SemanticSkillDiscovery
from app.skills.registry import SkillRegistry
from app.skills.sandbox import SkillSandbox, ExecutionResult
from app.tools.contract import ToolContract
from app.tools.builtin import (
    ToolRegistry,
    _handle_read_file,
    _handle_write_file,
    _handle_list_directory,
    _handle_search_files,
    _handle_run_command,
    _handle_get_file_info,
    _handle_search_text,
    _handle_read_json,
    _handle_write_json,
    _handle_delete_file,
    _handle_copy_file,
    _handle_move_file,
    _handle_get_env,
    _handle_list_skills,
    _handle_list_tools,
)
from app.security.permissions import PermissionPolicy, PermissionChecker
from app.security.audit import AuditLogger
from app.orchestration.agent import AgentOrchestrator
from app.tools.test_runner import TestRunner, TestSuite


# ─── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def temp_dir(tmp_path):
    """Provide a temporary directory."""
    return str(tmp_path)


@pytest.fixture
def sample_manifest():
    """Create a sample skill manifest for testing."""
    return SkillManifest(
        skill_id="test_read_file",
        name="Read File",
        description="Read and parse text files from the filesystem",
        version="1.0.0",
        trigger_prompts=["read this file", "what's in", "show me the contents"],
        supported_intents=["file_read", "text_parse"],
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to read"},
            },
            "required": ["path"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "lines": {"type": "integer"},
            },
        },
        entry_point="app.skills.test_read_file",
        timeout_seconds=30,
        allowed_tools=["read_only"],
        filesystem_scopes=["/home", "/tmp"],
    )


@pytest.fixture
def sample_tool_contract():
    """Create a sample tool contract for testing."""
    return ToolContract(
        name="test_tool",
        description="A test tool for validation",
        schema={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Input text"},
            },
            "required": ["text"],
        },
        permissions=["read_only"],
        timeout_seconds=30,
    )


# ─── Skill Manifest Tests ─────────────────────────────────────────

class TestSkillManifest:
    """Test skill manifest creation and validation."""

    def test_create_manifest(self):
        """Test creating a skill manifest."""
        manifest = SkillManifest(
            skill_id="test_1",
            name="Test Skill",
            description="A test skill",
        )
        assert manifest.skill_id == "test_1"
        assert manifest.name == "Test Skill"
        assert manifest.version == "1.0.0"

    def test_manifest_to_dict(self):
        """Test converting manifest to dictionary."""
        manifest = SkillManifest(
            skill_id="test_1",
            name="Test Skill",
            description="A test skill",
        )
        d = manifest.to_dict()
        assert d["skill_id"] == "test_1"
        assert d["name"] == "Test Skill"
        assert d["description"] == "A test skill"

    def test_manifest_from_dict(self):
        """Test creating manifest from dictionary."""
        data = {
            "skill_id": "test_1",
            "name": "Test Skill",
            "description": "A test skill",
            "version": "2.0.0",
        }
        manifest = SkillManifest.from_dict(data)
        assert manifest.skill_id == "test_1"
        assert manifest.version == "2.0.0"

    def test_manifest_validation_valid(self):
        """Test manifest validation with valid data."""
        manifest = SkillManifest(
            skill_id="test_1",
            name="Test Skill",
            description="A test skill",
            entry_point="app.skills.test",
        )
        is_valid, errors = manifest.validate()
        assert is_valid is True
        assert len(errors) == 0

    def test_manifest_validation_invalid(self):
        """Test manifest validation with missing required fields."""
        manifest = SkillManifest(
            skill_id="",
            name="",
            description="",
            entry_point="",
        )
        is_valid, errors = manifest.validate()
        assert is_valid is False
        assert len(errors) > 0

    def test_manifest_save_load(self, temp_dir):
        """Test saving and loading manifest to/from file."""
        manifest = SkillManifest(
            skill_id="test_1",
            name="Test Skill",
            description="A test skill",
            entry_point="app.skills.test",
        )
        path = f"{temp_dir}/manifest.json"
        manifest.to_file(path)

        loaded = SkillManifest.from_file(path)
        assert loaded.skill_id == manifest.skill_id
        assert loaded.name == manifest.name


# ─── Semantic Skill Discovery Tests ────────────────────────────────

class TestSemanticSkillDiscovery:
    """Test semantic skill discovery."""

    def test_register_skill(self, sample_manifest):
        """Test registering a skill for discovery."""
        discovery = SemanticSkillDiscovery()
        discovery.register_skill(sample_manifest)
        assert discovery.get_skill("test_read_file") is not None

    def test_unregister_skill(self, sample_manifest):
        """Test unregistering a skill."""
        discovery = SemanticSkillDiscovery()
        discovery.register_skill(sample_manifest)
        discovery.unregister_skill("test_read_file")
        assert discovery.get_skill("test_read_file") is None

    def test_keyword_search(self, sample_manifest):
        """Test keyword-based skill search."""
        discovery = SemanticSkillDiscovery()
        discovery.register_skill(sample_manifest)
        results = discovery.search("read file", limit=5)
        assert len(results) > 0
        skill, score = results[0]
        assert skill.skill_id == "test_read_file"
        assert score > 0

    def test_search_no_results(self):
        """Test search with no matching skills."""
        discovery = SemanticSkillDiscovery()
        results = discovery.search("nonexistent skill xyz", limit=5)
        assert len(results) == 0

    def test_list_all_skills(self, sample_manifest):
        """Test listing all registered skills."""
        discovery = SemanticSkillDiscovery()
        discovery.register_skill(sample_manifest)
        skills = discovery.list_all()
        assert len(skills) == 1
        assert skills[0].skill_id == "test_read_file"

    def test_get_stats(self, sample_manifest):
        """Test discovery statistics."""
        discovery = SemanticSkillDiscovery()
        discovery.register_skill(sample_manifest)
        stats = discovery.get_stats()
        assert stats["total_skills"] == 1
        assert "has_embedding_model" in stats


# ─── Skill Registry Tests ──────────────────────────────────────────

class TestSkillRegistry:
    """Test skill registry operations."""

    def test_register(self, sample_manifest):
        """Test registering a skill."""
        registry = SkillRegistry()
        skill_id = asyncio.run(registry.register(sample_manifest))
        assert skill_id == "test_read_file"

    def test_get(self, sample_manifest):
        """Test getting a skill by ID."""
        registry = SkillRegistry()
        asyncio.run(registry.register(sample_manifest))
        skill = asyncio.run(registry.get("test_read_file"))
        assert skill is not None
        assert skill.name == "Read File"

    def test_list_all(self, sample_manifest):
        """Test listing all skills."""
        registry = SkillRegistry()
        asyncio.run(registry.register(sample_manifest))
        skills = asyncio.run(registry.list_all())
        assert len(skills) == 1

    def test_search(self, sample_manifest):
        """Test searching skills."""
        registry = SkillRegistry()
        asyncio.run(registry.register(sample_manifest))
        results = asyncio.run(registry.search("read file", limit=5))
        assert len(results) > 0

    def test_unregister(self, sample_manifest):
        """Test unregistering a skill."""
        registry = SkillRegistry()
        asyncio.run(registry.register(sample_manifest))
        result = asyncio.run(registry.unregister("test_read_file"))
        assert result is True
        skill = asyncio.run(registry.get("test_read_file"))
        assert skill is None


# ─── Tool Contract Tests ───────────────────────────────────────────

class TestToolContract:
    """Test tool contract validation."""

    def test_create_contract(self, sample_tool_contract):
        """Test creating a tool contract."""
        assert sample_tool_contract.name == "test_tool"
        assert "read_only" in sample_tool_contract.permissions

    def test_validate_params_valid(self, sample_tool_contract):
        """Test parameter validation with valid params."""
        is_valid, error = sample_tool_contract.validate_params({"text": "hello"})
        assert is_valid is True
        assert error is None

    def test_validate_params_missing_required(self, sample_tool_contract):
        """Test parameter validation with missing required params."""
        is_valid, error = sample_tool_contract.validate_params({})
        assert is_valid is False
        assert error is not None

    def test_validate_params_wrong_type(self, sample_tool_contract):
        """Test parameter validation with wrong type."""
        is_valid, error = sample_tool_contract.validate_params({"text": 123})
        assert is_valid is False
        assert error is not None

    def test_contract_to_dict(self, sample_tool_contract):
        """Test converting contract to dictionary."""
        d = sample_tool_contract.to_dict()
        assert d["name"] == "test_tool"
        assert d["timeout_seconds"] == 30


# ─── Tool Registry Tests ───────────────────────────────────────────

class TestToolRegistry:
    """Test tool registry operations."""

    def test_register_tool(self, sample_tool_contract):
        """Test registering a tool."""
        registry = ToolRegistry()
        registry.register(sample_tool_contract)
        tool = registry.get("test_tool")
        assert tool is not None

    def test_list_tools(self, sample_tool_contract):
        """Test listing all tools."""
        registry = ToolRegistry()
        registry.register(sample_tool_contract)
        tools = registry.list_all()
        assert len(tools) == 1

    def test_list_tool_names(self, sample_tool_contract):
        """Test listing tool names."""
        registry = ToolRegistry()
        registry.register(sample_tool_contract)
        names = registry.list_names()
        assert "test_tool" in names

    def test_check_permission(self, sample_tool_contract):
        """Test permission checking."""
        registry = ToolRegistry()
        registry.register(sample_tool_contract)
        assert registry.check_permission("test_tool", ["read_only"]) is True
        assert registry.check_permission("test_tool", ["destructive"]) is False

    def test_execute_valid(self, sample_tool_contract):
        """Test executing a tool with valid params."""
        registry = ToolRegistry()

        def _test_handler(params, contract):
            return {"text": params.get("text"), "success": True}

        registry.register(sample_tool_contract, _test_handler)
        result = asyncio.run(
            registry.execute("test_tool", {"text": "hello"}, permissions=["read_only"])
        )
        assert result["success"] is True
        assert result["text"] == "hello"

    def test_execute_invalid_params(self, sample_tool_contract):
        """Test executing a tool with invalid params."""
        registry = ToolRegistry()
        registry.register(sample_tool_contract)
        result = asyncio.run(
            registry.execute("test_tool", {}, permissions=["read_only"])
        )
        assert result["success"] is False
        assert "error" in result

    def test_execute_not_found(self):
        """Test executing a non-existent tool."""
        registry = ToolRegistry()
        result = asyncio.run(
            registry.execute("nonexistent", {}, permissions=["read_only"])
        )
        assert result["success"] is False


# ─── Built-in Tool Handler Tests ───────────────────────────────────

class TestBuiltInTools:
    """Test built-in tool handlers."""

    def test_handle_read_file(self, temp_dir):
        """Test reading a file."""
        # Create a test file
        test_file = f"{temp_dir}/test.txt"
        Path(test_file).write_text("Hello, World!")

        result = _handle_read_file({"path": test_file}, None)
        assert result["success"] is True
        assert "Hello, World" in result["content"]
        assert result["lines"] > 0

    def test_handle_read_file_not_found(self, temp_dir):
        """Test reading a non-existent file."""
        result = _handle_read_file({"path": f"{temp_dir}/nonexistent.txt"}, None)
        assert result["success"] is False
        assert "error" in result

    def test_handle_write_file(self, temp_dir):
        """Test writing a file."""
        test_file = f"{temp_dir}/output.txt"
        result = _handle_write_file({
            "path": test_file,
            "content": "Test content",
        }, None)
        assert result["success"] is True
        assert Path(test_file).exists()
        assert Path(test_file).read_text() == "Test content"

    def test_handle_list_directory(self, temp_dir):
        """Test listing a directory."""
        # Create some test files
        Path(f"{temp_dir}/file1.txt").write_text("1")
        Path(f"{temp_dir}/file2.txt").write_text("2")

        result = _handle_list_directory({"path": temp_dir}, None)
        assert result["success"] is True
        assert result["count"] >= 2

    def test_handle_search_files(self, temp_dir):
        """Test searching for files by pattern."""
        Path(f"{temp_dir}/test.py").write_text("print('hello')")
        Path(f"{temp_dir}/test.txt").write_text("hello")

        result = _handle_search_files({"pattern": "*.py", "path": temp_dir}, None)
        assert result["success"] is True
        assert result["count"] >= 1

    def test_handle_run_command(self):
        """Test running a shell command."""
        # Use python -c which works reliably on Windows
        result = _handle_run_command({"command": "python -c \"print('hello')\""}, None)
        assert result["success"] is True
        assert "hello" in result.get("stdout", "")

    def test_handle_get_file_info(self, temp_dir):
        """Test getting file metadata."""
        test_file = f"{temp_dir}/info.txt"
        Path(test_file).write_text("test")

        result = _handle_get_file_info({"path": test_file}, None)
        assert result["success"] is True
        assert result["size_bytes"] == 4
        assert result["is_file"] is True

    def test_handle_search_text(self, temp_dir):
        """Test searching for text in files."""
        test_file = f"{temp_dir}/search.txt"
        Path(test_file).write_text("This is a test file\nWith multiple lines")

        result = _handle_search_text({"pattern": "test", "path": temp_dir}, None)
        assert result["success"] is True
        assert result["count"] >= 1

    def test_handle_read_json(self, temp_dir):
        """Test reading a JSON file."""
        json_file = f"{temp_dir}/data.json"
        Path(json_file).write_text('{"key": "value", "num": 42}')

        result = _handle_read_json({"path": json_file}, None)
        assert result["success"] is True
        assert result["data"]["key"] == "value"
        assert result["data"]["num"] == 42

    def test_handle_write_json(self, temp_dir):
        """Test writing a JSON file."""
        json_file = f"{temp_dir}/output.json"
        result = _handle_write_json({
            "path": json_file,
            "data": {"key": "value", "list": [1, 2, 3]},
        }, None)
        assert result["success"] is True

    def test_handle_copy_file(self, temp_dir):
        """Test copying a file."""
        src = f"{temp_dir}/source.txt"
        dst = f"{temp_dir}/dest.txt"
        Path(src).write_text("copy me")

        result = _handle_copy_file({"source": src, "destination": dst}, None)
        assert result["success"] is True
        assert Path(dst).read_text() == "copy me"

    def test_handle_move_file(self, temp_dir):
        """Test moving a file."""
        src = f"{temp_dir}/move_src.txt"
        dst = f"{temp_dir}/move_dst.txt"
        Path(src).write_text("move me")

        result = _handle_move_file({"source": src, "destination": dst}, None)
        assert result["success"] is True
        assert Path(dst).exists()
        assert not Path(src).exists()

    def test_handle_delete_file(self, temp_dir):
        """Test deleting a file."""
        test_file = f"{temp_dir}/delete_me.txt"
        Path(test_file).write_text("delete me")

        result = _handle_delete_file({
            "path": test_file,
            "_confirmed": True,
        }, None)
        assert result["success"] is True
        assert not Path(test_file).exists()

    def test_handle_delete_file_not_confirmed(self, temp_dir):
        """Test deleting a file without confirmation."""
        test_file = f"{temp_dir}/not_deleted.txt"
        Path(test_file).write_text("keep me")

        # Use a contract that requires confirmation (destructive)
        from app.tools.contract import ToolContract
        destructive_contract = ToolContract(
            name="delete_file",
            description="Delete a file",
            schema={"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            permissions=["destructive"],
            requires_confirmation=True,
        )
        result = _handle_delete_file({"path": test_file, "_confirmed": False}, destructive_contract)
        assert result["success"] is False
        assert Path(test_file).exists()  # File should still exist

    def test_handle_get_env(self):
        """Test getting environment variables."""
        result = _handle_get_env({}, None)
        assert result["success"] is True
        assert "env" in result

    def test_handle_get_env_specific(self):
        """Test getting a specific environment variable."""
        result = _handle_get_env({"name": "PATH"}, None)
        assert result["success"] is True
        assert "name" in result

    def test_handle_list_skills_no_registry(self):
        """Test listing skills when registry is not initialized."""
        result = _handle_list_skills({}, None)
        assert result["success"] is False

    def test_handle_list_tools_no_registry(self):
        """Test listing tools when registry is not initialized."""
        result = _handle_list_tools({}, None)
        assert result["success"] is False


# ─── Permission System Tests ───────────────────────────────────────

class TestPermissionSystem:
    """Test permission system."""

    def test_add_role(self):
        """Test adding a role."""
        policy = PermissionPolicy()
        policy.add_role("test_role", ["read_only", "read_write"])
        assert policy.has_permission("test_role", "read_only")
        assert policy.has_permission("test_role", "read_write")
        assert not policy.has_permission("test_role", "destructive")

    def test_file_read_allowed(self):
        """Test file read permission checks."""
        policy = PermissionPolicy()
        assert policy.is_file_read_allowed("/home/user/file.txt")
        assert not policy.is_file_read_allowed("/home/user/.env")
        assert not policy.is_file_read_allowed("/home/user/secrets/key.txt")

    def test_file_write_allowed(self):
        """Test file write permission checks."""
        policy = PermissionPolicy()
        policy.set_file_write_roots(["/home/user/output"])
        assert policy.is_file_write_allowed("/home/user/output/file.txt")
        assert not policy.is_file_write_allowed("/home/user/protected/file.txt")

    def test_command_allowed(self):
        """Test command allowlist."""
        policy = PermissionPolicy()
        assert policy.is_command_allowed("python script.py")
        assert policy.is_command_allowed("git status")
        assert not policy.is_command_allowed("rm -rf /")

    def test_network_allowed(self):
        """Test network permission checks."""
        policy = PermissionPolicy()
        assert policy.is_network_allowed("127.0.0.1")
        assert policy.is_network_allowed("localhost")

    def test_network_blocked(self):
        """Test blocking outbound network."""
        policy = PermissionPolicy()
        policy.set_block_outbound(True)
        assert not policy.is_network_allowed("127.0.0.1")

    def test_destructive_confirmation(self):
        """Test destructive action confirmation."""
        policy = PermissionPolicy()
        assert policy.requires_confirmation("delete")
        assert policy.requires_confirmation("overwrite")
        assert not policy.requires_confirmation("read")

    def test_permission_checker_check_tool(self):
        """Test permission checker for tools."""
        policy = PermissionPolicy()
        policy.add_role("user", ["read_only"])
        checker = PermissionChecker(policy=policy)

        result = asyncio.run(checker.check_tool_permission(
            role="user",
            tool_name="read_file",
            tool_permissions=["read_only"],
            params={"path": "/home/user/file.txt"},
        ))
        assert result["allowed"] is True

    def test_permission_checker_denied(self):
        """Test permission checker denying access."""
        policy = PermissionPolicy()
        policy.add_role("user", ["read_only"])
        checker = PermissionChecker(policy=policy)

        result = asyncio.run(checker.check_tool_permission(
            role="user",
            tool_name="delete_file",
            tool_permissions=["destructive"],
            params={"path": "/home/user/file.txt"},
        ))
        assert result["allowed"] is False

    def test_permission_checker_confirmation_required(self):
        """Test permission checker requiring confirmation."""
        policy = PermissionPolicy()
        policy.add_role("admin", ["read_only", "destructive"])
        checker = PermissionChecker(policy=policy)

        result = asyncio.run(checker.check_tool_permission(
            role="admin",
            tool_name="delete_file",
            tool_permissions=["destructive"],
            params={"path": "/home/user/file.txt"},
        ))
        assert result["allowed"] is False
        assert "requires_confirmation" in result

    def test_permission_checker_confirmation_passed(self):
        """Test permission checker with confirmation."""
        policy = PermissionPolicy()
        policy.add_role("admin", ["read_only", "destructive"])
        checker = PermissionChecker(policy=policy)

        result = asyncio.run(checker.check_tool_permission(
            role="admin",
            tool_name="delete_file",
            tool_permissions=["destructive"],
            params={"path": "/home/user/file.txt", "_confirmed": True},
        ))
        assert result["allowed"] is True


# ─── Audit Logger Tests ────────────────────────────────────────────

class TestAuditLogger:
    """Test audit logging."""

    def test_record_event(self, temp_dir):
        """Test recording an audit event."""
        from app.core.interfaces import AuditEvent, AuditAction
        logger = AuditLogger(log_path=f"{temp_dir}/audit.log")

        event = AuditEvent(
            event_id="test_1",
            action=AuditAction.TOOL_CALL,
            timestamp=time.time(),
            actor="test_user",
            details={"tool": "read_file", "path": "/test.txt"},
        )
        asyncio.run(logger.record(event))
        assert asyncio.run(logger.get_event_count()) == 1

    def test_query_events(self, temp_dir):
        """Test querying audit events."""
        from app.core.interfaces import AuditEvent, AuditAction
        logger = AuditLogger(log_path=f"{temp_dir}/audit.log")

        # Record multiple events
        for i in range(5):
            event = AuditEvent(
                event_id=f"test_{i}",
                action=AuditAction.TOOL_CALL,
                timestamp=time.time(),
                actor="test_user",
                details={"tool": "read_file"},
            )
            asyncio.run(logger.record(event))

        events = asyncio.run(logger.query(actor="test_user", limit=10))
        assert len(events) == 5

    def test_query_with_action_filter(self, temp_dir):
        """Test querying events with action filter."""
        from app.core.interfaces import AuditEvent, AuditAction
        logger = AuditLogger(log_path=f"{temp_dir}/audit.log")

        # Record different action types
        for i in range(3):
            event = AuditEvent(
                event_id=f"tool_{i}",
                action=AuditAction.TOOL_CALL,
                timestamp=time.time(),
                actor="user",
                details={},
            )
            asyncio.run(logger.record(event))

        for i in range(2):
            event = AuditEvent(
                event_id=f"skill_{i}",
                action=AuditAction.SKILL_EXECUTION,
                timestamp=time.time(),
                actor="user",
                details={},
            )
            asyncio.run(logger.record(event))

        tool_events = asyncio.run(logger.query(action=AuditAction.TOOL_CALL))
        skill_events = asyncio.run(logger.query(action=AuditAction.SKILL_EXECUTION))
        assert len(tool_events) == 3
        assert len(skill_events) == 2

    def test_export_json(self, temp_dir):
        """Test exporting audit log as JSON."""
        from app.core.interfaces import AuditEvent, AuditAction
        logger = AuditLogger(log_path=f"{temp_dir}/audit.log")

        event = AuditEvent(
            event_id="test_1",
            action=AuditAction.TOOL_CALL,
            timestamp=time.time(),
            actor="user",
            details={"tool": "read_file"},
        )
        asyncio.run(logger.record(event))

        json_output = asyncio.run(logger.export(format="json"))
        assert "test_1" in json_output

    def test_tool_stats(self, temp_dir):
        """Test tool call statistics."""
        from app.core.interfaces import AuditEvent, AuditAction
        logger = AuditLogger(log_path=f"{temp_dir}/audit.log")

        for i in range(3):
            event = AuditEvent(
                event_id=f"tool_{i}",
                action=AuditAction.TOOL_CALL,
                timestamp=time.time(),
                actor="user",
                details={"tool": "read_file"},
                result="success",
            )
            asyncio.run(logger.record(event))

        stats = asyncio.run(logger.get_tool_stats())
        assert stats["total_calls"] == 3
        assert stats["successful"] == 3
        assert stats["by_tool"]["read_file"] == 3


# ─── Sandbox Execution Tests ───────────────────────────────────────

class TestSkillSandbox:
    """Test sandbox execution."""

    def test_execute_success(self):
        """Test successful sandbox execution."""
        sandbox = SkillSandbox()
        result = asyncio.run(
            sandbox.execute(
                entry_point="cmd:echo hello",
                inputs={},
                actor="test_user",
            )
        )
        assert result.success is True

    def test_execute_timeout(self):
        """Test sandbox execution timeout."""
        sandbox = SkillSandbox(default_timeout=1)
        result = asyncio.run(
            sandbox.execute(
                entry_point="cmd:sleep 5",
                inputs={},
                timeout=1,
                actor="test_user",
            )
        )
        assert result.success is False
        assert "timeout" in result.error.lower() or "timed out" in result.error.lower()

    def test_execute_invalid_command(self):
        """Test sandbox with invalid command."""
        sandbox = SkillSandbox()
        result = asyncio.run(
            sandbox.execute(
                entry_point="cmd:nonexistent_command_xyz",
                inputs={},
                actor="test_user",
            )
        )
        assert result.success is False

    def test_validate_permissions(self):
        """Test permission validation."""
        sandbox = SkillSandbox()
        result = asyncio.run(
            sandbox.validate_permissions(
                required_permissions=["read_only", "read_write"],
                granted_permissions=["read_only", "read_write"],
            )
        )
        assert result is True

        result = asyncio.run(
            sandbox.validate_permissions(
                required_permissions=["destructive"],
                granted_permissions=["read_only"],
            )
        )
        assert result is False

    def test_check_resource_limits(self):
        """Test resource limit checks."""
        sandbox = SkillSandbox(max_memory_mb=1024)
        assert asyncio.run(sandbox.check_resource_limits(512, 50)) is True
        assert asyncio.run(sandbox.check_resource_limits(2048, 50)) is False


# ─── Agent Orchestrator Tests ──────────────────────────────────────

class TestAgentOrchestrator:
    """Test agent orchestrator."""

    def test_orchestrate_with_tool(self, sample_tool_contract):
        """Test orchestrating a tool execution."""
        registry = ToolRegistry()

        def _test_handler(params, contract):
            return {"text": params.get("query", params.get("text", "")), "success": True}

        registry.register(sample_tool_contract, _test_handler)

        orchestrator = AgentOrchestrator(tool_registry=registry)
        result = asyncio.run(
            orchestrator.orchestrate("execute test tool", role="user")
        )
        assert result.success is True
        assert result.selected_tool is not None
        assert result.selected_tool == "test_tool"
        assert result.output is not None

    def test_orchestrate_no_match(self):
        """Test orchestrating with no matching skill/tool."""
        orchestrator = AgentOrchestrator()
        result = asyncio.run(
            orchestrator.orchestrate("random query with no tools", role="user")
        )
        assert result.error is not None

    def test_list_available_tools(self, sample_tool_contract):
        """Test listing available tools."""
        registry = ToolRegistry()
        registry.register(sample_tool_contract)

        orchestrator = AgentOrchestrator(tool_registry=registry)
        tools = asyncio.run(orchestrator.list_available_tools())
        assert len(tools) == 1
        assert tools[0]["name"] == "test_tool"

    def test_list_available_skills(self, sample_manifest):
        """Test listing available skills."""
        discovery = SemanticSkillDiscovery()
        discovery.register_skill(sample_manifest)

        orchestrator = AgentOrchestrator(skill_discovery=discovery)
        skills = asyncio.run(orchestrator.list_available_skills())
        assert len(skills) == 1
        assert skills[0]["skill_id"] == "test_read_file"

    def test_get_stats(self):
        """Test orchestrator statistics."""
        orchestrator = AgentOrchestrator()
        stats = orchestrator.get_stats()
        assert stats["has_discovery"] is False
        assert stats["has_tool_registry"] is False

    def test_set_role(self):
        """Test setting execution role."""
        orchestrator = AgentOrchestrator()
        orchestrator.set_role("admin")
        assert orchestrator._role == "admin"


# ─── Test Runner Tests ─────────────────────────────────────────────

class TestRunnerClass:
    """Test the test runner."""

    def test_validate_tool_success(self, sample_tool_contract):
        """Test validating a tool with success."""
        registry = ToolRegistry()

        def _test_handler(params, contract):
            return {"text": params.get("text", ""), "success": True}

        registry.register(sample_tool_contract, _test_handler)
        result = asyncio.run(
            registry.execute("test_tool", {"text": "hello"}, permissions=["read_only"])
        )
        assert result["success"] is True

    def test_validate_tool_missing_params(self, sample_tool_contract):
        """Test validating a tool with missing params."""
        registry = ToolRegistry()
        registry.register(sample_tool_contract)
        result = asyncio.run(
            registry.execute("test_tool", {}, permissions=["read_only"])
        )
        assert result["success"] is False
        assert "error" in result

    def test_register_suite(self):
        """Test registering a test suite."""
        from app.tools.test_runner import TestRunner
        runner = TestRunner()
        runner.register_suite("unit_tests", ["tests/unit/"])
        assert "unit_tests" in runner.get_suite_names()

    def test_save_regression_result(self):
        """Test saving regression results."""
        from app.tools.test_runner import TestRunner, TestResult
        runner = TestRunner()
        runner.save_regression_result("test_suite", [
            TestResult(name="test_1", passed=True),
            TestResult(name="test_2", passed=False),
        ])
        comparison = runner.compare_regression("test_suite")
        assert comparison["baseline_tests"] == 2
        assert comparison["baseline_passed"] == 1


# ─── Integration Tests ─────────────────────────────────────────────

class TestFullPipeline:
    """End-to-end integration tests."""

    def test_full_tool_lifecycle(self, temp_dir):
        """Test the full tool lifecycle: register, execute, audit."""
        # Create audit logger
        from app.security.audit import AuditLogger
        from app.security.permissions import PermissionPolicy, PermissionChecker
        from app.tools.builtin import ToolRegistry, ToolContract

        audit = AuditLogger(log_path=f"{temp_dir}/audit.log")
        policy = PermissionPolicy()
        policy.add_role("user", ["read_only"])
        checker = PermissionChecker(policy=policy, audit_logger=audit)
        registry = ToolRegistry(policy=policy, audit_logger=audit)

        # Register a tool
        contract = ToolContract(
            name="read_file",
            description="Read a file",
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            permissions=["read_only"],
            timeout_seconds=30,
        )
        registry.register(contract, _handle_read_file)

        # Create test file
        test_file = f"{temp_dir}/test.txt"
        Path(test_file).write_text("Integration test content")

        # Execute tool
        result = asyncio.run(
            registry.execute("read_file", {"path": test_file}, permissions=["read_only"], actor="user")
        )
        assert result["success"] is True
        assert "Integration test" in result.get("content", "")

        # Check audit log
        events = asyncio.run(audit.query(action="tool_call"))
        assert len(events) >= 1

    def test_skill_discovery_and_execution(self, temp_dir):
        """Test skill discovery and execution pipeline."""
        from app.security.audit import AuditLogger
        from app.skills.discovery import SemanticSkillDiscovery
        from app.skills.sandbox import SkillSandbox
        from app.orchestration.agent import AgentOrchestrator

        audit = AuditLogger(log_path=f"{temp_dir}/audit.log")
        discovery = SemanticSkillDiscovery()

        # Register a skill
        manifest = SkillManifest(
            skill_id="cmd_runner",
            name="Command Runner",
            description="Execute shell commands",
            trigger_prompts=["run command", "execute", "run this"],
            entry_point="cmd:echo hello",
            allowed_tools=["read_only"],
        )
        discovery.register_skill(manifest)

        # Create sandbox and orchestrator
        sandbox = SkillSandbox(audit_logger=audit)
        orchestrator = AgentOrchestrator(
            skill_discovery=discovery,
            sandbox=sandbox,
            audit_logger=audit,
        )

        # Orchestrate
        result = asyncio.run(
            orchestrator.orchestrate("run command hello", role="user")
        )
        assert result.selected_skill == "cmd_runner"

    def test_permission_enforcement(self, temp_dir):
        """Test that permissions are enforced end-to-end."""
        from app.security.audit import AuditLogger
        from app.security.permissions import PermissionPolicy, PermissionChecker
        from app.tools.builtin import ToolRegistry, ToolContract

        audit = AuditLogger(log_path=f"{temp_dir}/audit.log")
        policy = PermissionPolicy()
        policy.add_role("guest", ["read_only"])
        policy.add_role("admin", ["read_only", "read_write", "destructive"])
        checker = PermissionChecker(policy=policy, audit_logger=audit)
        registry = ToolRegistry(policy=policy, audit_logger=audit)

        # Register a destructive tool
        contract = ToolContract(
            name="delete_file",
            description="Delete a file",
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "_confirmed": {"type": "boolean"},
                },
                "required": ["path", "_confirmed"],
            },
            permissions=["destructive"],
            is_destructive=True,
            timeout_seconds=30,
        )
        registry.register(contract, _handle_delete_file)

        # Create test file
        test_file = f"{temp_dir}/delete_me.txt"
        Path(test_file).write_text("delete me")

        # Guest should be denied
        result = asyncio.run(
            registry.execute("delete_file", {
                "path": test_file,
                "_confirmed": True,
            }, permissions=["guest"], actor="guest")
        )
        assert result["success"] is False

        # Admin should succeed (admin role has destructive permission)
        result = asyncio.run(
            registry.execute("delete_file", {
                "path": test_file,
                "_confirmed": True,
            }, permissions=["destructive"], actor="admin")
        )
        assert result["success"] is True
        assert not Path(test_file).exists()

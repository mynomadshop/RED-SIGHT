"""
RedSight - High-Performance Local AI Intelligence Platform
Unit Tests

Basic tests for core functionality.
"""

import pytest
import asyncio


class TestConfig:
    """Tests for configuration."""
    
    def test_settings_defaults(self):
        from app.config.settings import Settings
        settings = Settings()
        assert settings.platform.mode == "local_preferred"
        assert settings.lmstudio.base_url == "http://host.docker.internal:1234/v1"
        assert settings.routing.vram_headroom_gb_per_gpu == 3.0
    
    def test_settings_mode_validation(self):
        from app.config.settings import Settings
        with pytest.raises(ValueError):
            Settings(platform={"mode": "invalid_mode"})


class TestInterfaces:
    """Tests for core interfaces."""
    
    def test_trust_levels(self):
        from app.core.interfaces import TrustLevel
        assert TrustLevel.RAW == 0
        assert TrustLevel.PARSED == 1
        assert TrustLevel.VALIDATED == 2
        assert TrustLevel.PROMOTED == 3
        assert TrustLevel.GOLDEN == 4
    
    def test_job_status(self):
        from app.core.interfaces import JobStatus
        statuses = [s.value for s in JobStatus]
        assert "pending" in statuses
        assert "running" in statuses
        assert "completed" in statuses
        assert "failed" in statuses


class TestMemory:
    """Tests for memory stores."""
    
    def test_working_memory(self):
        from app.memory.working import WorkingMemory
        wm = WorkingMemory()
        
        async def test():
            await wm.store("key1", "value1")
            result = await wm.get("key1")
            assert result == "value1"
            await wm.delete("key1")
            result = await wm.get("key1")
            assert result is None
        
        asyncio.run(test())
    
    def test_episodic_memory(self):
        from app.memory.episodic import EpisodicMemory
        em = EpisodicMemory()
        
        async def test():
            mid = await em.store("task1", "decision1", "outcome1")
            assert mid.startswith("ep_task1_")
            count = await em.count()
            assert count == 1
        
        asyncio.run(test())
    
    def test_semantic_memory(self):
        from app.memory.semantic import SemanticMemory
        sm = SemanticMemory()
        
        async def test():
            mid = await sm.store("fact1", "source1")
            assert mid.startswith("sm_")
            count = await sm.count()
            assert count == 1
        
        asyncio.run(test())


class TestSkillManifest:
    """Tests for skill manifests."""
    
    def test_valid_manifest(self):
        from app.skills.manifest import SkillManifest
        manifest = SkillManifest(
            skill_id="test_skill",
            name="Test Skill",
            description="A test skill",
            entry_point="app.skills.test_skill.run",
        )
        is_valid, errors = manifest.validate()
        assert is_valid
        assert len(errors) == 0
    
    def test_invalid_manifest(self):
        from app.skills.manifest import SkillManifest
        manifest = SkillManifest(
            skill_id="",  # Empty ID
            name="",  # Empty name
            description="",  # Empty description
            entry_point="",  # Empty entry point
        )
        is_valid, errors = manifest.validate()
        assert not is_valid
        assert len(errors) > 0


class TestToolContract:
    """Tests for tool contracts."""
    
    def test_tool_validation(self):
        from app.tools.contract import ToolContract
        contract = ToolContract(
            name="test_tool",
            description="A test tool",
            schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "count": {"type": "integer"},
                },
                "required": ["name"],
            },
        )
        
        # Valid params
        is_valid, error = contract.validate_params({"name": "test"})
        assert is_valid
        assert error is None
        
        # Missing required
        is_valid, error = contract.validate_params({})
        assert not is_valid
        assert "Missing required parameter" in error
        
        # Wrong type
        is_valid, error = contract.validate_params({"name": "test", "count": "not_an_int"})
        assert not is_valid


class TestSecurityPolicy:
    """Tests for security policy."""
    
    def test_file_read_allowed(self):
        from app.security.policy import SecurityPolicy
        policy = SecurityPolicy()
        assert policy.is_file_read_allowed("/home/user/docs/file.txt")
    
    def test_file_read_denied(self):
        from app.security.policy import SecurityPolicy
        policy = SecurityPolicy()
        assert not policy.is_file_read_allowed("/home/user/.env")
    
    def test_command_allowed(self):
        from app.security.policy import SecurityPolicy
        policy = SecurityPolicy()
        assert policy.is_command_allowed("python script.py")
        assert policy.is_command_allowed("ls -la")


class TestStateTransition:
    """Tests for state machine."""
    
    def test_valid_transition(self):
        from app.orchestration.state_machine import TaskStateMachine, TaskState
        sm = TaskStateMachine()
        
        async def test():
            await sm.set_state("task1", TaskState.PENDING)
            await sm.set_state("task1", TaskState.PLANNING)
            state = await sm.get_state("task1")
            assert state == TaskState.PLANNING
        
        asyncio.run(test())
    
    def test_invalid_transition(self):
        from app.orchestration.state_machine import TaskStateMachine, TaskState, InvalidTransition
        sm = TaskStateMachine()
        
        async def test():
            await sm.set_state("task1", TaskState.PENDING)
            with pytest.raises(InvalidTransition):
                await sm.set_state("task1", TaskState.COMPLETE)  # Invalid: PENDING -> COMPLETE
        
        asyncio.run(test())


class TestDocumentParser:
    """Tests for document parser."""
    
    def test_split_text(self):
        from app.ingestion.parser import DocumentParser
        parser = DocumentParser(chunk_size=100, chunk_overlap=10)
        
        text = "A" * 250
        chunks = parser._split_text(text)
        assert len(chunks) >= 2
        assert all(len(c) <= 100 for c in chunks)


class TestBenchmarkManager:
    """Tests for benchmark manager."""
    
    @pytest.fixture
    def temp_dir(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir
    
    def test_record_and_get(self, temp_dir):
        from pathlib import Path
        from app.telemetry.benchmark import BenchmarkManager
        from app.core.interfaces import BenchmarkResult
        
        bm = BenchmarkManager(benchmark_path=str(Path(temp_dir) / "benchmarks"))
        
        result = BenchmarkResult(
            profile_name="test",
            model_id="test_model",
            backend="lmstudio",
            ttft_ms=100.0,
            tokens_per_second=50.0,
            total_latency_ms=1000.0,
            vram_peak_mb=2000.0,
            cpu_percent=30.0,
            success=True,
        )
        
        async def test():
            await bm.record(result)
            results = await bm.get_results(profile_name="test")
            assert len(results) == 1
            assert results[0].tokens_per_second == 50.0
        
        asyncio.run(test())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

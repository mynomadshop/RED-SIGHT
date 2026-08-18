"""
RedSight - High-Performance Local AI Intelligence Platform
Phase 6 Integration Tests — Controlled Learning

Tests for:
- SafetyBoundary (blocking, validation, daily limits)
- LearningEvent lifecycle (ingest, promote, revoke, feedback)
- ControlledLearning engine (batch, query, stats)
- Promotion workflow (request, approve, reject)
- API endpoints (ingest, promote, feedback, query, stats)
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Ensure project root is on path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.learning import (
    ControlledLearning,
    SafetyBoundary,
    LearningEvent,
    PromotionRequest,
    PromotionStatus,
    TrustLevel,
    FeedbackRecord,
)


# ═══════════════════════════════════════════════════════════
# SafetyBoundary Tests
# ═══════════════════════════════════════════════════════════

class TestSafetyBoundary:
    """Tests for safety boundary enforcement."""

    def test_source_blocked(self):
        sb = SafetyBoundary(blocked_sources=["evil-site"])
        assert sb.is_source_blocked("evil-site") is True
        assert sb.is_source_blocked("good-site") is False

    def test_category_blocked(self):
        sb = SafetyBoundary(blocked_categories=["spam"])
        assert sb.is_category_blocked("spam") is True
        assert sb.is_category_blocked("skill") is False

    def test_content_too_long(self):
        sb = SafetyBoundary(max_content_length=10)
        safe, reason = sb.check_safety("x" * 20)
        assert safe is False
        assert "exceeds" in reason

    def test_content_unsafe_pattern(self):
        sb = SafetyBoundary()
        safe, reason = sb.check_safety("this contains malware pattern")
        assert safe is False
        assert "unsafe" in reason

    def test_safe_content(self):
        sb = SafetyBoundary()
        safe, reason = sb.check_safety("This is a normal skill description")
        assert safe is True
        assert reason is None

    def test_can_promote_trust_bound(self):
        sb = SafetyBoundary()
        allowed, result = sb.can_promote(
            source="good", category="skill",
            current_trust=TrustLevel.VALIDATED,
            target_trust=TrustLevel.VALIDATED,
        )
        assert allowed is False
        assert "higher" in result

    def test_can_promote_confirmation_required(self):
        sb = SafetyBoundary()
        allowed, result = sb.can_promote(
            source="good", category="skill",
            current_trust=TrustLevel.VALIDATED,
            target_trust=TrustLevel.PROMOTED,
        )
        assert allowed is True
        assert result == "confirmation_required"

    def test_daily_limit(self):
        sb = SafetyBoundary(max_trust_per_day=2)
        sb.record_promotion()
        sb.record_promotion()
        allowed, result = sb.can_promote(
            source="good", category="skill",
            current_trust=TrustLevel.VALIDATED,
            target_trust=TrustLevel.CONFIRMED,
        )
        assert allowed is False
        assert "limit" in result

    def test_blocked_source_prevents_promotion(self):
        sb = SafetyBoundary(blocked_sources=["bad"])
        allowed, result = sb.can_promote(
            source="bad", category="skill",
            current_trust=TrustLevel.RAW,
            target_trust=TrustLevel.VALIDATED,
        )
        assert allowed is False

    def test_blocked_category_prevents_promotion(self):
        sb = SafetyBoundary(blocked_categories=["malware"])
        allowed, result = sb.can_promote(
            source="good", category="malware",
            current_trust=TrustLevel.RAW,
            target_trust=TrustLevel.VALIDATED,
        )
        assert allowed is False


# ═══════════════════════════════════════════════════════════
# LearningEvent Tests
# ═══════════════════════════════════════════════════════════

class TestLearningEvent:
    """Tests for LearningEvent dataclass."""

    def test_event_creation(self):
        event = LearningEvent(
            event_id="test_001",
            source="manual",
            content_hash="abc123",
            content="Test content",
            trust_level=TrustLevel.RAW,
            category="fact",
        )
        assert event.event_id == "test_001"
        assert event.trust_level == TrustLevel.RAW
        assert event.usage_count == 0
        assert event.feedback_score is None

    def test_event_default_timestamps(self):
        import time
        before = time.time()
        event = LearningEvent(
            event_id="test_002",
            source="manual",
            content_hash="def456",
            content="Test",
            trust_level=TrustLevel.RAW,
            category="general",
        )
        after = time.time()
        assert before <= event.created_at <= after
        assert event.confirmed_at is None
        assert event.revoked_at is None


# ═══════════════════════════════════════════════════════════
# ControlledLearning — Ingestion Tests
# ═══════════════════════════════════════════════════════════

class TestControlledLearningIngestion:
    """Tests for content ingestion into the learning engine."""

    @pytest.fixture
    def engine(self):
        return ControlledLearning()

    async def test_ingest_raw_content(self, engine):
        eid = await engine.ingest(
            content="How to bake a cake",
            source="web",
            category="skill",
            trust_level=TrustLevel.RAW,
        )
        assert eid is not None
        assert eid.startswith("learn_")

    async def test_ingest_blocked_source(self, engine):
        engine = ControlledLearning(
            safety_boundary=SafetyBoundary(blocked_sources=["blocked"])
        )
        eid = await engine.ingest(
            content="Bad content",
            source="blocked",
            category="general",
        )
        assert eid is None

    async def test_ingest_blocked_category(self, engine):
        engine = ControlledLearning(
            safety_boundary=SafetyBoundary(blocked_categories=["spam"])
        )
        eid = await engine.ingest(
            content="Spam content",
            source="web",
            category="spam",
        )
        assert eid is None

    async def test_ingest_unsafe_content(self, engine):
        eid = await engine.ingest(
            content="This contains malware pattern",
            source="web",
            category="general",
        )
        assert eid is None

    async def test_ingest_content_too_long(self, engine):
        engine = ControlledLearning(
            safety_boundary=SafetyBoundary(max_content_length=10)
        )
        eid = await engine.ingest(
            content="x" * 100,
            source="web",
            category="general",
        )
        assert eid is None

    async def test_ingest_batch(self, engine):
        items = [
            {"content": "Item 1", "source": "web", "category": "fact"},
            {"content": "Item 2", "source": "web", "category": "skill"},
            {"content": "Blocked", "source": "blocked", "category": "general"},
        ]
        engine = ControlledLearning(
            safety_boundary=SafetyBoundary(blocked_sources=["blocked"])
        )
        ids = await engine.ingest_batch(items)
        assert len(ids) == 2

    async def test_ingest_duplicate_content(self, engine):
        eid1 = await engine.ingest(
            content="Same content",
            source="web",
            category="general",
        )
        eid2 = await engine.ingest(
            content="Same content",
            source="web",
            category="general",
        )
        # Same content should get same hash but different event IDs
        assert eid1 != eid2

    async def test_ingest_with_context(self, engine):
        eid = await engine.ingest(
            content="Contextual content",
            source="web",
            category="fact",
            context={"url": "https://example.com", "author": "test"},
        )
        event = await engine.get_event(eid)
        assert event["context"]["url"] == "https://example.com"


# ═══════════════════════════════════════════════════════════
# ControlledLearning — Promotion Tests
# ═══════════════════════════════════════════════════════════

class TestControlledLearningPromotion:
    """Tests for content promotion workflow."""

    @pytest.fixture
    def engine(self):
        return ControlledLearning()

    async def test_request_promotion(self, engine):
        eid = await engine.ingest(
            content="Test content",
            source="web",
            category="skill",
        )
        req_id = await engine.request_promotion(
            event_id=eid,
            target_trust=TrustLevel.VALIDATED,
            reason="User marked as useful",
        )
        assert req_id is not None
        assert req_id.startswith("promo_")

    async def test_promotion_auto_approve_no_confirmation(self, engine):
        # VALIDATED doesn't require confirmation by default
        eid = await engine.ingest(
            content="Test content",
            source="web",
            category="skill",
        )
        req_id = await engine.request_promotion(
            event_id=eid,
            target_trust=TrustLevel.VALIDATED,
        )
        req = engine._promotions[req_id]
        assert req.status == PromotionStatus.APPROVED

    async def test_promotion_requires_confirmation(self, engine):
        # PROMOTED requires confirmation
        eid = await engine.ingest(
            content="Test content",
            source="web",
            category="skill",
        )
        req_id = await engine.request_promotion(
            event_id=eid,
            target_trust=TrustLevel.PROMOTED,
        )
        req = engine._promotions[req_id]
        assert req.status == PromotionStatus.PENDING

    async def test_approve_promotion(self, engine):
        # Use PROMOTED which requires confirmation
        eid = await engine.ingest(
            content="Test content",
            source="web",
            category="skill",
        )
        req_id = await engine.request_promotion(
            event_id=eid,
            target_trust=TrustLevel.PROMOTED,
        )
        # Should be PENDING (requires confirmation)
        req = engine._promotions[req_id]
        assert req.status == PromotionStatus.PENDING
        
        success = await engine.approve_promotion(req_id, approved_by="user")
        assert success is True
        event = await engine.get_event(eid)
        assert event["trust_level"] == "PROMOTED"

    async def test_reject_promotion(self, engine):
        # Use PROMOTED which requires confirmation
        eid = await engine.ingest(
            content="Test content",
            source="web",
            category="skill",
        )
        req_id = await engine.request_promotion(
            event_id=eid,
            target_trust=TrustLevel.PROMOTED,
        )
        req = engine._promotions[req_id]
        assert req.status == PromotionStatus.PENDING
        
        success = await engine.reject_promotion(req_id, reason="Not useful")
        assert success is True
        req = engine._promotions[req_id]
        assert req.status == PromotionStatus.REJECTED

    async def test_revoke_promotion(self, engine):
        eid = await engine.ingest(
            content="Test content",
            source="web",
            category="skill",
        )
        # Promote first
        req_id = await engine.request_promotion(
            event_id=eid,
            target_trust=TrustLevel.VALIDATED,
        )
        await engine.approve_promotion(req_id)
        
        # Then revoke
        success = await engine.revoke_promotion(eid)
        assert success is True
        event = await engine.get_event(eid)
        assert event["trust_level"] == "PARSED"  # Dropped one level
        assert event["revoked_at"] is not None

    async def test_cannot_promote_below_current(self, engine):
        eid = await engine.ingest(
            content="Test content",
            source="web",
            category="skill",
            trust_level=TrustLevel.VALIDATED,
        )
        req_id = await engine.request_promotion(
            event_id=eid,
            target_trust=TrustLevel.RAW,
        )
        assert req_id is None

    async def test_promotion_to_procedural_memory(self, engine):
        """Test that PROMOTED trust level promotes to procedural memory."""
        mock_proc = MagicMock()
        engine._procedural_memory = mock_proc
        
        eid = await engine.ingest(
            content="Important skill",
            source="web",
            category="skill",
        )
        req_id = await engine.request_promotion(
            event_id=eid,
            target_trust=TrustLevel.PROMOTED,
        )
        await engine.approve_promotion(req_id)
        
        # Should have called procedural memory store
        assert mock_proc.store.called

    async def test_promotion_to_working_memory(self, engine):
        """Test that VALIDATED/CONFIRMED trust promotes to working memory."""
        mock_working = MagicMock()
        engine._working_memory = mock_working
        
        eid = await engine.ingest(
            content="Important fact",
            source="web",
            category="fact",
        )
        req_id = await engine.request_promotion(
            event_id=eid,
            target_trust=TrustLevel.VALIDATED,
        )
        await engine.approve_promotion(req_id)
        
        assert mock_working.store.called


# ═══════════════════════════════════════════════════════════
# ControlledLearning — Feedback Tests
# ═══════════════════════════════════════════════════════════

class TestControlledLearningFeedback:
    """Tests for feedback submission and tracking."""

    @pytest.fixture
    def engine(self):
        return ControlledLearning()

    async def test_submit_feedback(self, engine):
        eid = await engine.ingest(
            content="Test content",
            source="web",
            category="fact",
        )
        event = await engine.get_event(eid)
        fb_id = await engine.submit_feedback(
            content_hash=event["content_hash"],
            score=0.9,
            category="quality",
            comment="Very useful",
        )
        assert fb_id is not None
        assert fb_id.startswith("fb_")

    async def test_feedback_updates_event(self, engine):
        eid = await engine.ingest(
            content="Test content",
            source="web",
            category="fact",
        )
        event = await engine.get_event(eid)
        await engine.submit_feedback(
            content_hash=event["content_hash"],
            score=0.75,
        )
        updated = await engine.get_event(eid)
        assert updated["feedback_score"] == 0.75
        assert updated["usage_count"] == 1

    async def test_submit_feedback_low_score(self, engine):
        eid = await engine.ingest(
            content="Bad content",
            source="web",
            category="fact",
        )
        event = await engine.get_event(eid)
        await engine.submit_feedback(
            content_hash=event["content_hash"],
            score=0.1,
        )
        updated = await engine.get_event(eid)
        assert updated["feedback_score"] == 0.1


# ═══════════════════════════════════════════════════════════
# ControlledLearning — Query & Analysis Tests
# ═══════════════════════════════════════════════════════════

class TestControlledLearningQuery:
    """Tests for querying and analyzing learned content."""

    @pytest.fixture
    def engine(self):
        return ControlledLearning()

    async def test_query_by_keyword(self, engine):
        await engine.ingest(
            content="How to bake bread",
            source="web",
            category="skill",
        )
        results = await engine.query("bread")
        assert len(results) == 1
        assert "bread" in results[0]["content"]

    async def test_query_filters_by_trust(self, engine):
        await engine.ingest(
            content="RAW content",
            source="web",
            category="general",
            trust_level=TrustLevel.RAW,
        )
        await engine.ingest(
            content="VALIDATED content",
            source="web",
            category="general",
            trust_level=TrustLevel.VALIDATED,
        )
        results = await engine.query("", trust_min=TrustLevel.VALIDATED)
        assert len(results) == 1
        assert results[0]["trust_level"] == "VALIDATED"

    async def test_query_filters_by_category(self, engine):
        await engine.ingest(
            content="Skill content",
            source="web",
            category="skill",
        )
        await engine.ingest(
            content="Fact content",
            source="web",
            category="fact",
        )
        results = await engine.query("", category="skill")
        assert len(results) == 1
        assert results[0]["category"] == "skill"

    async def test_query_revoked_excluded(self, engine):
        eid = await engine.ingest(
            content="Revoked content",
            source="web",
            category="general",
        )
        await engine.revoke_promotion(eid)
        results = await engine.query("Revoked")
        assert len(results) == 0

    async def test_get_promotions(self, engine):
        eid = await engine.ingest(
            content="Test",
            source="web",
            category="general",
        )
        await engine.request_promotion(
            event_id=eid,
            target_trust=TrustLevel.VALIDATED,
        )
        promotions = await engine.get_promotions()
        assert len(promotions) == 1

    async def test_get_promotions_filtered(self, engine):
        eid = await engine.ingest(
            content="Test",
            source="web",
            category="general",
        )
        # Use PROMOTED to require confirmation
        await engine.request_promotion(
            event_id=eid,
            target_trust=TrustLevel.PROMOTED,
        )
        pending = await engine.get_promotions(status=PromotionStatus.PENDING)
        assert len(pending) == 1
        approved = await engine.get_promotions(status=PromotionStatus.APPROVED)
        assert len(approved) == 0

    async def test_get_stats(self, engine):
        await engine.ingest(content="A", source="web", category="skill")
        await engine.ingest(content="B", source="web", category="fact")
        
        stats = await engine.get_stats()
        assert stats["total_events"] == 2
        assert stats["trust_distribution"]["RAW"] == 2
        assert stats["category_distribution"]["skill"] == 1
        assert stats["category_distribution"]["fact"] == 1

    async def test_clear(self, engine):
        await engine.ingest(content="A", source="web", category="general")
        await engine.clear()
        stats = await engine.get_stats()
        assert stats["total_events"] == 0


# ═══════════════════════════════════════════════════════════
# ControlledLearning API Tests
# ═══════════════════════════════════════════════════════════

class TestControlledLearningAPI:
    """Tests for Controlled Learning API endpoints."""

    def _make_app(self, learning_engine):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        
        app = FastAPI()
        from app.api.routes.controlled_learning import router, set_learning_engine
        set_learning_engine(learning_engine)
        app.include_router(router, prefix="/api/v1")
        return app, TestClient(app)

    def test_ingest_endpoint(self):
        engine = ControlledLearning()
        app, client = self._make_app(engine)
        
        resp = client.post("/api/v1/learn/ingest", json={
            "content": "Test content",
            "source": "web",
            "category": "skill",
            "trust_level": "RAW",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "event_id" in data
        assert data["status"] == "ingested"

    def test_ingest_blocked_source(self):
        engine = ControlledLearning(
            safety_boundary=SafetyBoundary(blocked_sources=["blocked"])
        )
        app, client = self._make_app(engine)
        
        resp = client.post("/api/v1/learn/ingest", json={
            "content": "Bad content",
            "source": "blocked",
        })
        assert resp.status_code == 403

    def test_ingest_batch_endpoint(self):
        engine = ControlledLearning()
        app, client = self._make_app(engine)
        
        resp = client.post("/api/v1/learn/ingest-batch", json={
            "items": [
                {"content": "Item 1", "source": "web"},
                {"content": "Item 2", "source": "web"},
            ]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_promote_endpoint(self):
        engine = ControlledLearning()
        app, client = self._make_app(engine)
        
        # Ingest first
        ingest_resp = client.post("/api/v1/learn/ingest", json={
            "content": "Test content",
            "source": "web",
        })
        event_id = ingest_resp.json()["event_id"]
        
        # Then promote
        resp = client.post("/api/v1/learn/promote", json={
            "event_id": event_id,
            "target_trust": "VALIDATED",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "request_id" in data

    def test_approve_promotion_endpoint(self):
        engine = ControlledLearning()
        app, client = self._make_app(engine)
        
        ingest_resp = client.post("/api/v1/learn/ingest", json={
            "content": "Test content",
            "source": "web",
        })
        event_id = ingest_resp.json()["event_id"]
        
        # Use PROMOTED to require confirmation
        promo_resp = client.post("/api/v1/learn/promote", json={
            "event_id": event_id,
            "target_trust": "PROMOTED",
        })
        req_id = promo_resp.json()["request_id"]
        
        approve_resp = client.post(
            f"/api/v1/learn/promotions/{req_id}/approve",
            json={"approved_by": "user"},
        )
        assert approve_resp.status_code == 200
        assert approve_resp.json()["approved"] is True

    def test_reject_promotion_endpoint(self):
        engine = ControlledLearning()
        app, client = self._make_app(engine)
        
        ingest_resp = client.post("/api/v1/learn/ingest", json={
            "content": "Test content",
            "source": "web",
        })
        event_id = ingest_resp.json()["event_id"]
        
        # Use PROMOTED to require confirmation
        promo_resp = client.post("/api/v1/learn/promote", json={
            "event_id": event_id,
            "target_trust": "PROMOTED",
        })
        req_id = promo_resp.json()["request_id"]
        
        reject_resp = client.post(
            f"/api/v1/learn/promotions/{req_id}/reject",
            json={"reason": "Not useful"},
        )
        assert reject_resp.status_code == 200
        assert reject_resp.json()["rejected"] is True

    def test_feedback_endpoint(self):
        engine = ControlledLearning()
        app, client = self._make_app(engine)
        
        ingest_resp = client.post("/api/v1/learn/ingest", json={
            "content": "Test content",
            "source": "web",
        })
        event = ingest_resp.json()
        
        resp = client.post("/api/v1/learn/feedback", json={
            "content_hash": event["event_id"],  # Using event_id as proxy
            "score": 0.8,
        })
        assert resp.status_code == 200
        assert "feedback_id" in resp.json()

    def test_query_endpoint(self):
        engine = ControlledLearning()
        app, client = self._make_app(engine)
        
        client.post("/api/v1/learn/ingest", json={
            "content": "How to bake bread",
            "source": "web",
            "category": "skill",
        })
        
        resp = client.get("/api/v1/learn/query", params={"query": "bread"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_query_endpoint_trust_filter(self):
        engine = ControlledLearning()
        app, client = self._make_app(engine)
        
        client.post("/api/v1/learn/ingest", json={
            "content": "RAW content",
            "source": "web",
            "trust_level": "RAW",
        })
        client.post("/api/v1/learn/ingest", json={
            "content": "VALIDATED content",
            "source": "web",
            "trust_level": "VALIDATED",
        })
        
        resp = client.get("/api/v1/learn/query", params={
            "query": "",
            "trust_min": "VALIDATED",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_promotions_endpoint(self):
        engine = ControlledLearning()
        app, client = self._make_app(engine)
        
        ingest_resp = client.post("/api/v1/learn/ingest", json={
            "content": "Test",
            "source": "web",
        })
        event_id = ingest_resp.json()["event_id"]
        
        client.post("/api/v1/learn/promote", json={
            "event_id": event_id,
            "target_trust": "VALIDATED",
        })
        
        resp = client.get("/api/v1/learn/promotions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1

    def test_stats_endpoint(self):
        engine = ControlledLearning()
        app, client = self._make_app(engine)
        
        client.post("/api/v1/learn/ingest", json={
            "content": "A",
            "source": "web",
            "category": "skill",
        })
        client.post("/api/v1/learn/ingest", json={
            "content": "B",
            "source": "web",
            "category": "fact",
        })
        
        resp = client.get("/api/v1/learn/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_events"] == 2

    def test_health_endpoint(self):
        engine = ControlledLearning()
        app, client = self._make_app(engine)
        
        resp = client.get("/api/v1/learn/health")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True

    def test_uninitialized_health(self):
        """Test health check when engine is not initialized."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routes.controlled_learning import router, _learning_engine
        
        # Temporarily clear the global
        from app.api.routes import controlled_learning as cl_module
        original = cl_module._learning_engine
        cl_module._learning_engine = None
        
        try:
            app = FastAPI()
            app.include_router(router, prefix="/api/v1")
            client = TestClient(app)
            
            resp = client.get("/api/v1/learn/health")
            assert resp.status_code == 200
            assert resp.json()["ready"] is False
        finally:
            cl_module._learning_engine = original

    def test_ingest_uninitialized(self):
        """Test ingest when engine is not initialized."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routes.controlled_learning import router
        
        from app.api.routes import controlled_learning as cl_module
        original = cl_module._learning_engine
        cl_module._learning_engine = None
        
        try:
            app = FastAPI()
            app.include_router(router, prefix="/api/v1")
            client = TestClient(app)
            
            resp = client.post("/api/v1/learn/ingest", json={})
            assert resp.status_code == 503
        finally:
            cl_module._learning_engine = original


# ═══════════════════════════════════════════════════════════
# Full Pipeline Tests
# ═══════════════════════════════════════════════════════════

class TestFullPipeline:
    """Integration tests for the full controlled learning pipeline."""

    async def test_full_ingest_promote_feedback_loop(self):
        """Test complete lifecycle: ingest → promote → feedback → query."""
        engine = ControlledLearning()
        
        # 1. Ingest
        eid = await engine.ingest(
            content="How to optimize Python code",
            source="blog",
            category="skill",
        )
        assert eid is not None
        
        # 2. Promote to PROMOTED (requires confirmation)
        req_id = await engine.request_promotion(
            event_id=eid,
            target_trust=TrustLevel.PROMOTED,
            reason="High-quality content",
        )
        assert req_id is not None
        
        # 3. Approve
        success = await engine.approve_promotion(req_id)
        assert success is True
        event = await engine.get_event(eid)
        assert event["trust_level"] == "PROMOTED"
        
        # 4. Feedback
        fb_id = await engine.submit_feedback(
            content_hash=event["content_hash"],
            score=0.95,
        )
        assert fb_id is not None
        
        # 5. Query
        results = await engine.query("optimize")
        assert len(results) == 1
        assert results[0]["feedback_score"] == 0.95
        
        # 6. Stats
        stats = await engine.get_stats()
        assert stats["total_events"] == 1
        assert stats["total_usage"] == 1

    async def test_content_deduplication(self):
        """Test that duplicate content gets same hash."""
        engine = ControlledLearning()
        
        eid1 = await engine.ingest(
            content="Same content",
            source="web",
            category="general",
        )
        eid2 = await engine.ingest(
            content="Same content",
            source="web",
            category="general",
        )
        
        event1 = await engine.get_event(eid1)
        event2 = await engine.get_event(eid2)
        assert event1["content_hash"] == event2["content_hash"]

    async def test_safety_boundary_integration(self):
        """Test safety boundaries block unsafe content end-to-end."""
        engine = ControlledLearning(
            safety_boundary=SafetyBoundary(
                blocked_sources=["malicious-site"],
                blocked_categories=["spam"],
                max_content_length=50,
            )
        )
        
        # Blocked source
        assert await engine.ingest("content", "malicious-site") is None
        
        # Blocked category
        assert await engine.ingest("content", "web", "spam") is None
        
        # Too long
        assert await engine.ingest("x" * 100, "web") is None
        
        # Safe content passes
        eid = await engine.ingest("Safe content here", "web", "general")
        assert eid is not None

    async def test_feedback_impacts_query_sorting(self):
        """Test that higher feedback scores appear first in query results."""
        engine = ControlledLearning()
        
        await engine.ingest(content="Low quality", source="web", category="general")
        await engine.ingest(content="High quality", source="web", category="general")
        
        # Get events
        all_results = await engine.query("")
        assert len(all_results) == 2
        
        # Add high feedback to first
        event1 = all_results[0]
        await engine.submit_feedback(
            content_hash=event1.get("content_hash", ""),
            score=0.9,
        )
        
        # Re-query — the high-scored one should be first
        results = await engine.query("")
        assert results[0]["feedback_score"] == 0.9

    async def test_api_full_workflow(self):
        """Test complete API workflow."""
        engine = ControlledLearning()
        app, client = TestFullPipeline._make_test_app(engine)
        
        # 1. Ingest
        resp = client.post("/api/v1/learn/ingest", json={
            "content": "Learned skill",
            "source": "web",
            "category": "skill",
        })
        assert resp.status_code == 200
        event_id = resp.json()["event_id"]
        
        # 2. Promote
        resp = client.post("/api/v1/learn/promote", json={
            "event_id": event_id,
            "target_trust": "VALIDATED",
        })
        assert resp.status_code == 200
        
        # 3. Query
        resp = client.get("/api/v1/learn/query", params={"query": "Learned"})
        assert resp.status_code == 200
        assert resp.json()["count"] == 1
        
        # 4. Stats
        resp = client.get("/api/v1/learn/stats")
        assert resp.status_code == 200
        assert resp.json()["total_events"] == 1
        
        # 5. Health
        resp = client.get("/api/v1/learn/health")
        assert resp.status_code == 200
        assert resp.json()["ready"] is True
    
    @staticmethod
    def _make_test_app(engine):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.routes.controlled_learning import router
        from app.api.routes.controlled_learning import set_learning_engine
        
        set_learning_engine(engine)
        app = FastAPI()
        app.include_router(router, prefix="/api/v1")
        return app, TestClient(app)

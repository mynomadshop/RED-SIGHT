"""
RedSight - High-Performance Local AI Intelligence Platform
Controlled Learning Module

Gated promotion of retrieved content into working/procedural memory,
with safety boundaries, user confirmation, and feedback loops.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TrustLevel(Enum):
    """Trust levels for learning content."""
    RAW = 0           # Unprocessed, untrusted
    PARSED = 1        # Extracted but unvalidated
    VALIDATED = 2     # Checked for consistency
    CONFIRMED = 3     # User confirmed as useful
    PROMOTED = 4      # Promoted to procedural memory


class PromotionStatus(Enum):
    """Status of a promotion request."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"


@dataclass
class LearningEvent:
    """A single learning event."""
    event_id: str
    source: str                    # Where the content came from
    content_hash: str              # Hash of the content
    content: str                   # The actual content
    trust_level: TrustLevel
    category: str                  # e.g., "skill", "fact", "decision"
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    confirmed_at: Optional[float] = None
    revoked_at: Optional[float] = None
    feedback_score: Optional[float] = None  # 0.0 - 1.0
    usage_count: int = 0           # How many times this was used


@dataclass
class PromotionRequest:
    """A request to promote content to higher trust level."""
    request_id: str
    content_hash: str
    source_trust: TrustLevel
    target_trust: TrustLevel
    reason: str
    context: Dict[str, Any] = field(default_factory=dict)
    status: PromotionStatus = PromotionStatus.PENDING
    requested_by: str = "system"   # "system", "user", "agent"
    requested_at: float = field(default_factory=time.time)
    approved_by: Optional[str] = None
    approved_at: Optional[float] = None
    rejection_reason: Optional[str] = None


@dataclass
class FeedbackRecord:
    """A feedback record for learned content."""
    feedback_id: str
    content_hash: str
    score: float                   # 0.0 - 1.0
    comment: Optional[str] = None
    category: str = "quality"      # quality, accuracy, relevance, safety
    created_at: float = field(default_factory=time.time)


class SafetyBoundary:
    """
    Safety boundaries for learning.
    
    Controls what can be learned, from where, and under what conditions.
    """
    
    def __init__(
        self,
        max_trust_per_day: int = 10,
        require_confirmation_for: Optional[List[TrustLevel]] = None,
        blocked_sources: Optional[List[str]] = None,
        blocked_categories: Optional[List[str]] = None,
        max_content_length: int = 10000,
        require_safety_check: bool = True,
    ):
        self.max_trust_per_day = max_trust_per_day
        self.require_confirmation_for = require_confirmation_for or [TrustLevel.PROMOTED]
        self.blocked_sources = blocked_sources or []
        self.blocked_categories = blocked_categories or []
        self.max_content_length = max_content_length
        self.require_safety_check = require_safety_check
        self._daily_count: Dict[str, int] = {}  # source -> count
    
    def is_source_blocked(self, source: str) -> bool:
        """Check if a source is blocked."""
        return source in self.blocked_sources
    
    def is_category_blocked(self, category: str) -> bool:
        """Check if a category is blocked."""
        return category in self.blocked_categories
    
    def is_content_safe(self, content: str) -> tuple[bool, Optional[str]]:
        """Basic safety check on content."""
        if len(content) > self.max_content_length:
            return False, f"Content exceeds {self.max_content_length} characters"
        
        # Check for obviously unsafe patterns
        unsafe_patterns = ["malware", "exploit", "injection", "overflow"]
        content_lower = content.lower()
        for pattern in unsafe_patterns:
            if pattern in content_lower:
                return False, f"Content contains unsafe pattern: {pattern}"
        
        return True, None
    
    def can_promote(self, source: str, category: str, current_trust: TrustLevel, target_trust: TrustLevel) -> tuple[bool, Optional[str]]:
        """Check if a promotion is allowed."""
        # Check source
        if self.is_source_blocked(source):
            return False, f"Source '{source}' is blocked"
        
        # Check category
        if self.is_category_blocked(category):
            return False, f"Category '{category}' is blocked"
        
        # Check trust level bounds
        if target_trust.value <= current_trust.value:
            return False, "Target trust must be higher than current"
        
        # Check if confirmation required
        if target_trust in self.require_confirmation_for:
            return True, "confirmation_required"
        
        # Check daily limit
        today = time.strftime("%Y-%m-%d")
        count = self._daily_count.get(today, 0)
        if count >= self.max_trust_per_day:
            return False, f"Daily trust limit reached ({self.max_trust_per_day})"
        
        return True, None
    
    def record_promotion(self) -> None:
        """Record a promotion for daily limit tracking."""
        today = time.strftime("%Y-%m-%d")
        self._daily_count[today] = self._daily_count.get(today, 0) + 1
    
    def check_safety(self, content: str) -> tuple[bool, Optional[str]]:
        """Run safety check on content."""
        if not self.require_safety_check:
            return True, None
        return self.is_content_safe(content)


class ControlledLearning:
    """
    Controlled Learning Engine.
    
    Manages gated promotion of content into working/procedural memory,
    with safety boundaries, user confirmation, and feedback loops.
    """
    
    def __init__(
        self,
        safety_boundary: Optional[SafetyBoundary] = None,
        working_memory=None,
        procedural_memory=None,
    ):
        self._safety = safety_boundary or SafetyBoundary()
        self._working_memory = working_memory
        self._procedural_memory = procedural_memory
        self._events: Dict[str, LearningEvent] = {}
        self._promotions: Dict[str, PromotionRequest] = {}
        self._feedback: Dict[str, FeedbackRecord] = {}
        self._content_index: Dict[str, List[str]] = {}  # category -> [event_ids]
    
    # ── Content Ingestion ────────────────────────────────────────────
    
    async def ingest(
        self,
        content: str,
        source: str,
        category: str = "general",
        trust_level: TrustLevel = TrustLevel.RAW,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Ingest content into the learning system.
        
        Returns event_id or None if content is blocked.
        """
        # Safety check
        if self._safety.is_source_blocked(source):
            logger.warning(f"Blocked source: {source}")
            return None
        
        if self._safety.is_category_blocked(category):
            logger.warning(f"Blocked category: {category}")
            return None
        
        safe, reason = self._safety.check_safety(content)
        if not safe:
            logger.warning(f"Content blocked: {reason}")
            return None
        
        # Create event
        event_id = f"learn_{uuid.uuid4().hex[:8]}"
        content_hash = self._hash_content(content)
        
        event = LearningEvent(
            event_id=event_id,
            source=source,
            content_hash=content_hash,
            content=content,
            trust_level=trust_level,
            category=category,
            context=context or {},
        )
        
        self._events[event_id] = event
        
        # Index by category
        if category not in self._content_index:
            self._content_index[category] = []
        self._content_index[category].append(event_id)
        
        logger.info(f"Learned content: {event_id} (trust={trust_level.name})")
        return event_id
    
    async def ingest_batch(
        self,
        items: List[Dict[str, Any]],
    ) -> List[str]:
        """Ingest multiple items at once."""
        event_ids = []
        for item in items:
            eid = await self.ingest(
                content=item["content"],
                source=item.get("source", "unknown"),
                category=item.get("category", "general"),
                trust_level=item.get("trust_level", TrustLevel.RAW),
                context=item.get("context"),
            )
            if eid:
                event_ids.append(eid)
        return event_ids
    
    # ── Promotion Management ─────────────────────────────────────────
    
    async def request_promotion(
        self,
        event_id: str,
        target_trust: TrustLevel,
        reason: str = "",
        requested_by: str = "system",
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Request to promote content to a higher trust level."""
        event = self._events.get(event_id)
        if not event:
            logger.warning(f"Event not found: {event_id}")
            return None
        
        if target_trust.value <= event.trust_level.value:
            logger.warning("Cannot promote: target must be higher than current")
            return None
        
        # Safety check
        allowed, check_result = self._safety.can_promote(
            source=event.source,
            category=event.category,
            current_trust=event.trust_level,
            target_trust=target_trust,
        )
        
        if not allowed:
            logger.warning(f"Promotion blocked: {check_result}")
            return None
        
        # Create promotion request
        request_id = f"promo_{uuid.uuid4().hex[:8]}"
        request = PromotionRequest(
            request_id=request_id,
            content_hash=event.content_hash,
            source_trust=event.trust_level,
            target_trust=target_trust,
            reason=reason,
            context=context or {},
            requested_by=requested_by,
        )
        
        # Auto-approve if no confirmation required
        if check_result != "confirmation_required":
            request.status = PromotionStatus.APPROVED
            request.approved_by = "system"
            request.approved_at = time.time()
            await self._execute_promotion(event_id, target_trust, request)
        
        self._promotions[request_id] = request
        logger.info(f"Promotion requested: {request_id} ({event_id} -> {target_trust.name})")
        return request_id
    
    async def approve_promotion(self, request_id: str, approved_by: str = "user") -> bool:
        """Approve a pending promotion request."""
        request = self._promotions.get(request_id)
        if not request or request.status != PromotionStatus.PENDING:
            return False
        
        event = None
        for e in self._events.values():
            if e.content_hash == request.content_hash:
                event = e
                break
        
        if not event:
            return False
        
        request.status = PromotionStatus.APPROVED
        request.approved_by = approved_by
        request.approved_at = time.time()
        
        await self._execute_promotion(event.event_id, request.target_trust, request)
        return True
    
    async def reject_promotion(self, request_id: str, reason: str = "") -> bool:
        """Reject a pending promotion request."""
        request = self._promotions.get(request_id)
        if not request or request.status != PromotionStatus.PENDING:
            return False
        
        request.status = PromotionStatus.REJECTED
        request.rejection_reason = reason
        return True
    
    async def _execute_promotion(self, event_id: str, trust_level: TrustLevel, request: PromotionRequest) -> None:
        """Execute the actual trust level promotion."""
        event = self._events.get(event_id)
        if not event:
            return
        
        old_trust = event.trust_level
        event.trust_level = trust_level
        event.confirmed_at = time.time()
        
        # Promote to procedural memory if promoted to PROMOTED
        if trust_level == TrustLevel.PROMOTED and self._procedural_memory:
            try:
                await self._procedural_memory.store(
                    skill_id=event.event_id,
                    version="1.0.0",
                    workflow={"content": event.content},
                    metadata={"source": event.source, "category": event.category},
                    trust_level=trust_level.value,
                )
                logger.info(f"Promoted to procedural memory: {event_id}")
            except Exception as e:
                logger.error(f"Failed to promote to procedural memory: {e}")
        
        # Store in working memory if it's a high-value fact
        if trust_level in (TrustLevel.VALIDATED, TrustLevel.CONFIRMED) and self._working_memory:
            try:
                await self._working_memory.store(
                    key=f"learned_{event_id}",
                    value=event.content,
                    ttl_seconds=3600,  # 1 hour TTL
                )
            except Exception as e:
                logger.error(f"Failed to store in working memory: {e}")
        
        self._safety.record_promotion()
        logger.info(f"Promoted {event_id}: {old_trust.name} -> {trust_level.name}")
    
    async def revoke_promotion(self, event_id: str) -> bool:
        """Revoke a promotion (downgrade trust level)."""
        event = self._events.get(event_id)
        if not event:
            return False
        
        if event.revoked_at:
            return False  # Already revoked
        
        event.revoked_at = time.time()
        # Drop trust by one level
        new_trust = TrustLevel(max(0, event.trust_level.value - 1))
        event.trust_level = new_trust
        logger.info(f"Revoked promotion: {event_id} -> {new_trust.name}")
        return True
    
    # ── Feedback ─────────────────────────────────────────────────────
    
    async def submit_feedback(
        self,
        content_hash: str,
        score: float,
        category: str = "quality",
        comment: Optional[str] = None,
    ) -> str:
        """Submit feedback for learned content."""
        feedback_id = f"fb_{uuid.uuid4().hex[:8]}"
        
        record = FeedbackRecord(
            feedback_id=feedback_id,
            content_hash=content_hash,
            score=score,
            comment=comment,
            category=category,
        )
        
        self._feedback[feedback_id] = record
        
        # Update event if found
        for event in self._events.values():
            if event.content_hash == content_hash:
                event.feedback_score = score
                event.usage_count += 1
                break
        
        logger.info(f"Feedback recorded: {feedback_id} (score={score})")
        return feedback_id
    
    # ── Query & Analysis ─────────────────────────────────────────────
    
    async def get_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        """Get a learning event by ID."""
        event = self._events.get(event_id)
        if not event:
            return None
        
        return {
            "event_id": event.event_id,
            "source": event.source,
            "content_hash": event.content_hash,
            "content": event.content,
            "trust_level": event.trust_level.name,
            "category": event.category,
            "context": event.context,
            "created_at": event.created_at,
            "confirmed_at": event.confirmed_at,
            "revoked_at": event.revoked_at,
            "feedback_score": event.feedback_score,
            "usage_count": event.usage_count,
        }
    
    async def query(
        self,
        query: str,
        trust_min: TrustLevel = TrustLevel.RAW,
        category: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Query learned content."""
        results = []
        query_lower = query.lower()
        
        for event in self._events.values():
            if event.trust_level.value < trust_min.value:
                continue
            if category and event.category != category:
                continue
            if event.revoked_at:
                continue
            
            # Simple keyword search
            if query_lower and query_lower not in event.content.lower():
                continue
            
            results.append({
                "event_id": event.event_id,
                "source": event.source,
                "content": event.content,
                "content_hash": event.content_hash,
                "trust_level": event.trust_level.name,
                "category": event.category,
                "feedback_score": event.feedback_score,
                "usage_count": event.usage_count,
            })
        
        # Sort by feedback score (highest first), then by usage count
        results.sort(key=lambda x: (x.get("feedback_score") or 0, x.get("usage_count", 0)), reverse=True)
        return results[:limit]
    
    async def get_promotions(
        self,
        status: Optional[PromotionStatus] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get promotion requests."""
        results = []
        for req in self._promotions.values():
            if status and req.status != status:
                continue
            results.append({
                "request_id": req.request_id,
                "content_hash": req.content_hash,
                "source_trust": req.source_trust.name,
                "target_trust": req.target_trust.name,
                "status": req.status.value,
                "reason": req.reason,
                "requested_by": req.requested_by,
                "requested_at": req.requested_at,
                "approved_by": req.approved_by,
                "rejection_reason": req.rejection_reason,
            })
        return results[:limit]
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get learning statistics."""
        trust_counts = {}
        for event in self._events.values():
            name = event.trust_level.name
            trust_counts[name] = trust_counts.get(name, 0) + 1
        
        category_counts = {}
        for event in self._events.values():
            cat = event.category
            category_counts[cat] = category_counts.get(cat, 0) + 1
        
        promo_counts = {}
        for req in self._promotions.values():
            status = req.status.value
            promo_counts[status] = promo_counts.get(status, 0) + 1
        
        return {
            "total_events": len(self._events),
            "trust_distribution": trust_counts,
            "category_distribution": category_counts,
            "total_promotions": len(self._promotions),
            "promotion_status": promo_counts,
            "total_feedback": len(self._feedback),
            "avg_feedback_score": (
                sum(e.feedback_score or 0 for e in self._events.values() if e.feedback_score) /
                max(1, sum(1 for e in self._events.values() if e.feedback_score))
            ),
            "total_usage": sum(e.usage_count for e in self._events.values()),
        }
    
    async def get_content_by_hash(self, content_hash: str) -> Optional[Dict[str, Any]]:
        """Get content by hash."""
        for event in self._events.values():
            if event.content_hash == content_hash:
                return self.get_event(event.event_id)
        return None
    
    def _hash_content(self, content: str) -> str:
        """Create a hash of content for deduplication."""
        import hashlib
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    async def clear(self) -> None:
        """Clear all learning data."""
        self._events.clear()
        self._promotions.clear()
        self._feedback.clear()
        self._content_index.clear()
        logger.info("Learning data cleared")

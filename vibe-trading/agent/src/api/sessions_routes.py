"""Session and goal HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_sessions_routes(app)``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.session.service import SessionBusyError

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models
# ============================================================================

class CreateSessionRequest(BaseModel):
    """Create session request body."""
    title: str = Field("", description="Session title")
    config: Optional[Dict[str, Any]] = Field(None, description="Session config")


class SessionResponse(BaseModel):
    """Session record."""
    session_id: str
    title: str
    status: str
    created_at: str
    updated_at: str
    last_attempt_id: Optional[str] = None


class SendMessageRequest(BaseModel):
    """Send chat message: natural-language strategy description."""
    content: str = Field(..., description="Natural language strategy description", min_length=1, max_length=5000)


class QuickChatRequest(BaseModel):
    """Quick single-prompt chat request."""
    session_id: Optional[str] = Field(None, description="Optional existing session ID")
    message: str = Field(..., min_length=1, description="User prompt text")
    title: Optional[str] = Field(None, description="Optional title when creating new session")


class AshareExportDocxRequest(BaseModel):
    """Request model for exporting Ashare research report to Word .docx format."""
    code: str = Field(..., description="Stock code")
    name: str = Field(..., description="Stock name")
    date: str = Field(..., description="Trading date string")
    content: str = Field(..., description="Markdown report content")
    stats: Optional[Dict[str, Any]] = Field(default=None, description="Stock price and turnover stats")


class MessageResponse(BaseModel):
    """Stored chat message."""
    message_id: str
    session_id: str
    role: str
    content: str
    created_at: str
    linked_attempt_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    tool_trail: List[Dict[str, Any]] = Field(default_factory=list)


class CreateGoalRequest(BaseModel):
    """Create or replace a finance research goal."""

    objective: str = Field(..., min_length=1, max_length=5000)
    criteria: List[str] = Field(default_factory=list)
    ui_summary: str = ""
    protocol: str = "thesis_review"
    risk_tier: str = "research_general"
    token_budget: Optional[int] = Field(None, ge=1)
    turn_budget: Optional[int] = Field(None, ge=1)
    time_budget_seconds: Optional[int] = Field(None, ge=1)


class UpdateGoalRequest(BaseModel):
    """Edit mutable finance research goal fields."""

    goal_id: str = Field(..., min_length=1)
    expected_goal_id: str = Field(..., min_length=1)
    objective: Optional[str] = Field(None, min_length=1, max_length=5000)
    ui_summary: Optional[str] = Field(None, max_length=500)


class AddGoalEvidenceRequest(BaseModel):
    """Append evidence to a finance research goal."""

    goal_id: str = Field(..., min_length=1)
    expected_goal_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1, max_length=10000)
    criterion_id: Optional[str] = None
    claim_id: Optional[str] = None
    evidence_type: str = "evidence"
    tool_call_id: Optional[str] = None
    run_id: Optional[str] = None
    source_provider: Optional[str] = None
    source_type: Optional[str] = None
    source_uri: Optional[str] = None
    symbol_universe: List[str] = Field(default_factory=list)
    benchmark: List[str] = Field(default_factory=list)
    timeframe: Optional[str] = None
    method: Optional[str] = None
    assumptions: Dict[str, Any] = Field(default_factory=dict)
    artifact_path: Optional[str] = None
    artifact_hash: Optional[str] = None
    data_as_of: Optional[str] = None
    confidence: Optional[str] = None
    caveat: Optional[str] = None
    contradicts_claim_ids: List[str] = Field(default_factory=list)


class GoalSnapshotResponse(BaseModel):
    """Finance research goal snapshot."""

    goal: Dict[str, Any]
    claims: List[Dict[str, Any]]
    criteria: List[Dict[str, Any]]
    evidence: List[Dict[str, Any]]
    evidence_count: int = 0


class AddGoalEvidenceResponse(BaseModel):
    """Response after appending goal evidence."""

    evidence: Dict[str, Any]
    snapshot: GoalSnapshotResponse


class GoalAuditRowRequest(BaseModel):
    """One criterion row for goal status audits."""

    criterion_id: str = Field(..., min_length=1)
    result: str = Field(..., min_length=1)
    evidence_ids: List[str] = Field(default_factory=list)
    notes: str = ""


class UpdateGoalStatusRequest(BaseModel):
    """Update a finance research goal status."""

    goal_id: str = Field(..., min_length=1)
    expected_goal_id: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    audit: List[GoalAuditRowRequest] = Field(default_factory=list)
    recap: Optional[str] = None


class UpdateGoalStatusResponse(BaseModel):
    """Response after changing a goal status."""

    goal: Dict[str, Any]
    snapshot: GoalSnapshotResponse


class UpdateGoalResponse(BaseModel):
    """Response after editing a goal."""

    goal: Dict[str, Any]
    snapshot: GoalSnapshotResponse


class UpdateSessionRequest(BaseModel):
    """Session update fields."""
    title: Optional[str] = None


# ============================================================================
# State variables
# ============================================================================

_goal_store = None


# ============================================================================
# Helper Functions
# ============================================================================

def _get_goal_store():
    """Return the shared finance goal store."""
    global _goal_store
    if _goal_store is None:
        from src.goal import GoalStore

        _goal_store = GoalStore()
    return _goal_store

# ============================================================================
# SSE frame helpers for session events (module-level for re-export)
# ============================================================================

_PROPOSAL_TOOL_NAME = "propose_mandate_profiles"
_PROPOSAL_ID_RE = re.compile(r'"proposal_id"\s*:\s*"(mp_[0-9a-f]{32})"')
_SCHEDULED_PROPOSAL_TOOL_NAME = "scheduled_research"
_SCHEDULED_PROPOSAL_ID_RE = re.compile(
    r'"proposal_id"\s*:\s*"(srp_[0-9a-f]{32})"'
)


def _load_full_proposal(proposal_id: str) -> Optional[Dict[str, Any]]:
    """Reload a persisted mandate proposal by id, broker-agnostic."""
    try:
        from src.live.paths import live_root

        for proposal_path in live_root().glob(f"*/proposals/{proposal_id}.json"):
            try:
                data = json.loads(proposal_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, dict) and data.get("type") == "mandate.proposal":
                return data
    except Exception:  # pragma: no cover - relay must never break the stream
        logger.debug("mandate.proposal reload failed for %s", proposal_id, exc_info=True)
    return None


def _mandate_proposal_frame_from_tool_result(event: Any) -> Optional[str]:
    """Build a mandate.proposal SSE frame from a propose-tool tool_result."""
    data = getattr(event, "data", None)
    if getattr(event, "event_type", None) != "tool_result" or not isinstance(data, dict):
        return None
    if data.get("tool") != _PROPOSAL_TOOL_NAME or data.get("status") != "ok":
        return None
    match = _PROPOSAL_ID_RE.search(str(data.get("preview") or ""))
    if not match:
        return None
    proposal = _load_full_proposal(match.group(1))
    if proposal is None:
        return None

    from src.session.events import SSEEvent

    frame = SSEEvent(
        event_type="mandate.proposal",
        data=proposal,
        session_id=getattr(event, "session_id", "") or "",
    )
    return frame.to_sse()


def _scheduled_proposal_frame_from_tool_result(event: Any) -> Optional[str]:
    """Build a deterministic scheduled-research confirmation SSE frame."""
    data = getattr(event, "data", None)
    if getattr(event, "event_type", None) != "tool_result" or not isinstance(data, dict):
        return None
    if data.get("tool") != _SCHEDULED_PROPOSAL_TOOL_NAME or data.get("status") != "ok":
        return None
    match = _SCHEDULED_PROPOSAL_ID_RE.search(str(data.get("preview") or ""))
    if not match:
        return None
    try:
        from src.scheduled_research.proposals import load_proposal

        proposal = load_proposal(match.group(1))
    except Exception:  # pragma: no cover - relay must never break the stream
        logger.debug("scheduled proposal reload failed", exc_info=True)
        return None
    from src.session.events import SSEEvent

    return SSEEvent(
        event_type="scheduled_research.proposal",
        data=proposal,
        session_id=getattr(event, "session_id", "") or "",
    ).to_sse()


_LIVE_ACTION_ID_RE = re.compile(r'"audit_id"\s*:\s*"(la_[0-9a-zA-Z]+)"')


def _load_live_action_record(audit_id: str) -> Optional[Dict[str, Any]]:
    """Reload a redacted live-action record from the ledger by audit_id."""
    try:
        from src.live.paths import live_root

        ledger = live_root() / "audit.jsonl"
        if not ledger.exists():
            return None
        for line in reversed(ledger.read_text(encoding="utf-8").splitlines()):
            if audit_id not in line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("audit_id") == audit_id:
                return record
    except Exception:  # pragma: no cover - relay must never break the stream
        logger.debug("live.action reload failed for %s", audit_id, exc_info=True)
    return None


def _live_action_frame_from_tool_result(event: Any) -> Optional[str]:
    """Build a live.action SSE frame from an order-guard tool_result."""
    data = getattr(event, "data", None)
    if getattr(event, "event_type", None) != "tool_result" or not isinstance(data, dict):
        return None
    preview = str(data.get("preview") or "")
    if '"live_action"' not in preview:
        return None
    match = _LIVE_ACTION_ID_RE.search(preview)
    if not match:
        return None
    record = _load_live_action_record(match.group(1))
    if record is None:
        return None

    from src.session.events import SSEEvent

    frame = SSEEvent(
        event_type="live.action",
        data=record,
        session_id=getattr(event, "session_id", "") or "",
    )
    return frame.to_sse()



# ============================================================================
# Registration
# ============================================================================

def register_sessions_routes(app: FastAPI) -> None:
    """Mount the session/goal routes onto ``app``.

    Resolves shared dependencies from the host ``api_server`` module via
    ``sys.modules``.
    """
    import sys as _sys

    host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
    if host is None:
        raise RuntimeError(
            "register_sessions_routes: api_server module not in sys.modules; "
            "ensure api_server is imported before calling this function"
        )

    # Auth dependencies
    require_auth = host.require_auth
    require_event_stream_auth = host.require_event_stream_auth

    # Late-access closures for shared host symbols (monkeypatch-safe)
    def _host_get_session_service():
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return h._get_session_service()

    def _host_validate_path_param(value: str, kind: str) -> None:
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return h._validate_path_param(value, kind)

    def _host_shell_tools_enabled_for_request(request: Request) -> bool:
        h = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return h._shell_tools_enabled_for_request(request)

    def _get_existing_session_or_404(session_id: str):
        """Return (service, session) or raise 404."""
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        session = svc.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return svc, session

    # -----------------------------------------------------------------------
    # Session CRUD routes
    # -----------------------------------------------------------------------

    @app.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
    async def create_session(
        request: CreateSessionRequest,
        principal=Depends(require_auth),
    ):
        """Create a chat session.

        The authenticated principal is recorded as the session owner. Under the
        shared-key and loopback auth modes that principal is not attributable to
        a named human -- it carries ``attributable=False`` and must not be read
        as an identity. Recording it anyway is still worth doing: it captures
        HOW the session was authorised, which is the part that becomes an
        identity once an identity provider is wired in.
        """
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        session = svc.create_session(
            title=request.title, config=request.config, owner=principal
        )
        return SessionResponse(
            session_id=session.session_id,
            title=session.title,
            status=session.status.value,
            created_at=session.created_at,
            updated_at=session.updated_at,
            last_attempt_id=session.last_attempt_id,
        )

    @app.get("/sessions", response_model=List[SessionResponse], dependencies=[Depends(require_auth)])
    async def list_sessions(limit: int = Query(50, ge=1, le=200)):
        """List sessions."""
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        sessions = svc.list_sessions(limit=limit)
        return [
            SessionResponse(
                session_id=s.session_id,
                title=s.title,
                status=s.status.value,
                created_at=s.created_at,
                updated_at=s.updated_at,
                last_attempt_id=s.last_attempt_id,
            )
            for s in sessions
        ]

    @app.get("/sessions/{session_id}", response_model=SessionResponse, dependencies=[Depends(require_auth)])
    async def get_session(session_id: str):
        """Get one session by id."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        session = svc.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        return SessionResponse(
            session_id=session.session_id,
            title=session.title,
            status=session.status.value,
            created_at=session.created_at,
            updated_at=session.updated_at,
            last_attempt_id=session.last_attempt_id,
        )

    # -----------------------------------------------------------------------
    # Goal sub-group routes
    # -----------------------------------------------------------------------

    @app.post(
        "/sessions/{session_id}/goal",
        response_model=GoalSnapshotResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_auth)],
    )
    async def create_session_goal(session_id: str, req: CreateGoalRequest):
        """Create or replace the current finance research goal for a session."""
        _host_validate_path_param(session_id, "session_id")
        svc, _session = _get_existing_session_or_404(session_id)
        from src.goal import RiskTier
        from src.goal.context import default_goal_criteria

        criteria = [item.strip() for item in req.criteria if item.strip()]
        if not criteria:
            criteria = default_goal_criteria()
        try:
            risk_tier = RiskTier(req.risk_tier)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid risk_tier: {req.risk_tier}") from exc
        if risk_tier is RiskTier.LIVE_TRADING_OR_EXECUTION:
            raise HTTPException(status_code=400, detail="live trading or execution goals are not supported")

        goal_store = _get_goal_store()
        try:
            goal = goal_store.replace_goal(
                session_id=session_id,
                objective=req.objective,
                criteria=criteria,
                ui_summary=req.ui_summary,
                source="api",
                protocol=req.protocol,
                risk_tier=risk_tier,
                token_budget=req.token_budget,
                turn_budget=req.turn_budget,
                time_budget_seconds=req.time_budget_seconds,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        snapshot = goal_store.get_goal_snapshot(goal.goal_id)
        if snapshot is None:
            raise HTTPException(status_code=500, detail="Goal created but could not be reloaded")
        svc.event_bus.emit(session_id, "goal.created", {"goal": snapshot["goal"]})
        return snapshot

    @app.get(
        "/sessions/{session_id}/goal",
        response_model=GoalSnapshotResponse,
        dependencies=[Depends(require_auth)],
    )
    async def get_session_goal(session_id: str):
        """Return the current finance research goal snapshot for a session."""
        _host_validate_path_param(session_id, "session_id")
        _get_existing_session_or_404(session_id)
        snapshot = _get_goal_store().get_current_snapshot(session_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No current goal")
        return snapshot

    @app.patch(
        "/sessions/{session_id}/goal",
        response_model=UpdateGoalResponse,
        dependencies=[Depends(require_auth)],
    )
    async def update_session_goal(session_id: str, req: UpdateGoalRequest):
        """Edit the current finance research goal without replacing the session."""
        _host_validate_path_param(session_id, "session_id")
        svc, _session = _get_existing_session_or_404(session_id)
        from src.goal import StaleGoalError

        if req.objective is None and req.ui_summary is None:
            raise HTTPException(status_code=400, detail="objective or ui_summary is required")

        goal_store = _get_goal_store()
        try:
            goal = goal_store.update_goal(
                session_id=session_id,
                goal_id=req.goal_id,
                expected_goal_id=req.expected_goal_id,
                objective=req.objective,
                ui_summary=req.ui_summary,
            )
        except StaleGoalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        snapshot = goal_store.get_goal_snapshot(goal.goal_id)
        if snapshot is None:
            raise HTTPException(status_code=500, detail="Goal snapshot could not be reloaded")
        svc.event_bus.emit(session_id, "goal.updated", {"goal": snapshot["goal"], "snapshot": snapshot})
        return {"goal": snapshot["goal"], "snapshot": snapshot}

    @app.post(
        "/sessions/{session_id}/goal/evidence",
        response_model=AddGoalEvidenceResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_auth)],
    )
    async def add_session_goal_evidence(session_id: str, req: AddGoalEvidenceRequest):
        """Append traceable evidence to the current finance research goal."""
        _host_validate_path_param(session_id, "session_id")
        svc, _session = _get_existing_session_or_404(session_id)
        from dataclasses import asdict
        from src.goal import EvidenceInput, StaleGoalError

        goal_store = _get_goal_store()
        try:
            evidence = goal_store.append_evidence(
                session_id=session_id,
                goal_id=req.goal_id,
                expected_goal_id=req.expected_goal_id,
                evidence=EvidenceInput(
                    criterion_id=req.criterion_id,
                    claim_id=req.claim_id,
                    evidence_type=req.evidence_type,
                    text=req.text,
                    tool_call_id=req.tool_call_id,
                    run_id=req.run_id,
                    source_provider=req.source_provider,
                    source_type=req.source_type,
                    source_uri=req.source_uri,
                    symbol_universe=req.symbol_universe,
                    benchmark=req.benchmark,
                    timeframe=req.timeframe,
                    method=req.method,
                    assumptions=req.assumptions,
                    artifact_path=req.artifact_path,
                    artifact_hash=req.artifact_hash,
                    data_as_of=req.data_as_of,
                    confidence=req.confidence,
                    caveat=req.caveat,
                    contradicts_claim_ids=req.contradicts_claim_ids,
                ),
            )
        except StaleGoalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        snapshot = goal_store.get_goal_snapshot(req.goal_id)
        if snapshot is None:
            raise HTTPException(status_code=500, detail="Goal snapshot could not be reloaded")
        svc.event_bus.emit(
            session_id,
            "goal.evidence",
            {"evidence": asdict(evidence), "goal_id": req.goal_id},
        )
        return {"evidence": asdict(evidence), "snapshot": snapshot}

    @app.patch(
        "/sessions/{session_id}/goal/status",
        response_model=UpdateGoalStatusResponse,
        dependencies=[Depends(require_auth)],
    )
    async def update_session_goal_status(session_id: str, req: UpdateGoalStatusRequest):
        """Update the current finance research goal status."""
        _host_validate_path_param(session_id, "session_id")
        svc, _session = _get_existing_session_or_404(session_id)
        from src.goal import AuditRow, GoalStatus, StaleGoalError

        try:
            next_status = GoalStatus(req.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"invalid goal status: {req.status}") from exc

        goal_store = _get_goal_store()
        try:
            goal = goal_store.update_status(
                session_id=session_id,
                goal_id=req.goal_id,
                expected_goal_id=req.expected_goal_id,
                status=next_status,
                audit=[
                    AuditRow(
                        criterion_id=row.criterion_id,
                        result=row.result,
                        evidence_ids=row.evidence_ids,
                        notes=row.notes,
                    )
                    for row in req.audit
                ],
                recap=req.recap,
            )
        except StaleGoalError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        snapshot = goal_store.get_goal_snapshot(goal.goal_id)
        if snapshot is None:
            raise HTTPException(status_code=500, detail="Goal snapshot could not be reloaded")
        svc.event_bus.emit(session_id, "goal.updated", {"goal": snapshot["goal"], "snapshot": snapshot})
        return {"goal": snapshot["goal"], "snapshot": snapshot}

    # -----------------------------------------------------------------------
    # Session action routes
    # -----------------------------------------------------------------------

    @app.delete("/sessions/{session_id}", dependencies=[Depends(require_auth)])
    async def delete_session(session_id: str):
        """Delete a session."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        deleted = svc.delete_session(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        _get_goal_store().delete_session_goals(session_id)
        return {"status": "deleted", "session_id": session_id}

    @app.patch("/sessions/{session_id}", dependencies=[Depends(require_auth)])
    async def update_session(session_id: str, req: UpdateSessionRequest):
        """Update session fields (e.g. title)."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        session = svc.store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        if req.title is not None:
            session.title = req.title
        session.updated_at = datetime.now(timezone.utc).isoformat()
        svc.store.update_session(session)
        return {"status": "updated", "session_id": session_id}

    @app.post("/sessions/{session_id}/title/auto", dependencies=[Depends(require_auth)])
    async def auto_title_session(session_id: str):
        """Summarize the first exchange into a short LLM-generated title.

        Never clobbers a manual rename: only rewrites when the current title
        is empty or still the auto-set first-prompt prefix from create time.
        """
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        session = svc.store.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        messages = svc.get_messages(session_id, limit=6)
        first_user = next(
            (m for m in messages if m.role == "user" and (m.content or "").strip()), None
        )
        if first_user is None:
            raise HTTPException(status_code=409, detail="Session has no user message to summarize")

        current = (session.title or "").strip()
        auto_prefix = first_user.content.strip()[:50].strip()
        if current and current != auto_prefix:
            return {"status": "kept", "session_id": session_id, "title": current}

        first_assistant = next(
            (m for m in messages if m.role == "assistant" and (m.content or "").strip()), None
        )
        excerpt = f"User: {first_user.content.strip()[:600]}"
        if first_assistant:
            excerpt += f"\nAssistant: {first_assistant.content.strip()[:600]}"
        prompt = (
            "Write a session title for the conversation below: at most 8 words "
            "(or 16 CJK characters), in the same language as the user's message, "
            "no quotes, no trailing punctuation. Reply with the title only.\n\n"
            + excerpt
        )

        def _generate() -> str:
            from src.providers.chat import ChatLLM

            llm = ChatLLM()
            try:
                response = llm.chat([{"role": "user", "content": prompt}], timeout=30)
                return (getattr(response, "content", "") or "").strip()
            finally:
                llm.close()

        try:
            raw = await asyncio.to_thread(_generate)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"title generation failed: {exc}")

        title = raw.splitlines()[0].strip().strip("\"'“”「」『』").strip() if raw else ""
        chars = list(title)
        if len(chars) > 40:
            title = "".join(chars[:40])
        if not title:
            raise HTTPException(status_code=502, detail="empty title from model")

        session.title = title
        session.updated_at = datetime.now(timezone.utc).isoformat()
        svc.store.update_session(session)
        return {"status": "updated", "session_id": session_id, "title": title}

    @app.post("/sessions/{session_id}/messages", dependencies=[Depends(require_auth)])
    async def send_message(session_id: str, payload: SendMessageRequest, http_request: Request):
        """Send a user message and start the agent loop (natural language strategy)."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        try:
            result = await svc.send_message(
                session_id=session_id,
                content=payload.content,
                include_shell_tools=_host_shell_tools_enabled_for_request(http_request),
            )
            return result
        except SessionBusyError as exc:
            # Must precede ValueError-style handling and stay distinct from 404:
            # the session exists, it is simply already running.
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.post("/sessions/{session_id}/cancel", dependencies=[Depends(require_auth)])
    async def cancel_session(session_id: str):
        """Cancel the in-flight agent loop for this session."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        cancelled = svc.cancel_current(session_id)
        if not cancelled:
            return {"status": "no_active_loop"}
        return {"status": "cancelled"}

    @app.get("/sessions/{session_id}/messages", response_model=List[MessageResponse], dependencies=[Depends(require_auth)])
    async def get_messages(session_id: str, limit: int = Query(100, ge=1, le=1000)):
        """List messages for a session."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        messages = svc.get_messages(session_id, limit=limit)
        return [
            MessageResponse(
                message_id=m.message_id,
                session_id=m.session_id,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
                linked_attempt_id=m.linked_attempt_id,
                metadata=m.metadata if m.metadata else None,
                tool_trail=m.tool_trail,
            )
            for m in messages
        ]

    @app.get("/sessions/{session_id}/events", dependencies=[Depends(require_event_stream_auth)])
    async def session_events(
        session_id: str,
        request: Request,
        last_event_id: Optional[str] = Query(None, alias="Last-Event-ID"),
        replay: Optional[str] = Query(None),
    ):
        """SSE stream for agent events."""
        _host_validate_path_param(session_id, "session_id")
        svc = _host_get_session_service()
        if not svc:
            raise HTTPException(status_code=501, detail="Session runtime not enabled")
        session = svc.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

        header_id = request.headers.get("Last-Event-ID")
        event_id = header_id or last_event_id
        replay_active = (replay or "").lower() == "active"
        replay_all = False
        if replay_active and not event_id and session.last_attempt_id:
            attempt = svc.store.get_attempt(session_id, session.last_attempt_id)
            attempt_status = getattr(attempt.status, "value", attempt.status) if attempt else None
            replay_all = attempt_status == "running"

        async def event_generator():
            async for event in svc.event_bus.subscribe(
                session_id,
                last_event_id=event_id,
                replay_all=replay_all,
            ):
                if await request.is_disconnected():
                    break
                yield event.to_sse()
                relayed = _mandate_proposal_frame_from_tool_result(event)
                if relayed is not None:
                    yield relayed
                scheduled_relay = _scheduled_proposal_frame_from_tool_result(event)
                if scheduled_relay is not None:
                    yield scheduled_relay
                live_action = _live_action_frame_from_tool_result(event)
                if live_action is not None:
                    yield live_action

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ========================================================================
    # Ashare Quantitative Research Agent Chat Endpoints (ReAct Mode)
    # ========================================================================
    async def _handle_quick_chat(payload: QuickChatRequest):
        """Financial Quant Agent implementation with tool execution and streaming SSE."""
        import os
        import json
        import httpx
        from src.session.models import Message
        from fastapi.responses import StreamingResponse
        from src.api.ashare_agent_tools import ASHARE_AGENT_TOOLS, execute_agent_tool

        svc = _host_get_session_service()
        sid = payload.session_id

        # If no session_id provided, create one
        if not sid and svc:
            session_title = payload.title or "A 股量化特征投研诊断"
            new_sess = svc.create_session(title=session_title)
            sid = new_sess.session_id

        # 1. 提取该 session 已有的历史对话消息 (在写入当前用户消息前)
        raw_history = []
        if payload.session_id and svc:
            try:
                raw_history = svc.store.get_messages(payload.session_id) or []
            except Exception as e:
                logger.warning("Failed to fetch session messages: %s", e)

        # 清洗并整理历史消息（剔除 think 标签与空白消息，仅保留 user 和 assistant）
        cleaned_history = []
        import re
        for m in raw_history:
            m_role = getattr(m, "role", "user")
            m_content = getattr(m, "content", "") or ""
            clean_c = re.sub(r"<think>[\s\S]*?</think>", "", m_content, flags=re.IGNORECASE).strip()
            clean_c = re.sub(r"</?think>", "", clean_c, flags=re.IGNORECASE).strip()
            if clean_c and m_role in ("user", "assistant"):
                cleaned_history.append({"role": m_role, "content": clean_c})

        # Save current user message to session store if session exists
        if sid and svc:
            try:
                user_msg = Message(
                    message_id=f"msg_{int(datetime.now(timezone.utc).timestamp()*1000)}_user",
                    session_id=sid,
                    role="user",
                    content=payload.message,
                    created_at=datetime.now(timezone.utc).isoformat(),
                )
                svc.store.append_message(user_msg)
            except Exception as e:
                logger.warning("Failed to store user message: %s", e)

        # 2. 组装发给大模型的多轮 messages (首轮量化特征锚定 + 最近对话滑动窗口)
        sys_prompt = {
            "role": "system",
            "content": (
                "你是由顶级量化对冲基金打造的 A 股金融量化与特征工程投研专家 Agent。"
                "回答必须全流程强制使用简体中文，风格严谨专业、语言干练犀利、排版优雅规范。\n\n"
                "【全景量化工具调用指引】\n"
                "你拥有调用 A 股全景金融量化工具矩阵的完整权限：\n"
                "1. Alpha Zoo 472 因子库即时量化画像与多空打分: get_alpha_zoo_profile\n"
                "2. 龙虎榜机构与游资席位明细: get_stock_dragon_tiger\n"
                "3. 主力/超大单/大单微观资金流向: get_fund_flow\n"
                "4. 北向资金/陆股通外资流入: get_northbound_flow\n"
                "5. 融资融券余额与多空两融杠杆: get_margin_trading\n"
                "6. 股东户数变动与筹码集中度: get_shareholder_count\n"
                "7. 大宗交易成交溢折价与席位: get_block_trades\n"
                "8. 限售股解禁日期与流通盘压力: get_lockup_expiry\n"
                "9. 财务三表核心指标与成长性: get_financial_statements\n"
                "10. 所属申万行业与概念板块联动: get_sector_info\n"
                "11. 公司基本资料与主营构成: get_stock_profile\n"
                "12. 机构公募/社保/QFII重仓持股: get_institutional_holdings\n"
                "13. 个股最新核心公告与新闻舆情: get_stock_news\n"
                "14. 多周期技术指标(MACD/RSI/布林带): technical_indicators\n\n"
                "【并行调用规范】\n"
                "在首轮推演中，你必须一次性在单个 tool_calls 列表中并行调用全部相关的 A 股量化工具（包括必选的 get_alpha_zoo_profile 472因子画像，以及龙虎榜、资金流、北向资金、两融、股东户数、财务三表、技术指标、板块联动、公司资料、机构持仓、公告等），严禁分批单步调用，以便系统并行全量检索并快速生成全景投研报告！\n\n"
                "【研报排版与结构化规范】\n"
                "在获得工具结果后，请按以下 4 大核心章节生成极简纯净、专业金融级的 Markdown 深度投研研报：\n\n"
                "## 一、Alpha Zoo 多因子量化画像与综合评分\n"
                "- 必须输出标准对齐的 Markdown 表格（包含表头与对齐分隔线）：\n"
                "| 因子名称 | 因子ID | 因子公式 | 最新值 | 时序分位 | 评分 / 状态 |\n"
                "| :--- | :--- | :--- | ---: | ---: | :--- |\n"
                "- 提炼 Top 3 核心多头贡献因子 与 Top 3 核心空头抑制因子；\n"
                "- 给出加权 Alpha Zoo 综合评分与定性评级。\n\n"
                "## 二、量价形态与微观结构推演\n"
                "- 深入诊断当前触发策略因子（如 HL+5R, 5R, HIGH_ALL, AMO放量等）的微观质量与资金意图；\n"
                "- 结合 MA5~MA377 均线矩阵与前期高低点，计算第一支撑位、第二支撑位及上方筹码阻力位。\n\n"
                "## 三、基本面财务与资金席位交叉印证\n"
                "- 交叉印证主力超大单资金流向、龙虎榜席位与最新股东户数/筹码集中度；\n"
                "- 结合营收净利增速与 ROE 评估基本面匹配度。\n\n"
                "## 四、交易操作策略与风控止损位\n"
                "- 使用 `> 💡 操作建议: ...` 给出明确的仓位管理与择时建议；\n"
                "- 使用 `> ⚠️ 风控警示: ...` 给出严格的形态失效条件与止损点位。\n\n"
                "【多轮追问答疑指引】\n"
                "如果当前对话属于对已出具研报的多轮追问、技术细节探讨或特定行情推演，请直接针对投资者的具体问题进行严谨详尽、逻辑清晰的专业解答与量化分析，全流程强制使用简体中文，排版优雅清晰，无需机械套用首轮的 4 大章节大标题。"
            )
        }

        messages = [sys_prompt]
        if cleaned_history:
            if len(cleaned_history) > 8:
                messages.append(cleaned_history[0])
                if len(cleaned_history) > 1 and cleaned_history[1]["role"] == "assistant":
                    messages.append(cleaned_history[1])
                for h in cleaned_history[-6:]:
                    if h not in messages:
                        messages.append(h)
            else:
                messages.extend(cleaned_history)

        messages.append({"role": "user", "content": payload.message})

        primary_base_url = os.getenv("PRIMARY_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL", "http://127.0.0.1:62202/0d574b39/sync/v1")
        primary_model = os.getenv("PRIMARY_LLM_MODEL") or os.getenv("OPENAI_MODEL_NAME", "Qwen3.8-27B")
        primary_api_key = os.getenv("PRIMARY_LLM_API_KEY") or os.getenv("OPENAI_API_KEY", "")

        async def stream_generator():
            full_reasoning = []
            full_content = []
            tool_trails = []
            upstream_url = "http://127.0.0.1:62202/0d574b39/sync/v1/chat/completions"
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {primary_api_key}",
            }

            max_agent_turns = 3
            current_turn = 0

            try:
                while current_turn < max_agent_turns:
                    current_turn += 1
                    use_tools = ASHARE_AGENT_TOOLS if current_turn < 3 else None

                    body = {
                        "model": primary_model,
                        "messages": messages,
                        "temperature": 0.2,
                        "max_tokens": 65536,
                        "stream": True,
                    }
                    if use_tools:
                        body["tools"] = use_tools
                        body["tool_choice"] = "auto"

                    in_think_mode = False
                    in_tool_mode = False
                    pending_c_buf = ""
                    tool_calls_buffer = {}
                    text_tool_calls_buf = []
                    turn_has_tool_calls = False

                    turn_content_buf = []

                    async with httpx.AsyncClient(timeout=180.0) as client:
                        async with client.stream("POST", upstream_url, json=body, headers=headers) as response:
                            if response.status_code != 200:
                                err_body = await response.aread()
                                logger.error("Upstream error: status=%d body=%s", response.status_code, err_body)
                                raise RuntimeError(f"Upstream returned HTTP {response.status_code}")

                            async for line in response.aiter_lines():
                                line = line.strip()
                                if not line or not line.startswith("data:"):
                                    continue
                                data_str = line[5:].strip()
                                if data_str == "[DONE]":
                                    break
                                try:
                                    chunk = json.loads(data_str)
                                    choices = chunk.get("choices", [])
                                    if not choices:
                                        continue
                                    delta = choices[0].get("delta", {})

                                    # 1. 检查是否有 OpenAI 原生 tool_calls 增量
                                    if "tool_calls" in delta and delta["tool_calls"]:
                                        turn_has_tool_calls = True
                                        for tc in delta["tool_calls"]:
                                            idx = tc.get("index", 0)
                                            if idx not in tool_calls_buffer:
                                                tool_calls_buffer[idx] = {
                                                    "id": tc.get("id") or f"call_{len(tool_calls_buffer)}",
                                                    "name": tc.get("function", {}).get("name", ""),
                                                    "arguments": tc.get("function", {}).get("arguments", ""),
                                                }
                                            else:
                                                if tc.get("function", {}).get("name"):
                                                    tool_calls_buffer[idx]["name"] += tc["function"]["name"]
                                                if tc.get("function", {}).get("arguments"):
                                                    tool_calls_buffer[idx]["arguments"] += tc["function"]["arguments"]

                                    # 2. 检查 reasoning 与 content (支持 <think> 与 <tool_call> 标签拦截)
                                    r_chunk = delta.get("reasoning", "") or delta.get("reasoning_content", "") or ""
                                    c_chunk = delta.get("content", "") or ""

                                    emit_reasoning = ""
                                    emit_content = ""

                                    if r_chunk:
                                        emit_reasoning += r_chunk

                                    if c_chunk:
                                        pending_c_buf += c_chunk
                                        while pending_c_buf:
                                            # 处理 <think> 模式
                                            if in_think_mode:
                                                if "</think>" in pending_c_buf:
                                                    before, _, after = pending_c_buf.partition("</think>")
                                                    if before:
                                                        emit_reasoning += before
                                                    in_think_mode = False
                                                    pending_c_buf = after
                                                elif any(pending_c_buf.endswith(prefix) for prefix in ["<", "</", "</t", "</th", "</thi", "</thin", "</think"]):
                                                    for p in ["</think", "</thin", "</thi", "</th", "</t", "</", "<"]:
                                                        if pending_c_buf.endswith(p):
                                                            cut_idx = len(pending_c_buf) - len(p)
                                                            if cut_idx > 0:
                                                                emit_reasoning += pending_c_buf[:cut_idx]
                                                                pending_c_buf = pending_c_buf[cut_idx:]
                                                            break
                                                    break
                                                else:
                                                    emit_reasoning += pending_c_buf
                                                    pending_c_buf = ""
                                            # 处理 <tool_call> 模式 (拦截工具调用文本)
                                            elif in_tool_mode:
                                                if "</tool_call>" in pending_c_buf:
                                                    before, _, after = pending_c_buf.partition("</tool_call>")
                                                    text_tool_calls_buf.append(before + "</tool_call>")
                                                    in_tool_mode = False
                                                    pending_c_buf = after
                                                else:
                                                    text_tool_calls_buf.append(pending_c_buf)
                                                    pending_c_buf = ""
                                            else:
                                                # 常规内容模式
                                                if "<think>" in pending_c_buf:
                                                    before, _, after = pending_c_buf.partition("<think>")
                                                    if before:
                                                        emit_content += before
                                                    in_think_mode = True
                                                    pending_c_buf = after
                                                elif "<tool_call>" in pending_c_buf:
                                                    before, _, after = pending_c_buf.partition("<tool_call>")
                                                    if before:
                                                        emit_content += before
                                                    in_tool_mode = True
                                                    text_tool_calls_buf.append("<tool_call>")
                                                    pending_c_buf = after
                                                elif any(pending_c_buf.endswith(prefix) for prefix in ["<", "<t", "<th", "<thi", "<thin", "<think", "<to", "<too", "<tool", "<tool_"]):
                                                    for p in ["<tool_call", "<tool_", "<tool", "<too", "<to", "<think", "<thin", "<thi", "<th", "<t", "<"]:
                                                        if pending_c_buf.endswith(p):
                                                            cut_idx = len(pending_c_buf) - len(p)
                                                            if cut_idx > 0:
                                                                emit_content += pending_c_buf[:cut_idx]
                                                                pending_c_buf = pending_c_buf[cut_idx:]
                                                            break
                                                    break
                                                else:
                                                    emit_content += pending_c_buf
                                                    pending_c_buf = ""

                                    if emit_reasoning:
                                        full_reasoning.append(emit_reasoning)
                                        yield f"data: {json.dumps({'session_id': sid, 'reasoning_delta': emit_reasoning, 'content_delta': ''}, ensure_ascii=False)}\n\n"

                                    if emit_content:
                                        full_content.append(emit_content)
                                        if current_turn == 1 and use_tools:
                                            turn_content_buf.append(emit_content)
                                        else:
                                            yield f"data: {json.dumps({'session_id': sid, 'reasoning_delta': '', 'content_delta': emit_content}, ensure_ascii=False)}\n\n"
                                except Exception:
                                    continue

                    # 冲刷缓冲区中剩余的文本
                    if pending_c_buf:
                        if in_think_mode:
                            full_reasoning.append(pending_c_buf)
                            yield f"data: {json.dumps({'session_id': sid, 'reasoning_delta': pending_c_buf, 'content_delta': ''}, ensure_ascii=False)}\n\n"
                        elif in_tool_mode:
                            text_tool_calls_buf.append(pending_c_buf)
                        else:
                            full_content.append(pending_c_buf)
                            if current_turn == 1 and use_tools:
                                turn_content_buf.append(pending_c_buf)
                            else:
                                yield f"data: {json.dumps({'session_id': sid, 'reasoning_delta': '', 'content_delta': pending_c_buf}, ensure_ascii=False)}\n\n"

                    # 3. 提取所有工具调用（合并原生 tool_calls_buffer 与 XML text_tool_calls_buf）
                    all_tools_to_exec = []
                    if tool_calls_buffer:
                        for idx, tc in sorted(tool_calls_buffer.items()):
                            t_name = tc["name"].strip()
                            t_id = tc["id"]
                            raw_args = tc["arguments"].strip()
                            try:
                                parsed_args = json.loads(raw_args) if raw_args else {}
                            except Exception:
                                parsed_args = {"code": payload.message[:6]}
                            all_tools_to_exec.append({"id": t_id, "name": t_name, "args": parsed_args})

                    if text_tool_calls_buf:
                        full_xml_text = "".join(text_tool_calls_buf)
                        # 解析 <tool_call><function=xxx><parameter=k>v</parameter></function></tool_call>
                        for m in re.finditer(r"<tool_call>[\s\S]*?<function=([a-zA-Z0-9_]+)>([\s\S]*?)</function>[\s\S]*?</tool_call>", full_xml_text):
                            func_name = m.group(1).strip()
                            body_text = m.group(2)
                            parsed_args = {}
                            for p in re.finditer(r"<parameter=([a-zA-Z0-9_]+)>\s*([\s\S]*?)\s*</parameter>", body_text):
                                k = p.group(1).strip()
                                v = p.group(2).strip()
                                parsed_args[k] = int(v) if v.isdigit() else v
                            if not any(t["name"] == func_name for t in all_tools_to_exec):
                                all_tools_to_exec.append({
                                    "id": f"call_xml_{len(all_tools_to_exec)}",
                                    "name": func_name,
                                    "args": parsed_args
                                })

                    if all_tools_to_exec:
                        full_content = []
                        turn_content_buf = []
                        formatted_tool_calls = []
                        round_trails = []

                        # 1. 立即并发下发所有 tool_call SSE 事件，让前端卡片瞬间全量展开进入调度状态
                        for t in all_tools_to_exec:
                            t_name = t["name"]
                            t_id = t["id"]
                            t_args = t["args"]
                            formatted_tool_calls.append({
                                "id": t_id,
                                "type": "function",
                                "function": {
                                    "name": t_name,
                                    "arguments": json.dumps(t_args, ensure_ascii=False),
                                }
                            })
                            yield f"data: {json.dumps({'session_id': sid, 'event': 'tool_call', 'tool': t_name, 'args': t_args, 'tool_id': t_id}, ensure_ascii=False)}\n\n"

                        # 2. 多线程高并发并行执行全部量化工具 (带 6 秒超时防挂死保护)
                        from concurrent.futures import ThreadPoolExecutor, as_completed

                        def _run_single_tool(item):
                            tool_n = item["name"]
                            tool_a = item["args"]
                            tool_i = item["id"]
                            try:
                                res = execute_agent_tool(tool_n, tool_a)
                            except Exception as e:
                                res = {"ok": False, "summary": f"工具异常: {e}", "data": {}}
                            return {
                                "tool_id": tool_i,
                                "tool": tool_n,
                                "args": tool_a,
                                "ok": bool(res.get("ok", True)),
                                "summary": res.get("summary", "工具调用完成"),
                                "data": res.get("data", {}),
                                "status": "done" if bool(res.get("ok", True)) else "error"
                            }

                        num_workers = min(16, len(all_tools_to_exec))
                        tool_results_map = {}

                        with ThreadPoolExecutor(max_workers=num_workers) as executor:
                            future_to_item = {
                                executor.submit(_run_single_tool, item): item
                                for item in all_tools_to_exec
                            }

                            for fut in as_completed(future_to_item):
                                item_meta = future_to_item[fut]
                                try:
                                    res_obj = fut.result(timeout=6.5)
                                except Exception as err:
                                    res_obj = {
                                        "tool_id": item_meta["id"],
                                        "tool": item_meta["name"],
                                        "args": item_meta["args"],
                                        "ok": False,
                                        "status": "error",
                                        "summary": f"工具执行超时或异常: {err}",
                                        "data": {}
                                    }

                                tool_results_map[res_obj["tool_id"]] = res_obj

                                # 一旦某个工具执行完毕，即刻流式推送 tool_result 事件
                                yield f"data: {json.dumps({'session_id': sid, 'event': 'tool_result', 'tool': res_obj['tool'], 'ok': res_obj['ok'], 'status': res_obj['status'], 'summary': res_obj['summary'], 'data': res_obj['data'], 'tool_id': res_obj['tool_id']}, ensure_ascii=False)}\n\n"

                        # 按原调用顺序组装 round_trails 与 tool_trails
                        for t in all_tools_to_exec:
                            r = tool_results_map.get(t["id"]) or {
                                "tool_id": t["id"],
                                "tool": t["name"],
                                "args": t["args"],
                                "ok": True,
                                "status": "done",
                                "summary": "工具执行就绪",
                                "data": {}
                            }
                            round_trails.append(r)
                            tool_trails.append({"tool": r["tool"], "args": r["args"], "ok": r["ok"], "status": r["status"], "summary": r["summary"], "data": r["data"]})

                        # 回填 messages 发起第二轮总结推理
                        messages.append({
                            "role": "assistant",
                            "content": "".join(full_content) or None,
                            "tool_calls": formatted_tool_calls,
                        })

                        for tr in round_trails:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tr["tool_id"],
                                "name": tr["tool"],
                                "content": json.dumps({"summary": tr["summary"], "data": tr["data"]}, ensure_ascii=False),
                            })

                        # 追加明确的研报生成收敛指令
                        messages.append({
                            "role": "user",
                            "content": "【量化系统指令】所有金融工具与 Alpha Zoo 因子数据均已检索就绪，请不要再输出任何工具调用标签。请立刻结合上述所有工具结果、Alpha Zoo 多因子画像（包含综合多头评分及 Top 多空贡献因子）、量价微观特征及均线矩阵，全面输出包含「🔬 Alpha Zoo 多因子量化画像与综合评分」的深度投研诊断研报！"
                        })

                        # 清空当前轮正文缓冲，准备接收第二轮的完整投研研报
                        full_content = []
                        # 进入下一轮推理
                        continue
                    else:
                        if turn_content_buf:
                            flushed_text = "".join(turn_content_buf)
                            yield f"data: {json.dumps({'session_id': sid, 'reasoning_delta': '', 'content_delta': flushed_text}, ensure_ascii=False)}\n\n"
                            turn_content_buf = []
                        break

            except Exception as exc:
                logger.error("Agent LLM Stream inference error: %s", exc)
                err_report = f"\n\n> ⚠️ **量化大模型 Agent 服务调用异常**: `{exc}`\n\n请检查大模型网关连接或稍后点击重试。"
                full_content.append(err_report)
                yield f"data: {json.dumps({'session_id': sid, 'reasoning_delta': '', 'content_delta': err_report}, ensure_ascii=False)}\n\n"

            # 流结束时保存完整助理回答到 session store (过滤 think 标签)
            raw_reply = "".join(full_content) or "".join(full_reasoning) or "量化投研诊断完成。"
            clean_reply = re.sub(r"<think>[\s\S]*?</think>", "", raw_reply, flags=re.IGNORECASE).strip()
            clean_reply = re.sub(r"</?think>", "", clean_reply, flags=re.IGNORECASE).strip() or raw_reply

            if sid and svc:
                try:
                    assistant_msg = Message(
                        message_id=f"msg_{int(datetime.now(timezone.utc).timestamp()*1000)}_asst",
                        session_id=sid,
                        role="assistant",
                        content=clean_reply,
                        created_at=datetime.now(timezone.utc).isoformat(),
                        tool_trail=tool_trails,
                    )
                    svc.store.append_message(assistant_msg)
                except Exception as e:
                    logger.warning("Failed to store assistant message: %s", e)

            yield "data: [DONE]\n\n"

        return StreamingResponse(
            stream_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )

    @app.post("/chat", dependencies=[Depends(require_auth)])
    async def chat_endpoint(payload: QuickChatRequest):
        return await _handle_quick_chat(payload)

    @app.post("/api/ashare/analyze", dependencies=[Depends(require_auth)])
    async def ashare_analyze_endpoint(payload: QuickChatRequest):
        return await _handle_quick_chat(payload)

    @app.post("/api/ashare/export-docx", dependencies=[Depends(require_auth)])
    async def ashare_export_docx_endpoint(payload: AshareExportDocxRequest = Body(...)):
        from .ashare_docx_exporter import build_ashare_docx
        from fastapi.responses import Response
        import urllib.parse
        
        docx_buf = build_ashare_docx(
            code=payload.code,
            name=payload.name,
            date_str=payload.date,
            markdown_content=payload.content,
            stats=payload.stats
        )
        
        clean_name = re.sub(r"[\s\*\/\\]+", "_", payload.name)
        filename = f"【AI量化研报】{payload.code}_{clean_name}_{payload.date}.docx"
        encoded_filename = urllib.parse.quote(filename)
        
        return Response(
            content=docx_buf.getvalue(),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="{encoded_filename}"; filename*=UTF-8\'\'{encoded_filename}',
                "Access-Control-Allow-Origin": "*",
            }
        )



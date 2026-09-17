from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from pydantic import BaseModel, Field

from app.auth import decode_access_token, issue_access_token, verify_password
from app.config import database_url, langgraph_database_url
from app.db import build_session_factory
from app.models import ApprovalStatus, RequestType, User, UserRole
from app.repositories import SessionFactory
from app.runtime import AppRuntime, build_runtime
from app.vector_rag import VectorPolicyKnowledgeBase


class CreateCaseInput(BaseModel):
    customer_id: str = Field(min_length=1, max_length=64)
    order_id: str = Field(min_length=1, max_length=64)
    request_type: RequestType
    summary: str = Field(min_length=1, max_length=2000)
    submitted_on: date = Field(default_factory=date.today)
    case_id: str | None = Field(default=None, min_length=1, max_length=64)


class ApprovalInput(BaseModel):
    status: ApprovalStatus
    note: str = Field(default="", max_length=2000)


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


def create_app(
    *,
    session_factory: SessionFactory | None = None,
    checkpointer: Any | None = None,
) -> FastAPI:
    if (session_factory is None) != (checkpointer is None):
        raise ValueError("session_factory and checkpointer must be supplied together")

    if session_factory is None:
        app = FastAPI(title="Auditable Business Agent", lifespan=_production_lifespan)
    else:
        app = FastAPI(title="Auditable Business Agent")
        app.state.runtime = build_runtime(session_factory, checkpointer)

    bearer = HTTPBearer(auto_error=False)
    app.mount(
        "/ui",
        StaticFiles(directory=Path(__file__).parent.parent / "frontend" / "dist", html=True),
        name="ui",
    )

    def current_user(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> User:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
        try:
            username, claimed_role = decode_access_token(credentials.credentials)
        except Exception as error:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token") from error
        user = _runtime(request.app).user_repository.get_by_username(username)
        if user is None or user.role is not claimed_role:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token")
        return user

    def require_roles(*roles: UserRole):
        def dependency(user: User = Depends(current_user)) -> User:
            if user.role not in roles:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
            return user

        return dependency

    @app.post("/auth/login")
    def login(payload: LoginInput) -> dict[str, str]:
        user = _runtime(app).user_repository.get_by_username(payload.username)
        if user is None or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
        return {"access_token": issue_access_token(user), "token_type": "bearer"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse(url="/ui/")

    @app.post("/cases")
    def create_case(
        payload: CreateCaseInput,
        response: Response,
        _: User = Depends(require_roles(UserRole.CUSTOMER_SERVICE, UserRole.APPROVER)),
    ) -> dict[str, Any]:
        case_id = payload.case_id or f"CASE-{uuid4()}"
        if payload.case_id and _runtime(app).case_store.get(case_id) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Case ID already exists")
        request_id = f"REQ-{uuid4()}"
        state = {
            "case_id": case_id,
            "customer_id": payload.customer_id,
            "order_id": payload.order_id,
            "request_type": payload.request_type.value,
            "summary": payload.summary,
            "submitted_on": payload.submitted_on.isoformat(),
            "assessment_on": date.today().isoformat(),
            "request_id": request_id,
        }
        result = _runtime(app).workflow.invoke(state, config=_config(case_id))
        body = _workflow_response(result)
        if body["status"] == "pending_approval":
            response.status_code = status.HTTP_202_ACCEPTED
        else:
            response.status_code = status.HTTP_201_CREATED
        return body

    @app.post("/cases/{case_id}/approval")
    def submit_approval(
        case_id: str,
        payload: ApprovalInput,
        approver: User = Depends(require_roles(UserRole.APPROVER)),
    ) -> dict[str, Any]:
        if _runtime(app).case_store.get(case_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
        if not _runtime(app).workflow.get_state(_config(case_id)).next:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Case is not awaiting approval")
        result = _runtime(app).workflow.invoke(
            Command(
                resume={
                    "approver_id": approver.username,
                    "status": payload.status.value,
                    "note": payload.note,
                    "decided_at": datetime.now(timezone.utc).isoformat(),
                }
            ),
            config=_config(case_id),
        )
        return _workflow_response(result)

    @app.get("/cases/{case_id}")
    def get_case(
        case_id: str,
        _: User = Depends(require_roles(UserRole.CUSTOMER_SERVICE, UserRole.APPROVER)),
    ) -> dict[str, Any]:
        case = _runtime(app).case_store.get(case_id)
        if case is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
        return {
            "case": {
                "case_id": case.case_id,
                "customer_id": case.customer_id,
                "order_id": case.order_id,
                "request_type": case.request_type.value,
                "summary": case.summary,
                "submitted_on": case.submitted_on.isoformat(),
            },
            "audit_events": _audit_events(case_id, app),
        }

    @app.get("/cases/{case_id}/audit")
    def get_audit(
        case_id: str,
        _: User = Depends(require_roles(UserRole.CUSTOMER_SERVICE, UserRole.APPROVER)),
    ) -> list[dict[str, Any]]:
        if _runtime(app).case_store.get(case_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
        return _audit_events(case_id, app)

    return app


@asynccontextmanager
async def _production_lifespan(app: FastAPI):
    with PostgresSaver.from_conn_string(langgraph_database_url()) as checkpointer:
        checkpointer.setup()
        knowledge_base = VectorPolicyKnowledgeBase.from_database(
            connection=database_url(),
            documents_directory=_policy_documents_directory(),
        )
        app.state.runtime = build_runtime(build_session_factory(), checkpointer, knowledge_base=knowledge_base)
        yield


def _runtime(app: FastAPI) -> AppRuntime:
    return app.state.runtime


def _config(case_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": case_id}}


def _workflow_response(result: dict[str, Any]) -> dict[str, Any]:
    interrupts = result.get("__interrupt__")
    if interrupts:
        details = interrupts[0].value
        return {"case_id": details["case_id"], "status": "pending_approval", "approval": details}
    return {
        "case_id": result["case_id"],
        "status": result["status"],
        "decision": {
            "action": result["action"],
            "reason": result["reason"],
            "rule_id": result["rule_id"],
            "requires_approval": result["requires_approval"],
        },
        "ticket_id": result.get("ticket_id"),
    }


def _audit_events(case_id: str, app: FastAPI) -> list[dict[str, Any]]:
    return [
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "actor_type": event.actor_type,
            "actor_id": event.actor_id,
            "payload": dict(event.payload),
            "occurred_at": event.occurred_at.isoformat(),
            "request_id": event.request_id,
        }
        for event in _runtime(app).audit_log.events_for_case(case_id)
    ]


def _policy_documents_directory():
    return Path(__file__).parent.parent / "sample_data" / "policies"


app = create_app()

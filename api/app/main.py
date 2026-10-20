import logging
import secrets

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, EmailStr, Field

from .agent import route_message
from .config import settings
from .departments import config as departments
from .mailer import send_department_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(
    title="AI Mail Router",
    description=(
        "Accepts a free-text employee message, uses an LLM (local Ollama by "
        "default) acting as a tool-using AI agent to decide which department "
        "should handle it, and forwards the message there by email. "
        "Departments are configured in departments.yaml."
    ),
    version="1.1.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
)


_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """Enforced only when API_KEY is set, so local demos keep working without it."""
    if settings.api_key and not (key and secrets.compare_digest(key, settings.api_key)):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key header")


class RouteRequest(BaseModel):
    email: EmailStr = Field(..., description="Sender's email address")
    message: str = Field(..., min_length=1, description="Free-text message content")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"email": "jan.nowak@example.com", "message": "Nie dziala mi komputer"},
                {"email": "jan.nowak@example.com", "message": "Chcialbym zglosic urlop na jutro"},
            ]
        }
    }


class RouteResponse(BaseModel):
    routed_to: str
    subject: str


class DepartmentOut(BaseModel):
    email: str
    name: str
    description: str


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get(
    "/api/v1/departments",
    response_model=list[DepartmentOut],
    tags=["routing"],
    dependencies=[Depends(require_api_key)],
)
def list_departments() -> list[DepartmentOut]:
    return [DepartmentOut(**vars(d)) for d in departments.departments]


@app.post(
    "/api/v1/route",
    response_model=RouteResponse,
    tags=["routing"],
    dependencies=[Depends(require_api_key)],
)
def route(payload: RouteRequest) -> RouteResponse:
    try:
        decision = route_message(payload.message)
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Agent failed to produce a routing decision")
        raise HTTPException(status_code=502, detail="AI agent failed to process the message") from exc

    try:
        send_department_email(
            to=decision.to,
            subject=decision.subject,
            body=decision.body,
            reply_to=payload.email,
        )
    except Exception as exc:
        logger.exception("Failed to send routed email")
        raise HTTPException(status_code=502, detail="Failed to deliver the routed email") from exc

    logger.info("Routed message from %s to %s", payload.email, decision.to)
    return RouteResponse(routed_to=decision.to, subject=decision.subject)

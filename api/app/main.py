import logging

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr, Field

from .agent import route_message
from .mailer import send_department_email

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api")

app = FastAPI(
    title="AI Message Router -- PoC",
    description=(
        "Accepts a free-text employee message, uses a local LLM (via Ollama) "
        "acting as a tool-using AI agent to decide which department should "
        "handle it, and forwards the message there by email."
    ),
    version="1.0.0",
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
)


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


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.post("/api/v1/route", response_model=RouteResponse, tags=["routing"])
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

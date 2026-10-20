"""
The AI Agent: decides which department a message belongs to by calling the
`send_email` tool via an LLM (local Ollama by default, or any OpenAI-compatible API).

The list of departments comes from departments.yaml, so the tool schema and the
system prompt are generated from it at startup.

Design decision: the LLM's tool call carries the routing decision (`to`,
`subject`, `body`), but the *actual* sending — including the security-relevant
`Reply-To` header — is done deterministically in mailer.py from data the
caller already gave us. The model is never trusted with the sender's email
address for the Reply-To header; it only decides where the message goes and
how to phrase it.
"""

import json
import logging

from openai import OpenAI, APIStatusError
from pydantic import BaseModel

from .config import settings
from .departments import config as departments

logger = logging.getLogger("agent")

def _build_tool(emails: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": (
                "Forward the employee's request to the correct internal department by "
                "email. Must be called exactly once per incoming message."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "enum": emails,
                        "description": "The single best-matching department address for this request.",
                    },
                    "subject": {
                        "type": "string",
                        "description": "Short subject line summarizing the request.",
                    },
                    "body": {
                        "type": "string",
                        "description": "The message to forward to the department (may quote/paraphrase the original).",
                    },
                },
                "required": ["to", "subject", "body"],
            },
        },
    }


def _build_system_prompt() -> str:
    guide = "\n".join(
        f"- {d.email} ({d.name}): {d.description}" for d in departments.departments
    )
    return f"""You are an AI routing agent for an internal company ticketing system.
You receive a short free-text message written by an employee and must decide which
department should handle it, then forward it by calling the `send_email` tool.

Department guide:
{guide}

Fallback: if the message has nothing to do with the company, is small talk / a greeting /
a thank-you with no actual request, is unintelligible, or matches none of the departments
well, send it to {departments.fallback}. No department is a catch-all except the fallback.

Rules:
- You MUST call `send_email` exactly once. Never answer in plain text.
- Pick exactly one `to` address -- the single best match.
- Write `subject` and `body` in the same language as the original message.
"""


SEND_EMAIL_TOOL = _build_tool(departments.emails)
SYSTEM_PROMPT = _build_system_prompt()


class RoutingDecision(BaseModel):
    to: str
    subject: str
    body: str


_client = OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)


def _call_model(message: str, tool_choice):
    return _client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        tools=[SEND_EMAIL_TOOL],
        tool_choice=tool_choice,
    )


def _extract_decision(response) -> RoutingDecision | None:
    message = response.choices[0].message
    tool_calls = getattr(message, "tool_calls", None) or []
    for call in tool_calls:
        if call.function.name != "send_email":
            continue
        try:
            args = json.loads(call.function.arguments)
        except json.JSONDecodeError:
            logger.warning("Model returned non-JSON tool arguments: %r", call.function.arguments)
            continue
        if args.get("to") in departments.emails and args.get("subject") and args.get("body"):
            return RoutingDecision(**args)
        logger.warning("Model returned an invalid send_email payload: %r", args)
    return None


def route_message(message: str) -> RoutingDecision:
    """Ask the agent to classify+route `message`. Always returns a decision --
    falls back to the configured fallback department if the model misbehaves
    after a few tries."""

    for tool_choice in ("required", "auto", "auto"):
        try:
            response = _call_model(message, tool_choice)
        except APIStatusError as exc:
            logger.warning("LLM rejected tool_choice=%r (%s), retrying", tool_choice, exc)
            continue
        except Exception:
            logger.exception("Call to the LLM failed, retrying")
            continue

        decision = _extract_decision(response)
        if decision is not None:
            return decision
        logger.warning("Model did not return a valid send_email tool call, retrying")

    logger.error("Agent failed to produce a valid routing decision, falling back to %s", departments.fallback)
    return RoutingDecision(
        to=departments.fallback,
        subject="Unclassified message",
        body=message,
    )

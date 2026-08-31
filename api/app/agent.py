"""
The AI Agent: decides which department a message belongs to by calling the
`send_email` tool via an LLM served locally through Ollama.

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

logger = logging.getLogger("agent")

DEPARTMENTS = [
    "human-resources@example.com",
    "help-desk@example.com",
    "it@example.com",
    "kadry@example.com",
    "other@example.com",
]

SEND_EMAIL_TOOL = {
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
                    "enum": DEPARTMENTS,
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

SYSTEM_PROMPT = """You are an AI routing agent for an internal company ticketing system.
You receive a short free-text message written by an employee (often in Polish) and must
decide which department should handle it, then forward it by calling the `send_email` tool.

Department guide:
- it@example.com: technical / hardware / software / computer / network problems,
  including security incidents (e.g. phishing).
- help-desk@example.com: concrete, actionable internal support requests that are not a
  clear IT failure -- physical equipment requests (new mouse, headset, laptop), access/
  permission requests to internal systems, or "how do I use tool X" questions.
- human-resources@example.com: general HR matters -- contracts, onboarding, workplace
  conduct/conflict, benefits (e.g. multisport-style cards), insurance, training,
  recruitment, performance-review scheduling. Benefits and training ALWAYS go here,
  never to help-desk.
- kadry@example.com: Polish payroll / leave / absence administration -- "urlop",
  "zwolnienie lekarskie", "L4", "wyplata", "pasek wynagrodzen" and similar. Does not
  include general expense reimbursement (e.g. travel/delegacja costs) -- that is not
  clearly covered by any department, so it falls back to other@example.com.
- other@example.com: fallback. Use it whenever the message (a) has nothing to do with
  the company or its internal departments (e.g. asking where the nearest ATM is), (b)
  is small talk / a greeting / a thank-you with no actual request, (c) is unintelligible,
  or (d) matches none of the departments above well. help-desk@example.com is NOT a
  catch-all -- do not route to it just because a message sounds vaguely like a
  request; if there is no real internal-support action to take, use other@example.com
  instead.

Rules:
- You MUST call `send_email` exactly once. Never answer in plain text.
- Pick exactly one `to` address -- the single best match.
- Write `subject` and `body` in the same language as the original message.
"""


class RoutingDecision(BaseModel):
    to: str
    subject: str
    body: str


_client = OpenAI(base_url=settings.ollama_base_url, api_key="ollama")


def _call_model(message: str, tool_choice):
    return _client.chat.completions.create(
        model=settings.ollama_model,
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
        if args.get("to") in DEPARTMENTS and args.get("subject") and args.get("body"):
            return RoutingDecision(**args)
        logger.warning("Model returned an invalid send_email payload: %r", args)
    return None


def route_message(message: str) -> RoutingDecision:
    """Ask the agent to classify+route `message`. Always returns a decision --
    falls back to other@example.com if the model misbehaves after a few tries."""

    for tool_choice in ("required", "auto", "auto"):
        try:
            response = _call_model(message, tool_choice)
        except APIStatusError as exc:
            logger.warning("Ollama rejected tool_choice=%r (%s), retrying", tool_choice, exc)
            continue
        except Exception:
            logger.exception("Call to the local LLM failed, retrying")
            continue

        decision = _extract_decision(response)
        if decision is not None:
            return decision
        logger.warning("Model did not return a valid send_email tool call, retrying")

    logger.error("Agent failed to produce a valid routing decision, falling back to other@example.com")
    return RoutingDecision(
        to="other@example.com",
        subject="Unclassified message",
        body=message,
    )

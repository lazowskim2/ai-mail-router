"""End-to-end tests of the HTTP API against a fake OpenAI-compatible LLM server.

No real model or mail server is needed: the fake server answers with a
`send_email` tool call, and email sending is captured in memory.
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


class FakeLLM(BaseHTTPRequestHandler):
    """Routes anything mentioning "laptop" to IT, everything else to an invalid address."""

    last_request: dict = {}

    def log_message(self, *args):
        pass

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLLM.last_request = request
        message = request["messages"][1]["content"]
        to = "it@example.com" if "laptop" in message else "not-a-department@evil.com"
        arguments = json.dumps({"to": to, "subject": "Laptop", "body": message})
        body = json.dumps({
            "id": "1", "object": "chat.completion", "created": 0, "model": "fake",
            "choices": [{
                "index": 0, "finish_reason": "tool_calls",
                "message": {"role": "assistant", "content": None, "tool_calls": [{
                    "id": "call_1", "type": "function",
                    "function": {"name": "send_email", "arguments": arguments},
                }]},
            }],
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


_server = HTTPServer(("127.0.0.1", 0), FakeLLM)
threading.Thread(target=_server.serve_forever, daemon=True).start()

os.environ.update(
    LLM_BASE_URL=f"http://127.0.0.1:{_server.server_port}/v1",
    API_KEY="test-key",
    DEPARTMENTS_FILE=str(ROOT / "departments.yaml"),
)
sys.path.insert(0, str(ROOT / "api"))

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main  # noqa: E402
from app.departments import load_departments  # noqa: E402

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture
def sent(monkeypatch):
    outbox = []
    monkeypatch.setattr(main, "send_department_email", lambda **kw: outbox.append(kw))
    return outbox


client = TestClient(main.app)


def test_requires_api_key(sent):
    response = client.post("/api/v1/route", json={"email": "john@example.com", "message": "laptop"})
    assert response.status_code == 401
    assert sent == []


def test_routes_to_department_with_sender_as_reply_to(sent):
    response = client.post(
        "/api/v1/route",
        json={"email": "john@example.com", "message": "My laptop won't turn on"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["routed_to"] == "it@example.com"
    assert sent[-1]["to"] == "it@example.com"
    assert sent[-1]["reply_to"] == "john@example.com"


def test_invalid_model_answer_goes_to_fallback(sent):
    response = client.post(
        "/api/v1/route",
        json={"email": "john@example.com", "message": "hello there"},
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.json()["routed_to"] == "other@example.com"
    assert sent[-1]["to"] == "other@example.com"


def test_model_can_only_choose_configured_addresses(sent):
    client.post("/api/v1/route", json={"email": "john@example.com", "message": "laptop"}, headers=HEADERS)
    tool = FakeLLM.last_request["tools"][0]["function"]
    allowed = tool["parameters"]["properties"]["to"]["enum"]
    assert allowed == load_departments(ROOT / "departments.yaml").emails


def test_lists_departments():
    response = client.get("/api/v1/departments", headers=HEADERS)
    assert response.status_code == 200
    assert {d["email"] for d in response.json()} >= {"it@example.com", "other@example.com"}


@pytest.mark.parametrize("path", ["departments.yaml", "examples/departments.pl.yaml"])
def test_shipped_configs_are_valid(path):
    config = load_departments(ROOT / path)
    assert config.fallback in config.emails

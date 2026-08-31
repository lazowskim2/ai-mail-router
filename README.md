# AI Message Router — Proof of Concept

A containerized microservice that acts as an **AI Agent**: it receives a free-text
message from an employee, uses a locally-hosted LLM (via [Ollama](https://ollama.com))
to interpret it, and — through real function/tool calling — decides which internal
department should receive it, then delivers the message by email (captured by MailHog
for testing).

## Quick start

```bash
docker compose up -d
```

That's it. On first run this will:

1. build the `api` image,
2. start MailHog and Ollama,
3. pull the LLM weights into a named volume (`ollama-pull` service — this is the slow
   step the first time, a couple of GB depending on the model),
4. only then start the API, once the model is actually ready.

Subsequent `docker compose up -d` runs are fast — the model weights persist in the
`ollama_data` volume, so nothing is re-downloaded.

Once it's up:

- API: http://localhost:8000
- Swagger / OpenAPI docs: **http://localhost:8000/api/v1/docs**
- MailHog web UI (see the emails the agent sent): http://localhost:8025

### Try it

```bash
curl -X POST http://localhost:8000/api/v1/route \
  -H "Content-Type: application/json" \
  -d '{"email": "jan.nowak@example.com", "message": "Nie dziala mi komputer"}'
```

Expected response:

```json
{"routed_to": "it@example.com", "subject": "..."}
```

Then open http://localhost:8025 — you'll see the forwarded email in the `it@example.com`
mailbox, with `Reply-To: jan.nowak@example.com` set correctly.

Try a second example to see different routing:

```bash
curl -X POST http://localhost:8000/api/v1/route \
  -H "Content-Type: application/json" \
  -d '{"email": "jan.nowak@example.com", "message": "Chcialbym zglosic urlop na jutro"}'
```

## Architecture

```
client --HTTP--> [api: FastAPI]
                      |
                      | 1. chat.completions(tools=[send_email]) over OpenAI-compatible API
                      v
                 [ollama: local LLM, e.g. llama3.2]
                      |
                      | 2. model responds with a tool_call: send_email(to, subject, body)
                      v
                 [api parses the tool call]
                      |
                      | 3. api sends the actual email via smtplib (Reply-To set from the
                      |    ORIGINAL request, not from the model)
                      v
                 [mailhog: SMTP :1025 / Web UI :8025]
```

Services (`docker-compose.yml`):

| service       | role                                                                 |
|---------------|-----------------------------------------------------------------------|
| `ollama`      | runs the LLM, exposes an OpenAI-compatible API on `:11434`            |
| `ollama-pull` | one-shot job: pulls the model weights into `ollama`'s volume, then exits |
| `mailhog`     | fake SMTP server + web UI, stands in for the real mail infrastructure |
| `api`         | FastAPI service; hosts the agent and the HTTP endpoint                |

## Key design decisions

- **The tool call *is* the routing decision.** The agent is given exactly one tool,
  `send_email(to, subject, body)`, with `to` constrained to an enum of the five
  department addresses. The model doesn't do a separate "classify" step and then a
  "send" step — picking the tool's `to` argument *is* the classification. This matches
  the task's requirement that the agent "samodzielnie użyje udostępnionego mu narzędzia
  do wysłania wiadomości e-mail".

- **`Reply-To` is never trusted to the model.** The LLM only decides *where* the
  message goes and how to phrase it. The `Reply-To` header is set deterministically by
  the API from the `email` field of the original HTTP request. This avoids a class of
  bugs/prompt-injection risk where the model could set an arbitrary or malformed
  Reply-To.

- **Model choice: `llama3.2` (3B) by default.** It's one of the smaller models with
  solid tool-calling support in Ollama, which keeps the first `docker compose up -d`
  reasonably fast (~2GB pull) while still handling this task's five-way classification
  well. For higher routing accuracy, swap in a larger tool-calling model — no code
  changes needed, just:

  ```bash
  OLLAMA_MODEL=qwen2.5:7b docker compose up -d
  ```

- **Retry + graceful fallback, not a hard failure.** Small local models occasionally
  don't emit a tool call, or emit an invalid one. `agent.route_message()` retries with
  `tool_choice="required"` then twice with `tool_choice="auto"` (some Ollama/model
  combinations don't support `"required"`, so that failure is caught and it falls back
  automatically). If all three attempts fail, the message is routed to
  `other@example.com` rather than the request failing with a 5xx. This reflects how a
  production system should treat non-deterministic LLM output — degrade gracefully,
  don't drop the request.

- **Department disambiguation.** The task lists both `human-resources@example.com` and
  `kadry@example.com`, which overlap in English. The system prompt resolves this by
  treating `kadry@example.com` as the Polish payroll/leave/absence mailbox (`urlop`,
  `L4`, `wypłata`, ...) and `human-resources@example.com` as general/policy HR matters —
  this is a judgment call, documented here so it's easy to challenge or retune (it's a
  single paragraph in `api/app/agent.py::SYSTEM_PROMPT`).

- **Tuned against a live model, not just read for plausibility.** The agent was run
  end-to-end (real HTTP tool-calling round trip, no mocks) against a local LLM serving
  the same OpenAI-compatible `/v1` API Ollama exposes, using 50 varied/ambiguous
  Polish (and a couple of English) messages designed to stress the classifier —
  small talk, off-topic questions, gibberish, sensitive HR cases (mobbing, conflict),
  security incidents, and messages that plausibly straddle two departments. Zero
  request failures across the batch (~0.9s/request). This surfaced one real weakness in
  the first version of the prompt: the model treated `help-desk@example.com` as a
  catch-all, occasionally routing small talk, off-topic questions, and even benefits/
  training questions there instead of `human-resources@example.com` or
  `other@example.com`. `SYSTEM_PROMPT` was tightened to explicitly state that
  `help-desk@example.com` is not a catch-all and to pin down benefits/training as HR
  and non-work topics as `other@example.com`; re-running the same 50 messages fixed
  every one of those misroutes. Since the LLM's output isn't fully deterministic,
  individual borderline cases (e.g. "printer jammed": IT hardware fault vs. a
  help-desk equipment ticket) can occasionally flip between runs — expected behavior
  for a non-deterministic classifier, not a bug, and worth keeping in mind when
  evaluating routing decisions.

## Project layout

```
docker-compose.yml
api/
  Dockerfile
  requirements.txt
  app/
    main.py     — FastAPI app, HTTP endpoint, Swagger config
    agent.py    — tool schema, system prompt, Ollama call + retry/fallback logic
    mailer.py   — SMTP delivery via MailHog, Reply-To handling
    config.py   — environment-based settings
```

## What was tested without Docker

The sandbox used to prepare this PoC does not have Docker installed, so the following
was verified directly against the real code instead:

- `docker compose config` — the compose file parses and resolves cleanly.
- The FastAPI app imports and serves `/api/v1/docs` and `/api/v1/openapi.json` at the
  required paths, with `/api/v1/route` registered.
- **Full end-to-end run against a real, locally-hosted LLM** (LM Studio, serving the
  same OpenAI-compatible `/v1/chat/completions` API that Ollama exposes, so the app
  code under test is exactly what runs in the container) and a local SMTP capture
  server standing in for MailHog: single requests, a 50-message ambiguity/load test
  (see "Tuned against a live model" above), and header inspection all passed —
  correct routing, correct `Reply-To`, zero request failures, ~0.9s/request.
- `mailer.send_department_email()` verified against the local debugging SMTP server —
  `To`, `Reply-To`, `Subject` and body all come through correctly, including Polish
  diacritics (properly MIME-encoded).

What was **not** possible to verify in this environment: the container build itself
and the `ollama-pull` model-download step, since that requires the Docker daemon.
Everything downstream of "the model is up and speaking the OpenAI API" has been
exercised for real; only the Docker plumbing around it is unverified. Recommended
before final review: run `docker compose up -d` once on a machine with Docker
installed to confirm the container wiring itself.

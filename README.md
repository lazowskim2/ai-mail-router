# AI Mail Router

**English** | [Polski](README.pl.md)

**An AI message router for companies.** Employees write in plain language ("my laptop won't turn on", "I'd like to take Friday off"). The AI decides which department should handle it and forwards the message there by email. The department's reply goes straight back to the employee.

- 🏢 **Departments live in one YAML file.** No code changes needed.
- 🔒 **Runs 100% locally by default** (Ollama + MailHog test inbox). No data leaves your company.
- 🔌 **Any AI model**: Ollama, OpenAI, Groq, OpenRouter, LM Studio, or anything else with an OpenAI-compatible API.
- 📬 **Real email**: Gmail, Microsoft 365 or any SMTP server.
- 🛡️ **Resilient to model mistakes.** If the AI gets it wrong, the message goes to a fallback department and nothing is lost.
- 🌍 **Multilingual.** It understands messages in any language the model speaks and replies in the same language. Tested in English and Polish.
- 🧩 **Simple REST API** with Swagger. Easy to plug into a web form, an intranet, a Slack bot or your own app.

**MIT licensed**: use it, modify it and deploy it commercially, including for clients.

---

## Quick start (2 minutes)

All you need is [Docker](https://docs.docker.com/get-docker/).

```bash
git clone https://github.com/lazowskim2/ai-mail-router.git
cd ai-mail-router
docker compose up -d
```

On the first run Docker downloads the AI model (~2 GB). Later starts are fast. Once it's up:

| What | Where |
|---|---|
| API docs (Swagger) | http://localhost:8000/api/v1/docs |
| Test inbox (preview of sent emails) | http://localhost:8025 |

Send a test message:

```bash
curl -X POST http://localhost:8000/api/v1/route \
  -H "Content-Type: application/json" \
  -d '{"email": "john.smith@example.com", "message": "My computer won'\''t start"}'
```

```json
{"routed_to": "it@example.com", "subject": "Computer won't start"}
```

At http://localhost:8025 you'll see the email in the `it@example.com` inbox with a `Reply-To: john.smith@example.com` header, so IT replies directly to the employee.

---

## Make it yours

### 1. Departments: `departments.yaml`

```yaml
fallback: office@yourcompany.com

departments:
  - email: it@yourcompany.com
    name: IT
    description: >
      Broken computers, printers, network, passwords, suspicious emails (phishing).

  - email: accounting@yourcompany.com
    name: Accounting
    description: >
      Invoices, expense reimbursement, business travel. NOT salaries (that's payroll).

  - email: office@yourcompany.com
    name: Office
    description: >
      Anything that doesn't fit another department.
```

You can have as many departments as you like. **The `description` field matters most**: say what belongs in the department and what does *not*. Routing accuracy depends on it. A ready-made Polish config is in [`examples/departments.pl.yaml`](examples/departments.pl.yaml). After editing, run:

```bash
docker compose restart api
```

### 2. Email, AI model and security: `.env`

```bash
cp .env.example .env
```

Example with real email (Microsoft 365) and a cloud model:

```env
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USER=router@yourcompany.com
SMTP_PASSWORD=...
SMTP_FROM=router@yourcompany.com

LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...

API_KEY=a-long-random-key
```

When `API_KEY` is set, every request must include an `X-API-Key` header. All options are documented in [`.env.example`](.env.example).

> 💡 Want a more accurate local model? Set `LLM_MODEL=qwen2.5:7b` and Ollama will pull it on startup.

---

## API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/route` | Takes `{email, message}`, picks a department and sends the email |
| `GET` | `/api/v1/departments` | Lists configured departments (e.g. for an intranet form) |
| `GET` | `/health` | Health check |

---

## How it works

```
web form / app / bot
          │  POST /api/v1/route
          ▼
   [API: FastAPI] ── departments.yaml ──► prompt + list of allowed addresses
          │
          │ 1. the model gets a single tool: send_email(to, subject, body)
          ▼
   [AI model: Ollama / OpenAI / ...]
          │
          │ 2. the model calls the tool and picks a department (to = routing decision)
          ▼
   [API validates the decision]  ── bad address / no answer ──► retry ──► fallback department
          │
          │ 3. API sends the email over SMTP, Reply-To = sender from the request
          ▼
   [department inbox]
```

### Design decisions

- **The tool call is the routing decision.** The model doesn't classify and send in separate steps. It gets one tool, `send_email`, whose `to` field is restricted to the addresses in `departments.yaml`. It cannot send email outside that list.
- **Reply-To never comes from the model.** The API sets the header from the `email` field of the request. This blocks prompt injection: no one can talk the model into sending replies to a foreign address.
- **Graceful degradation instead of errors.** Small local models sometimes skip the tool call or return a wrong address. The router tries 3 times (first with `tool_choice="required"`, then `"auto"`), and if that fails it sends the message to the fallback department. No request is lost.
- **Tested against a live model.** The default setup was run against 50 varied, sometimes tricky messages in Polish and English: small talk, gibberish, harassment reports, phishing, cases on the border of two departments. Zero failed requests, ~0.9 s per message on average. Borderline cases (e.g. "printer jammed": IT or help desk?) can occasionally go either way, since this is an AI classifier. The fix is a sharper `description`.

---

## Project structure

```
departments.yaml      - departments (edit for your company)
examples/             - ready-made configs (e.g. Polish)
.env.example          - email, model and API key settings
docker-compose.yml
api/app/
  main.py             - HTTP endpoints, Swagger, API key
  agent.py            - prompt and tool built from departments.yaml, retry/fallback
  departments.py      - loads and validates departments.yaml
  mailer.py           - SMTP sending (plain / STARTTLS / SSL), Reply-To
  config.py           - settings from environment variables
```

---

## License

[MIT](LICENSE) © AImployee ([aimployee.pl](https://aimployee.pl))

Need a deployment in your company, a helpdesk integration, or a version that reads a shared mailbox? Get in touch: [aimployee.pl](https://aimployee.pl)

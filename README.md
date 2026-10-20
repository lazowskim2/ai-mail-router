# AI Mail Router

**Inteligentny router wiadomości dla firm.** Pracownik pisze zwykłym językiem („nie działa mi komputer”, „chcę zgłosić urlop na piątek”), a AI samo decyduje, który dział ma się tym zająć, i przekazuje mu wiadomość mailem. Odpowiedź od działu trafia prosto do nadawcy.

- 🏢 **Działy konfigurujesz w jednym pliku YAML.** Nie trzeba ruszać kodu.
- 🔒 **Domyślnie działa w 100% lokalnie** (Ollama + testowa skrzynka MailHog). Żadne dane nie wychodzą z firmy.
- 🔌 **Dowolny model AI**: Ollama, OpenAI, Groq, OpenRouter, LM Studio, czyli wszystko, co ma API zgodne z OpenAI.
- 📬 **Prawdziwa poczta**: Gmail, Microsoft 365 albo dowolny serwer SMTP.
- 🛡️ **Odporny na błędy modelu.** Jeśli AI się pomyli, wiadomość trafia do działu awaryjnego i nic nie ginie.
- 🧩 **Proste REST API** ze Swaggerem. Łatwo podpiąć formularz, intranet, bota na Slacku czy własną aplikację.

Licencja **MIT**: możesz używać, zmieniać i wdrażać komercyjnie, także u klientów.

---

## Szybki start (2 minuty)

Wymagany jest tylko [Docker](https://docs.docker.com/get-docker/).

```bash
git clone https://github.com/lazowskim2/wskz-poc.git ai-mail-router
cd ai-mail-router
docker compose up -d
```

Za pierwszym razem Docker pobierze model AI (~2 GB), a kolejne starty są szybkie. Po uruchomieniu masz:

| Co | Gdzie |
|---|---|
| Dokumentacja API (Swagger) | http://localhost:8000/api/v1/docs |
| Testowa skrzynka (podgląd wysłanych maili) | http://localhost:8025 |

Wyślij testową wiadomość:

```bash
curl -X POST http://localhost:8000/api/v1/route \
  -H "Content-Type: application/json" \
  -d '{"email": "jan.nowak@example.com", "message": "Nie działa mi komputer"}'
```

```json
{"routed_to": "it@example.com", "subject": "Awaria komputera"}
```

Na http://localhost:8025 zobaczysz maila w skrzynce `it@example.com` z nagłówkiem `Reply-To: jan.nowak@example.com`, więc dział IT odpowiada bezpośrednio pracownikowi.

---

## Dopasowanie do Twojej firmy

### 1. Działy: `departments.yaml`

```yaml
fallback: biuro@twojafirma.pl

departments:
  - email: it@twojafirma.pl
    name: IT
    description: >
      Awarie komputerów, drukarek, sieci, hasła, podejrzane maile (phishing).

  - email: ksiegowosc@twojafirma.pl
    name: Księgowość
    description: >
      Faktury, zwroty kosztów, delegacje. NIE wypłaty (to kadry).

  - email: biuro@twojafirma.pl
    name: Biuro
    description: >
      Wszystko, co nie pasuje do innych działów.
```

Działów może być dowolnie dużo. **Najważniejsze jest pole `description`**: opisz w nim, co trafia do działu, a co *nie* trafia. Od tego zależy trafność routingu. Po zmianie wystarczy:

```bash
docker compose restart api
```

### 2. Poczta, model AI, zabezpieczenia: `.env`

```bash
cp .env.example .env
```

Przykład z prawdziwą pocztą (Microsoft 365) i modelem w chmurze:

```env
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USER=router@twojafirma.pl
SMTP_PASSWORD=...
SMTP_FROM=router@twojafirma.pl

LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...

API_KEY=dlugi-losowy-klucz
```

Gdy `API_KEY` jest ustawiony, każde zapytanie musi mieć nagłówek `X-API-Key`. Wszystkie opcje są opisane w [`.env.example`](.env.example).

> 💡 Chcesz dokładniejszy lokalny model? Ustaw `LLM_MODEL=qwen2.5:7b`. Ollama pobierze go sama przy starcie.

---

## API

| Metoda | Ścieżka | Opis |
|---|---|---|
| `POST` | `/api/v1/route` | Przyjmuje `{email, message}`, kieruje wiadomość do działu i wysyła maila |
| `GET` | `/api/v1/departments` | Lista skonfigurowanych działów (np. do formularza w intranecie) |
| `GET` | `/health` | Healthcheck |

---

## Jak to działa

```
formularz / aplikacja / bot
          │  POST /api/v1/route
          ▼
   [API: FastAPI] ── departments.yaml ──► prompt + lista dozwolonych adresów
          │
          │ 1. model dostaje jedno narzędzie: send_email(to, subject, body)
          ▼
   [model AI: Ollama / OpenAI / ...]
          │
          │ 2. model wywołuje narzędzie i wybiera dział (to = decyzja o routingu)
          ▼
   [API waliduje decyzję]  ── zły adres / brak odpowiedzi ──► retry ──► dział awaryjny
          │
          │ 3. API wysyła maila przez SMTP, Reply-To = nadawca z requestu
          ▼
   [skrzynka działu]
```

### Decyzje projektowe

- **Wywołanie narzędzia jest decyzją o routingu.** Model nie robi osobno klasyfikacji i wysyłki. Dostaje jedno narzędzie `send_email`, w którym pole `to` jest ograniczone do adresów z `departments.yaml`. Nie da się wysłać maila poza listę.
- **Reply-To nigdy nie pochodzi od modelu.** Nagłówek ustawia API na podstawie pola `email` z zapytania. Chroni to przed prompt injection, bo nikt nie przekona modelu, żeby odpowiedzi szły na obcy adres.
- **Łagodna degradacja zamiast błędu.** Małe lokalne modele czasem nie wywołają narzędzia albo podadzą zły adres. Router próbuje 3 razy (najpierw `tool_choice="required"`, potem `"auto"`), a jeśli to nie wystarczy, wysyła wiadomość do działu awaryjnego. Żadne zgłoszenie nie ginie.
- **Przetestowane na żywym modelu.** Domyślną konfigurację sprawdzono na 50 różnych, także podchwytliwych wiadomościach po polsku i angielsku: small talk, bezsens, mobbing, phishing, sprawy na styku dwóch działów. Zero błędnych zapytań, średnio ~0,9 s na wiadomość. Przypadki graniczne (np. „zacięta drukarka”: IT czy help desk?) mogą czasem wypaść różnie, bo to klasyfikator AI. Rozwiązaniem jest doprecyzowanie `description`.

---

## Struktura projektu

```
departments.yaml      - działy (edytuj pod swoją firmę)
.env.example          - konfiguracja poczty, modelu i klucza API
docker-compose.yml
api/app/
  main.py             - endpointy HTTP, Swagger, klucz API
  agent.py            - prompt i narzędzie budowane z departments.yaml, retry/fallback
  departments.py      - wczytywanie i walidacja departments.yaml
  mailer.py           - wysyłka SMTP (plain / STARTTLS / SSL), Reply-To
  config.py           - ustawienia ze zmiennych środowiskowych
```

---

## 🇬🇧 In English

**AI Mail Router** routes free-text employee messages to the right department by email. An LLM picks the department through tool calling, and the reply goes straight back to the sender. Departments are defined in `departments.yaml`, the LLM can be any OpenAI-compatible API (local Ollama by default), and SMTP works with Gmail, Microsoft 365 or any server. Run `docker compose up -d` and open http://localhost:8000/api/v1/docs. MIT licensed.

---

## Licencja

[MIT](LICENSE) © AImployee ([aimployee.pl](https://aimployee.pl))

Potrzebujesz wdrożenia w firmie, integracji z helpdeskiem albo wersji czytającej skrzynkę pocztową? Napisz: [aimployee.pl](https://aimployee.pl)

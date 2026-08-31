# AI Message Router - Proof of Concept

Mikroserwis, ktory dziala jak inteligentny router wiadomosci. Przyjmuje krotki tekst od pracownika (np. "nie dziala mi komputer"), wysyla go do lokalnie hostowanego modelu jezykowego (Ollama), a model poprzez prawdziwe tool/function calling decyduje do jakiego dzialu to przekierowac i sam wywoluje narzedzie, ktore wysyla maila. Mail jest przechwytywany przez MailHog, wiec nic nie wychodzi na zewnatrz, wszystko mozna podejrzec w panelu webowym.

## Jak to odpalic

```bash
docker compose up -d
```

To wszystko. Przy pierwszym uruchomieniu Docker:

1. zbuduje obraz API,
2. odpali MailHog i Ollame,
3. pobierze wagi modelu do wolumenu (serwis `ollama-pull`, to jest ten wolny krok za pierwszym razem, kilka GB w zaleznosci od modelu),
4. dopiero po tym wystartuje API, jak model bedzie juz gotowy.

Kolejne uruchomienia `docker compose up -d` sa juz szybkie, bo wagi modelu zostaja w wolumenie `ollama_data` i nie sciagaja sie od nowa.

Po odpaleniu:

- API: http://localhost:8000
- Dokumentacja Swagger: **http://localhost:8000/api/v1/docs**
- Panel MailHog (widac tu przechwycone maile): http://localhost:8025

### Przykladowe zapytanie

```bash
curl -X POST http://localhost:8000/api/v1/route \
  -H "Content-Type: application/json" \
  -d '{"email": "jan.nowak@example.com", "message": "Nie dziala mi komputer"}'
```

Odpowiedz:

```json
{"routed_to": "it@example.com", "subject": "..."}
```

Potem wchodzisz na http://localhost:8025 i widzisz przekazana wiadomosc w skrzynce `it@example.com`, z naglowkiem `Reply-To: jan.nowak@example.com` ustawionym poprawnie.

Drugi przyklad, zeby zobaczyc inny routing:

```bash
curl -X POST http://localhost:8000/api/v1/route \
  -H "Content-Type: application/json" \
  -d '{"email": "jan.nowak@example.com", "message": "Chcialbym zglosic urlop na jutro"}'
```

## Jak to jest zbudowane

```
klient --HTTP--> [api: FastAPI]
                      |
                      | 1. chat.completions(tools=[send_email]) przez OpenAI-kompatybilne API
                      v
                 [ollama: lokalny model, np. llama3.2]
                      |
                      | 2. model odpowiada tool_callem: send_email(to, subject, body)
                      v
                 [api parsuje ten tool call]
                      |
                      | 3. api faktycznie wysyla maila przez smtplib (Reply-To ustawiony
                      |    z ORYGINALNEGO requestu, nie z modelu)
                      v
                 [mailhog: SMTP :1025 / panel webowy :8025]
```

Serwisy w `docker-compose.yml`:

| serwis        | co robi                                                              |
|---------------|-----------------------------------------------------------------------|
| `ollama`      | odpala model, wystawia OpenAI-kompatybilne API na `:11434`            |
| `ollama-pull` | jednorazowy job, sciaga wagi modelu do wolumenu `ollama`, potem konczy dzialanie |
| `mailhog`     | fejkowy serwer SMTP + panel webowy, zastepuje prawdziwa poczte        |
| `api`         | serwis FastAPI, tu siedzi agent i endpoint HTTP                       |

## Decyzje projektowe

- **Tool call to jest decyzja o routingu.** Agent dostaje dokladnie jedno narzedzie, `send_email(to, subject, body)`, gdzie `to` jest ograniczone do listy pieciu adresow dzialow. Model nie robi osobno "klasyfikacji" i osobno "wysylki", wybor argumentu `to` w tool callu to jest ta klasyfikacja. To pasuje do wymagania z zadania, ze agent ma samodzielnie uzyc udostepnionego mu narzedzia do wysylki maila.

- **Reply-To nigdy nie jest w gestii modelu.** LLM decyduje tylko dokad wyslac wiadomosc i jak ja sformulowac. Naglowek Reply-To ustawiany jest deterministycznie przez API, na podstawie pola `email` z oryginalnego requestu. Dzieki temu model nie moze ustawic dowolnego albo zepsutego Reply-To, co jest wazne tez pod katem prompt injection.

- **Domyslny model to llama3.2 (3B).** To jeden z mniejszych modeli, ktore w Ollamie dobrze radza sobie z tool callingiem, wiec pierwsze `docker compose up -d` nie trwa wiecznosc (pobranie ~2GB). Jak ktos chce wiekszej dokladnosci klasyfikacji, wystarczy podmienic model bez zadnych zmian w kodzie:

  ```bash
  OLLAMA_MODEL=qwen2.5:7b docker compose up -d
  ```

- **Retry i graceful fallback zamiast twardego bledu.** Male lokalne modele czasem nie zwroca tool calla albo zwroca zly. Funkcja `route_message()` w `agent.py` probuje najpierw z `tool_choice="required"`, potem dwa razy z `tool_choice="auto"` (bo nie kazda kombinacja Ollama/model wspiera `"required"`, wiec taki blad jest lapany i leci fallback). Jak wszystkie trzy proby zawioda, wiadomosc idzie do `other@example.com` zamiast wywalac blad 5xx. Tak wlasnie powinien zachowywac sie produkcyjny system przy niedeterministycznym outpucie z LLM, ma degradowac sie lagodnie, a nie gubic zgloszenia.

- **Rozroznienie human-resources vs kadry.** W zadaniu sa jednoczesnie `human-resources@example.com` i `kadry@example.com`, ktore po angielsku brzmia podobnie. System prompt rozstrzyga to tak: `kadry@example.com` to polska administracja kadrowo-placowa (urlop, L4, wyplata i tym podobne), a `human-resources@example.com` to ogolne sprawy HR (umowy, onboarding, polityka firmy). To jest decyzja uznaniowa, opisana tutaj zeby latwo bylo ja zakwestionowac albo poprawic, to jeden akapit w `api/app/agent.py::SYSTEM_PROMPT`.

- **Sprawdzone na zywym modelu, nie tylko przeczytane.** Agenta odpalilem naprawde, end-to-end (prawdziwy HTTP tool calling, zero mockow), przeciwko lokalnemu LLM wystawiajacemu to samo OpenAI-kompatybilne API co Ollama, na 50 roznych, momentami podchwytliwych wiadomosci po polsku i troche po angielsku, tak zeby model musial sie chwile zastanowic: pogaduszki, pytania niezwiazane z firma, bezsensowny tekst, wrazliwe sprawy HR (mobbing, konflikt), zgloszenie phishingu, wiadomosci na styku dwoch dzialow. Zero bledow requestow na calej partii, srednio ok. 0.9s na zapytanie. Ten test wychwycil realny problem w pierwszej wersji promptu: model traktowal `help-desk@example.com` jak worek na wszystko i wrzucal tam czasem pogaduszki, pytania niezwiazane z firma, a nawet pytania o benefity czy szkolenia, zamiast do `human-resources@example.com` albo `other@example.com`. Dopisalem w `SYSTEM_PROMPT` wprost, ze help-desk to nie jest kosz na wszystko, oraz ze benefity/szkolenia to zawsze HR, a tematy niezwiazane z praca to `other`. Po tej poprawce te same 50 wiadomosci przeszlo juz bez tych bledow. Model nie jest w pelni deterministyczny, wiec pojedyncze przypadki na granicy dwoch dzialow (np. "zacieta drukarka": awaria sprzetu czy zgloszenie do help-desk) moga czasem wypasc inaczej miedzy jednym uruchomieniem a drugim, to normalne przy takim klasyfikatorze, a nie blad.

## Struktura projektu

```
docker-compose.yml
api/
  Dockerfile
  requirements.txt
  app/
    main.py     - aplikacja FastAPI, endpoint HTTP, konfiguracja Swaggera
    agent.py    - schemat narzedzia, system prompt, wywolanie Ollamy, logika retry/fallback
    mailer.py   - wysylka przez SMTP do MailHoga, obsluga Reply-To
    config.py   - ustawienia z zmiennych srodowiskowych
```

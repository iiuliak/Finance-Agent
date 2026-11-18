# VAT Reserve Agent

An agent that tells a freelancer how much of their balance is VAT and proposes moving it into a tax reserve. It never moves money without the user's confirmation.

The demo books are synthetic: one account, a year of invoices and expenses, quarterly VAT on a cash basis (VAT is due when an invoice is paid). They open on today, unless `AS_OF_DATE` sets another day. Each quarter has its own invoices, on fixed days, so the card follows whichever quarter that day is in. The page can move that day, and it can add or delete invoices and expenses or change the two balances. A payment dated after the chosen day is hidden from the agent until the day reaches it. [RULES.md](RULES.md) is the full contract, including the answer key every test reproduces.

## Run it with Docker

You need Docker Desktop (or any Docker with Compose v2).

```bash
docker compose up --build
```

Open <http://localhost:8000>. The books open on today. From 2 November through 29 November, ask "How much should I move to my VAT reserve?". A card shows VAT already due (€2,565), the estimated VAT at quarter end (€4,085) and the proposed transfer (€3,585). The invoices from the rest of the year are on the books, and they belong to other quarters, so they leave that card as it is. Approve moves the money; Reject leaves everything as it is.

The same panel can move the day. On 10 December the €2,000 invoice has been paid, VAT already due is €2,945, and the missed €8,000 invoice drops out of the forecast. On 5 November the card matches 15 November. Moving into another quarter reads that quarter's invoices instead. Adding an invoice or an expense, or editing either balance, updates those figures. A card that was already on screen is withdrawn, because its amount was computed from the old books.

On startup the container applies the migrations and loads the demo books if they are missing. To start the demo over after approving:

```bash
docker compose exec app python -m finance_agent.seed --reset
```

## Run it without Docker

You need Python 3.14 and a PostgreSQL server. The app expects `postgresql+psycopg://vat:vat@localhost:5433/vat`; set `DATABASE_URL` to use another one. The easiest way to get that database is `docker compose up -d db`.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

alembic upgrade head
python -m finance_agent.seed            # add --reset to start over
uvicorn finance_agent.api.main:app --reload
```

Open <http://localhost:8000>.

## Choosing the language model

By default (`LLM_MODE=template`) no model is called: replies are built from the books, so the demo runs offline without a key.

Set `LLM_MODE=openai` to let a model drive the conversation through tools. Any OpenAI-compatible API works. Copy `.env.example` to `.env` for Docker, or export the variables in your shell for a local run.

| Provider | Variables |
| --- | --- |
| Groq (free key at [console.groq.com](https://console.groq.com)) | `OPENAI_BASE_URL=https://api.groq.com/openai/v1`, `OPENAI_API_KEY`, `OPENAI_MODEL=openai/gpt-oss-120b` |
| OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL` (for example `gpt-4o-mini`) |
| Ollama, local run | `OPENAI_BASE_URL=http://localhost:11434/v1`, `OPENAI_MODEL=llama3.1` |
| Ollama, from Docker | `OPENAI_BASE_URL=http://host.docker.internal:11434/v1`, `OPENAI_MODEL=llama3.1` |

The model never does arithmetic and never chooses an amount. It can call five tools, none of which takes arguments:

| Tool | Type | Needs approval |
| --- | --- | --- |
| `get_invoices` | Read | No |
| `get_expenses` | Read | No |
| `get_balance` | Read | No |
| `get_vat_summary` | Read | No |
| `transfer_to_reserve` | Write | Yes |

`get_vat_summary` returns the VAT figures already computed in Python, so the model can answer "how much VAT do I owe?" without adding anything up itself.

`transfer_to_reserve` only saves a pending proposal whose amount Python computed. Money moves only when the user clicks Approve, which calls `POST /api/proposals/{id}/decision`, an endpoint the model has no access to.

A user message that contains personal information, such as a name, a surname, an IBAN, an email, or a phone number, is not sent, and the model is not called. The reply is always: "Your message contains personal information (e.g., a name, surname, IBAN, email, or phone number). Please remove it from your message." Earlier chat turns that contain personal information are replaced with a flag. A message without that information is sent as written.

## How we show it works

Forecast error against the true VAT in the synthetic data. This check scores the opening day (today, or `AS_OF_DATE`). It does not follow the day selected on the page:

```bash
python -m finance_agent.eval_forecast
```

```text
estimated_vat_due 4085.00
true_vat_due 2945.00
absolute_error 1140.00
```

That sample is what a day from 2 November through 29 November prints. Another day prints that day's error. The forecast assumes each open invoice is paid on its expected date. In the fourth quarter the €8,000 invoice is paid in January and the €2,000 invoice is paid on 10 December, which accounts for the error.

Tests, including the proof that no transfer runs without approval (`tests/test_approval.py`, `tests/test_api.py`, `tests/test_agent.py`), need the database from `docker compose up -d db`. They create and use a separate `vat_test` database:

```bash
pytest
```

## Layout

| Path | What it holds |
| --- | --- |
| `finance_agent/domain` | Pure VAT, forecast and proposal arithmetic |
| `finance_agent/services` | Proposal generation and the approve/reject decision |
| `finance_agent/agent` | LangGraph agent, tools, and the template (no model) mode |
| `finance_agent/api` | FastAPI app serving the page and the JSON API |
| `finance_agent/db`, `alembic` | SQLAlchemy models and migrations |
| `finance_agent/demo_data.py` | The synthetic books |

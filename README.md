# VAT Reserve Agent

SME collect VAT from their clients and then spend it. When the quarterly payment to the Finanzamt is due, the money is no longer in the account.

This demo is an agent that keeps that VAT aside. It looks at one account, says how much of the balance is VAT, and proposes moving that amount into a tax reserve. The user approves or rejects the proposal. Money moves only after they click Approve.

The books are synthetic. There is one tax setup: a quarterly return, with VAT due when the invoice is paid. The agent reads invoices (net amount, VAT rate, issue date, and whether they are paid), expenses (gross amount and input VAT), and the current balance.

## What the agent does

Python calculates every figure. The language model writes the explanation in plain language and repeats the figures the tools return.

1. VAT already due is VAT collected on invoices paid this quarter, minus input VAT on expenses in the same quarter.
2. A forecast adds the VAT on invoices that are still open and expected to be paid before the quarter ends. That is the estimated VAT at quarter end.
3. The proposal fills the reserve up to that estimate, and only up to the cash in the operating account. It reads like “Move €2,800 to your tax reserve.”
4. The page shows one card: the estimated VAT, the proposed amount, a short explanation, and Approve and Reject. Approve runs the transfer. Reject leaves both balances as they are.

The model can read invoices, expenses, the two balances, and the VAT summary Python has already computed. The only write it can ask for is a pending proposal. Approve is a separate action, and the model cannot take it.

## Compliant with EU regulations

The demo complies with the EU rules that apply to a VAT assistant which can propose a movement of money.

**VAT.** The calculation follows the EU VAT system as Germany applies it for this setup (Council Directive 2006/112/EC): a quarterly return, cash basis, and VAT owed equal to VAT collected minus deductible input VAT. Amounts are euros with two decimal places. Python does the arithmetic.

**Personal data** A message that contains a name, a surname, an email, an IBAN, or a phone number is withheld, and the model is not called. The reply asks the user to remove it. Earlier turns that contained personal information are replaced with a flag before a later turn is sent. The invoices and expenses are synthetic, so the agent works on made-up books.

**The customer stays in control** The agent files a proposal and waits. Money moves when the user clicks Approve, which calls an endpoint reserved for that decision. Reject, or leaving the card alone, leaves the balances unchanged. A proposal can be decided only once.

## Run the app

### With Docker

You need Docker Desktop, or any Docker with Compose v2.

```bash
docker compose up --build
```

Open <http://localhost:8000>. On startup the container applies the database migrations and loads the demo books if they are missing. Ask “How much should I move to my VAT reserve?”

To start the demo over after an approval:

```bash
docker compose exec app python -m finance_agent.seed --reset
```

### Without Docker

You need Python 3.14 and PostgreSQL. The app expects `postgresql+psycopg://vat:vat@localhost:5433/vat`. Set `DATABASE_URL` to use another database. The easiest way to get that database is `docker compose up -d db`.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

alembic upgrade head
python -m finance_agent.seed
uvicorn finance_agent.api.main:app --reload
```

Open <http://localhost:8000>. Add `--reset` to the seed command to load the demo books again.

### Language model

By default (`LLM_MODE=template`) no model is called. Replies are built from the books, so the demo runs without an API key.

Set `LLM_MODE=openai` to let a model drive the conversation. Any OpenAI-compatible API works. Copy `.env.example` to `.env` for Docker, or export the variables in your shell for a local run.

| Provider | Variables |
| --- | --- |
| Groq (free key at [console.groq.com](https://console.groq.com)) | `OPENAI_BASE_URL=https://api.groq.com/openai/v1`, `OPENAI_API_KEY`, `OPENAI_MODEL=openai/gpt-oss-120b` |
| OpenAI | `OPENAI_API_KEY`, `OPENAI_MODEL` (for example `gpt-4o-mini`) |
| Ollama, local run | `OPENAI_BASE_URL=http://localhost:11434/v1`, `OPENAI_MODEL=llama3.1` |
| Ollama, from Docker | `OPENAI_BASE_URL=http://host.docker.internal:11434/v1`, `OPENAI_MODEL=llama3.1` |

The books open on today. Set `AS_OF_DATE` (for example `2026-11-15`) to open on another day. After that, the page can move the day, add or delete invoices and expenses, and change the two balances.

# VAT Reserve Agent — demo rules

These rules are the contract for the demo. The calculation, the forecast, the card, the database, and the tests all follow them. Change a rule here before changing the code that depends on it.

## Clock

The books open on **15 November 2026**. `AS_OF_DATE` sets that starting day when the demo account is seeded. After that, the day lives on the account, and the page can move it. The app does not use the wall clock.

The chosen day selects the quarter. 15 November 2026 falls in the fourth calendar quarter:

- `period_start`: 1 October 2026, inclusive
- `period_end`: 1 January 2027, exclusive

Quarter boundaries are 1 January, 1 April, 1 July, and 1 October. `period_end` is the next boundary.

## When VAT counts

VAT is due when the invoice is paid (cash basis), and the return is quarterly.

- An invoice adds VAT only when `payment_date` is set and `period_start <= payment_date < period_end`.
- An expense adds input VAT only when `period_start <= expense_date < period_end`.
- An unpaid invoice adds nothing to VAT already due.

## Forecast

The forecast estimates VAT still to come from invoices that are open on the chosen day.

The database stores each invoice's real payment date. The forecast only sees the books as they stood on the chosen day. A payment dated after that day is treated as not yet paid, and an expense dated after it is ignored. VAT due so far uses the same view. The agent tools use that view too, so a later payment date is not something the model can read.

Count an invoice as additional VAT only when all of these are true:

- it is unpaid as of the chosen day
- `expected_payment_date` is set
- the expected day is still ahead: `expected_payment_date >= as_of`
- `period_start <= expected_payment_date < period_end`

Once the expected day has passed and the invoice is still unpaid, it is no longer counted as coming this quarter.

Do not invent future expenses. The estimate uses net VAT before flooring at zero, so input VAT already recorded reduces it:

```text
estimated_vat_due = max(collected_vat - input_vat + additional_vat, 0)
```

`vat_due = max(collected_vat - input_vat, 0)` is shown on the card as VAT already due.

The forecast method name is `expected_payment_dates`.

## Amount on the card

The proposed transfer fills the reserve up to the estimate, and never moves more cash than the operating account holds:

```text
proposed_amount = min(operating_balance, max(0, estimated_vat_due - reserve_balance))
```

The card shows three different numbers:

- VAT already due this quarter (`vat_due`)
- Estimated VAT at quarter end (`forecast_vat`)
- The proposed transfer (`proposed_amount`)

## Money

- Every amount is a `Decimal` with two digits, quantized with `ROUND_HALF_UP`. Never use `float`.
- Invoice VAT is the Postgres generated column `round(net_amount * vat_rate, 2)`. Python reads `vat_amount`. It does not multiply net by rate again.
- VAT rate is a fraction from 0 to 1, for example `0.1900` for 19%.

## Approval

Generating a proposal only stores a row with status `pending`. The graph does not move money.

A transfer is inserted only by the approve decision:

- Reject sets the proposal to `rejected` and inserts no transfer. Balances stay as they are.
- Approve of a positive amount moves that amount from the operating balance to the reserve balance and sets the proposal to `executed`, in the same database transaction.
- Approve of a zero amount sets the proposal to `executed` and inserts no transfer.
- A second decision on the same proposal is rejected. The idempotency key of a transfer is the proposal id, and each proposal has at most one transfer.
- Generating a proposal sets every other `pending` proposal for the account to `superseded`. A superseded proposal cannot be approved, because its amount was computed from balances that may have changed. At most one proposal per account is pending.

The model writes the explanation only. It does not choose any amount.

## Seed answer key

One account:

- Operating balance: €12,000
- Reserve balance: €500

Invoices, all at 19% VAT. The database stores the real payment date. On 15 November the last two are still in the future, so the agent treats them as unpaid.

| Net | Issued | Real payment | Expected payment | Visible on 15 Nov 2026 |
| --- | --- | --- | --- | --- |
| €10,000 | 1 Oct 2026 | 5 Oct 2026 | 5 Oct 2026 | paid |
| €5,000 | 20 Oct 2026 | 2 Nov 2026 | 2 Nov 2026 | paid |
| €8,000 | 1 Nov 2026 | 5 Jan 2027 | 30 Nov 2026 | unpaid |
| €2,000 | 10 Nov 2026 | 10 Dec 2026 | 15 Jan 2027 | unpaid |

VAT on those invoices is €1,900, €950, €1,520, and €380.

Expenses:

| Date | Gross | Input VAT |
| --- | --- | --- |
| 10 Oct 2026 | €1,190 | €190 |
| 1 Nov 2026 | €595 | €95 |

Figures every test should reproduce:

| Figure | Amount |
| --- | --- |
| VAT collected so far | €2,850 |
| Input VAT so far | €285 |
| VAT already due | €2,565 |
| Additional VAT in the forecast | €1,520 |
| Estimated quarter-end VAT | €4,085 |
| Proposed transfer | €3,585 |
| True quarter-end VAT | €2,945 |
| Absolute forecast error | €1,140 |

The forecast check always scores 15 November, even when the page is standing on another day.

On 10 December the €2,000 invoice has been paid and the €8,000 invoice's expected day has passed:

| Figure | Amount |
| --- | --- |
| VAT already due | €2,945 |
| Additional VAT in the forecast | €0 |
| Estimated quarter-end VAT | €2,945 |
| Proposed transfer | €2,445 |

On 5 November the visible books match 15 November, so the card is unchanged.

After a successful approve of the 15 November proposal: operating balance €8,415, reserve balance €4,085, one completed transfer of €3,585.

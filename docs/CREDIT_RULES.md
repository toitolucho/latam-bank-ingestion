# Credit rules (synthetic, policy version 0.4)

> Policy 0.4 is the reference version of the credit rules. Earlier components
> (`backend/policy/credit_policy.yaml`, gold views) were built on preliminary versions so the
> team could move in parallel; they are aligned to this version in follow-up PRs.

These rules produce **indicative pre-approved offers** for marketing and lead generation.
No offer is final: every customer who wants to proceed is handed off to an advisor, who
verifies documents and decides. Products in scope: credit card, personal loan and mortgage.

All parameters are synthetic and live in silver reference tables, loaded from `data/reference/`:
`ref_policy_params`, `ref_policy_bands`, `ref_segment_adjustments`, `ref_term_grid` and
`ref_product_catalog`. The gold SQL (`data/databricks/gold/`) and the rules
service read the **same tables** and must apply the **same formulas** (section 4).

## 1. Hard filters
If any fails, there is no automatic offer and the reason code is returned.

| Code | Rule | Value (`ref_policy_params`) |
|---|---|---|
| R01 | Active customer | `customer_status = 'Active'` |
| R02 | Minimum tenure | `min_tenure_months` = 6 |
| R03 | No delinquency | max `days_past_due` on active credit products ≤ `max_days_past_due` = 30 (current snapshot; the data has no 12-month history) |
| R04 | No blocked or suspended product | any product with status `Blocked` or `Suspended` |
| R05 | Minimum income | income known and ≥ `min_income_usd` = 300 USD/month |
| R06 | Minimum score | `credit_score` present and band ≠ E |
| R07 | Recent confirmed fraud | no fraud transaction in the last `fraud_lookback_days` = 90; otherwise advisor review |
| R08 | Capacity exhausted | available installment ≤ 0 |

`R05_INCOME_MISSING` is recoverable: the agent can ask the customer for their income and the
rules service recalculates (offer becomes conditional, flag `F03`).
Complaints never change the amount or the rate and do not block the offer. An open
High/Critical complaint sets `requires_advisor_review`; an open Critical complaint also
removes the proactive offer (section 7); and every accepted offer records the open complaints
and flag `F04` for the advisor (section 6).

## 2. Debt capacity: the 20% hard limit
- **Income used** = declared monthly income from `customers`, converted to USD at the cutoff
  date. Observed deposits are **ignored** for the limit, whether 0 or not: customers can be paid
  into other banks, so deposits here show only part of their income. Among eligible customers
  with deposits, observed income is a median 20% of declared and lower in 94% of cases; using
  the lower of the two would cut the median available installment from 458 to 87 USD. Deposits
  stay as an indicator for the advisor (`avg_monthly_deposits_usd_6m`).
- **Current installments** = sum of the monthly installments of the customer's active credit
  products:
  - loans: annuity of the original amount (`credit_limit`) at the product `interest_rate`, with
    the term taken from `ref_term_grid` (shortest term whose amount range covers the amount),
    because the data has no loan term;
  - credit cards: annuity of the current balance over 60 months at the card rate.
- **Maximum total installment** = `max_debt_to_income` (20%) × income used.
- **Available installment** = maximum total installment − current installments.

Only **current** credits count as existing debt: active credit cards, personal loans and
mortgages. Closed products do not count. Offers are proposals, not debt: neither the other
options shown nor offers already accepted in the chat (`credit_offers`) are subtracted, since
they only become credits after the advisor formalizes them.

The new installment can never exceed the available installment: after the offer, all
installments together stay at or below 20% of income. The amount is bounded by capacity and by
the product range; the term by the band (section 3).

## 3. Risk band and rate
The band will come from the risk model's probability of default. Until the model exists,
it comes from `credit_score` (`ref_policy_bands`):

| Band | Score | Rate adjustment | Max term personal loan | Max term mortgage | Offer |
|---|---|---|---|---|---|
| A | 740 or more | −2.0 pp | 60 months | 30 years | yes |
| B | 680–739 | −1.0 pp | 60 months | 30 years | yes |
| C | 620–679 | 0 | 48 months | 25 years | yes |
| D | 560–619 | +2.0 pp | 36 months | 20 years | yes |
| E | below 560 | — | — | — | no |

Risk limits the term, not the amount: a riskier band gets a higher rate and shorter maximum
terms. Credit cards always have the 5-year card term.

**Age at maturity (new in 0.4).** A personal loan or mortgage must end before the customer turns
`max_age_at_maturity_years` = 75 (`ref_policy_params`), as banks usually require for life
insurance on the loan. The maximum term is the band maximum capped by the months left until
that age (`customer_credit_profile.max_term_by_age_months`); a term above it is unavailable
(`term_above_band_maximum`). Examples: at 58, mortgages up to 15 years and personal loans up to
the band maximum; at 72, personal loans up to 36 months and no mortgage. Cards have no age cap.
When the birth date is missing there is no cap and the advisor verifies age.

Age is used **only** for this explicit term rule, never as a risk-model feature or to change the
amount or rate; gender, marital status and accent are not used at all (they serve only to
measure bias). At the 2026-06-30 cutoff, 19,256 of the 50,707 eligible customers have no
mortgage term available because of age and 8,677 no personal loan term; their card offer stands.

Segment adjustment (`ref_segment_adjustments`): Premium −1.0 pp, Plus −0.5 pp, Basic 0,
Student +1.0 pp.

**Offer rate** = `ref_term_grid.reference_rate_pct` + band adjustment + segment adjustment,
clamped to the product range `[min_rate_pct, max_rate_pct]` of `ref_product_catalog`.

## 4. Amount and installment (shared formulas)
With `r = annual_rate_pct / 1200` and `n = term_months`:
- `monthly_installment(P) = P · r / (1 − (1 + r)^−n)` (`fn_monthly_installment`)
- `max_principal(I) = I · (1 − (1 + r)^−n) / r` (`fn_max_principal`)

Options are **alternatives** ("this or that"), never added together: each option uses the
whole available installment on its own.

For each `ref_term_grid` option (loan term or card tier):
- loans: the term must be ≤ the band's maximum term for the product; the amount range is the
  whole product range of `ref_product_catalog` (5,000–150,000 USD for personal loans and
  mortgages), at any allowed term;
- cards: the amount range is the tier's credit limit range in `ref_term_grid`;
- maximum amount by capacity = `max_principal(available installment)` at the offer rate;
- offer maximum = min(capacity amount, range maximum), rounded down to 100 USD;
- the option is available only if the offer maximum ≥ range minimum.

The loan amount ranges per term in `ref_term_grid` are typical ranges: they are only used to
infer the term of the customer's existing loans (section 2), not to restrict new offers.

Cards use the same formulas with n = 60 (the limit is sized so that a full balance would be
repaid within the card term).

## 5. Currencies
- Catalog, grid and rules in USD. Income and balances are converted with
  `daily_exchange_rates` at the latest rate on or before the cutoff date (`as_of_date`).
- The customer sees amounts and installments in local currency; `credit_offers` stores the
  exchange rate used.
- The rate is a nominal annual rate and is not converted.

## 6. Live recalculation
The rules service starts from `gold.customer_credit_profile` and recomputes with sections 2–4.

| What the customer says | Treatment |
|---|---|
| Their income is different | Replaces income used; offer conditional, flag `F03` |
| Additional household income | Asked to **every** customer the same way ("is there anyone else in your household who contributes income and could join the credit?"), never inferred from marital status. If yes, the agent also asks **that person's monthly installments**: the income is added to income used and the installments to current installments (household income comes with household debt). If the customer does not know those installments, the extra income is not added and the advisor completes it. Conditional, flag `F03`; documents of both people required |
| Wants a lower installment or longer term | Pick another amount or option within the available installment |
| Has a debt outside the bank | Its installment is added to current installments; the offer may drop |
| Paid off a loan at another bank | Only changes if that installment had been declared before |

Advisor flags (they never block the handoff):
- `F02_NEAR_LIMIT_DECLARED_INCOME` the new total debt-to-income is 19% or more **and** the
  offer relies on income declared in the chat: a small error in that income would push the
  customer over 20%. Offers at the maximum amount on income from the profile do not raise it.
- `F03_DECLARED_DATA` the offer relies on data declared in the chat (income, household income,
  external debt)
- `F04_OPEN_COMPLAINTS` the customer has at least one open complaint at offer time

## 7. Proactive offers and marketing consent
Offers are computed for every customer. `customer_credit_profile.offer_mode` says how the
agent may use them:
- `proactive`: eligible, `accepts_marketing = true` and no open Critical complaint; the agent
  may present the offer.
- `on_customer_interest`: eligible but without marketing consent or with an open Critical
  complaint (`not_proactive_reason`); the agent does not mention offers unless the customer
  shows interest in credit, then the offer is ready.
- `none`: not eligible (see `reason_codes`).

`credit_offers.offer_origin` records which case led to each accepted offer.

**What to present first: always the highest.** Per product, the agent leads with one available
option (`customer_credit_offer_options.is_featured`); the others stay as alternatives if the
customer asks for a lower installment or another term:
- credit card: the highest available tier;
- personal loan and mortgage: the highest amount, which is usually the longest term the band
  allows. When several terms reach the product maximum (150,000 USD), the shortest of them wins:
  lower rate and less total interest for the same amount.

A product with no available option has no featured option.

## 8. Accepted offers and advisor handoff
When the customer accepts, the API writes one row to `gold.credit_offers`: offer parameters
in USD and local currency, exchange rate, income used and its source, current installments,
resulting debt-to-income, band, segment, rate adjustment, declared data, open complaints at
offer time (all, High/Critical and Critical), flags, required documents, `offer_id`,
`policy_version`, validity (`offer_validity_days` = 30) and status.
Every accepted offer is handed off to an advisor.

## Example
Band C, Basic segment, income 2,500 USD from the profile, current installments 100 USD:
- maximum total installment = 20% × 2,500 = 500; available = 400;
- personal loan, 24 months at 15.2%: `max_principal(400)` = 8,233 → offer up to **8,200 USD**,
  installment 398.37, total debt-to-income after (100 + 398.37) / 2,500 = 19.9%; no flag,
  because the income comes from the profile;
- or personal loan, 48 months (band C maximum) at 21.7%: offer up to **12,700 USD**, installment
  398.06. A 60-month term is not available to band C.

The customer adds 1,000 USD of household income: income 3,500, available 600, 24-month offer up
to 12,300 USD (flags `F02`, `F03`). The customer declares an external loan of 150 USD/month:
available 250, 24-month offer up to 5,100 USD (flag `F03`). In every case, if the customer
proceeds, the offer is recorded and handed off to an advisor.

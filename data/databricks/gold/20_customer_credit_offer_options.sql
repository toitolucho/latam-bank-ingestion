-- =============================================================================================
-- customer_credit_offer_options: baseline offer per customer and term-grid option.
-- Task of the latam_bank_medallion and credit_policy_refresh jobs; runs after customer_credit_profile.
-- Parameters :silver_schema (ref_*) and :gold_schema (profile, fn_*), catalog.schema.
-- Policy and formulas: docs/CREDIT_RULES.md. Synthetic policy, offline results.
-- =============================================================================================

CREATE OR REPLACE TABLE IDENTIFIER(:gold_schema || '.customer_credit_offer_options')
COMMENT 'Baseline pre-approved offer per customer and product option (ref_term_grid row: loan term or card tier). Options are alternatives: each uses the whole 20% capacity; is_featured marks the one to present first per product. Rate = reference rate + band and segment adjustments, clamped to the product range. Loans: any amount in the product range, at terms up to the band maximum. Cards: the tier credit limit range. Maximum amount = what the available installment can repay, capped by the range. Indicative only; the rules service recomputes when the customer gives new data. Amounts in USD and local currency.'
AS
WITH catalog AS (
    SELECT product_code, min_amount_usd, max_amount_usd, min_rate_pct, max_rate_pct
    FROM IDENTIFIER(:silver_schema || '.ref_product_catalog')
),
priced AS (
    SELECT
        p.customer_id,
        p.local_currency,
        p.fx_to_usd,
        p.is_eligible,
        p.offer_mode,
        p.reason_codes,
        p.available_installment_usd,
        p.risk_band,
        p.segment,
        p.total_rate_adjustment_pp,
        p.as_of_date,
        p.policy_version,
        g.product_code                                    AS option_code,
        c.product_code,
        g.product_type,
        g.tier,
        g.term_months,
        -- loans: whole product range at any allowed term; cards: the tier limit range
        CASE WHEN c.product_code = 'CC' THEN g.min_amount_usd ELSE c.min_amount_usd END AS option_min_amount_usd,
        CASE WHEN c.product_code = 'CC' THEN g.max_amount_usd ELSE c.max_amount_usd END AS option_max_amount_usd,
        CASE c.product_code
            WHEN 'PL' THEN g.term_months <= p.max_term_personal_loan_months
            WHEN 'MG' THEN g.term_months <= p.max_term_mortgage_months
            ELSE true END                                 AS term_allowed,
        g.reference_rate_pct,
        least(greatest(g.reference_rate_pct + p.total_rate_adjustment_pp, c.min_rate_pct), c.max_rate_pct) AS offer_rate_pct
    FROM IDENTIFIER(:gold_schema || '.customer_credit_profile') p
    CROSS JOIN IDENTIFIER(:silver_schema || '.ref_term_grid') g
    JOIN catalog c ON c.product_code = split(g.product_code, '-')[0]
),
sized AS (
    SELECT
        *,
        IDENTIFIER(:gold_schema || '.fn_max_principal')(greatest(coalesce(available_installment_usd, 0), 0), offer_rate_pct, term_months) AS max_amount_by_capacity_usd
    FROM priced
),
capped AS (
    SELECT *, floor(least(max_amount_by_capacity_usd, option_max_amount_usd) / 100) * 100 AS capped_amount_usd
    FROM sized
),
available AS (
    SELECT *,
        coalesce(is_eligible AND term_allowed AND capped_amount_usd >= option_min_amount_usd, false) AS is_available
    FROM capped
),
featured AS (
    -- The option the agent presents first, per customer and product: cards the highest tier,
    -- loans the highest amount; ties (several terms at the product maximum) go to the shortest term.
    SELECT *,
        is_available AND row_number() OVER (
            PARTITION BY customer_id, product_code
            ORDER BY is_available DESC, option_max_amount_usd DESC, capped_amount_usd DESC, term_months ASC) = 1 AS is_featured
    FROM available
)
SELECT
    customer_id,
    option_code,
    product_code,
    product_type,
    tier,
    term_months,
    reference_rate_pct,
    total_rate_adjustment_pp,
    round(offer_rate_pct, 2)                                                   AS offer_rate_pct,
    option_min_amount_usd,
    option_max_amount_usd,
    term_allowed,
    round(max_amount_by_capacity_usd, 2)                                       AS max_amount_by_capacity_usd,
    is_available,
    is_featured,
    offer_mode,
    CASE WHEN NOT is_eligible                              THEN 'customer_not_eligible'
         WHEN NOT term_allowed                             THEN 'term_above_band_maximum'
         WHEN capped_amount_usd < option_min_amount_usd    THEN 'capacity_below_option_minimum' END AS unavailable_reason,
    CASE WHEN is_available THEN capped_amount_usd END                          AS offer_max_amount_usd,
    CASE WHEN is_available
         THEN round(IDENTIFIER(:gold_schema || '.fn_monthly_installment')(capped_amount_usd, offer_rate_pct, term_months), 2) END AS offer_monthly_installment_usd,
    local_currency,
    fx_to_usd,
    CASE WHEN is_available THEN round(capped_amount_usd / fx_to_usd, 0) END   AS offer_max_amount_local,
    CASE WHEN is_available
         THEN round(IDENTIFIER(:gold_schema || '.fn_monthly_installment')(capped_amount_usd, offer_rate_pct, term_months) / fx_to_usd, 0) END AS offer_monthly_installment_local,
    risk_band,
    segment,
    as_of_date,
    policy_version,
    current_timestamp()                                                        AS computed_at
FROM featured;

-- Column descriptions (reapplied on every rebuild: CREATE OR REPLACE drops them).
ALTER TABLE IDENTIFIER(:gold_schema || '.customer_credit_offer_options') ALTER COLUMN
    customer_id COMMENT 'Customer key',
    option_code COMMENT 'ref_term_grid option: PL, MG, or CC-<tier> for credit cards',
    product_code COMMENT 'CC credit card, PL personal loan, MG mortgage',
    product_type COMMENT 'Credit Card, Personal Loan or Mortgage',
    tier COMMENT 'Card tier (Classic, Gold, Platinum, Black); null for loans',
    term_months COMMENT 'Term in months (cards: 60, the card validity)',
    reference_rate_pct COMMENT 'Reference annual rate of the option in ref_term_grid, percent',
    total_rate_adjustment_pp COMMENT 'Band + segment adjustment of the customer, percentage points',
    offer_rate_pct COMMENT 'Offered nominal annual rate: reference + adjustment, clamped to the product rate range',
    option_min_amount_usd COMMENT 'Lowest amount for the option, USD: product minimum for loans, tier minimum for cards',
    option_max_amount_usd COMMENT 'Highest amount for the option, USD: product maximum for loans, tier maximum for cards',
    term_allowed COMMENT 'The term is within the band maximum capped by age at maturity (always true for cards)',
    max_amount_by_capacity_usd COMMENT 'Amount the available installment repays at offer_rate_pct over term_months, USD',
    is_available COMMENT 'Eligible customer, term allowed and capped amount >= option minimum',
    is_featured COMMENT 'Option to present first for the customer and product: cards the highest available tier, loans the highest amount, ties to the shortest term. At most one per customer and product',
    offer_mode COMMENT 'Customer offer mode copied from the profile (proactive, on_customer_interest, none)',
    unavailable_reason COMMENT 'customer_not_eligible, term_above_band_maximum (band maximum or age-at-maturity cap) or capacity_below_option_minimum; null when available',
    offer_max_amount_usd COMMENT 'Largest amount offered: min(capacity amount, option maximum) rounded down to 100 USD; null when not available',
    offer_monthly_installment_usd COMMENT 'Monthly installment of offer_max_amount_usd, USD',
    local_currency COMMENT 'Currency shown to the customer',
    fx_to_usd COMMENT 'Exchange rate used: 1 unit of local_currency = fx_to_usd USD',
    offer_max_amount_local COMMENT 'offer_max_amount_usd in local currency',
    offer_monthly_installment_local COMMENT 'offer_monthly_installment_usd in local currency',
    risk_band COMMENT 'Customer risk band',
    segment COMMENT 'Customer segment',
    as_of_date COMMENT 'Cutoff date of the profile',
    policy_version COMMENT 'Credit policy version used',
    computed_at COMMENT 'When the row was computed';

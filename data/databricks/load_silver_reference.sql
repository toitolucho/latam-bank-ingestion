-- Loads the static reference tables from data/reference/*.csv into silver.
-- The CSVs are uploaded first to the volume /Volumes/workspace/silver_latam_bank/reference/
-- (see data/scripts/load_reference.py). Rerun only when a CSV changes.
-- All tables are synthetic: team-defined, derived from observed `products` data where
-- possible (see data/reference/README.md and data/reference/derivation/). ref_card_tiers.csv is only a
-- derivation input for derivation/07 and is not loaded: its result is already in ref_term_grid.
-- Parameter :silver_schema (catalog.schema) selects where the ref_* tables are created
-- (workspace.silver_latam_bank_test or workspace.silver_latam_bank); the CSVs are always read from
-- the volume workspace.silver_latam_bank.reference.

CREATE VOLUME IF NOT EXISTS workspace.silver_latam_bank.reference
COMMENT 'Source CSVs for the synthetic reference tables (silver.ref_*). Source of truth: data/reference/ in the team repo.';

CREATE SCHEMA IF NOT EXISTS IDENTIFIER(:silver_schema);

-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE IDENTIFIER(:silver_schema || '.ref_product_catalog') (
    product_code         STRING     NOT NULL COMMENT 'Product family code: CC credit card, PL personal loan, MG mortgage',
    product_type         STRING     NOT NULL COMMENT 'English product type',
    source_product_type  STRING     NOT NULL COMMENT 'Raw product_type label in bronze products (Spanish); join key to map raw data',
    min_amount_usd       INT        NOT NULL COMMENT 'Minimum amount / credit limit in USD (observed min of active products)',
    max_amount_usd       INT        NOT NULL COMMENT 'Maximum amount / credit limit in USD (observed max of active products)',
    min_rate_pct         DOUBLE     NOT NULL COMMENT 'Minimum nominal annual rate, percent (observed)',
    max_rate_pct         DOUBLE     NOT NULL COMMENT 'Maximum nominal annual rate, percent (observed)',
    allowed_terms_months ARRAY<INT> NOT NULL COMMENT 'Allowed terms in months. SYNTHETIC: the source data has no loan term',
    is_synthetic         BOOLEAN    NOT NULL COMMENT 'Always true: team-defined data',
    policy_version       STRING     NOT NULL COMMENT 'Version of the reference data set',
    _source_file         STRING              COMMENT 'Volume file the row was loaded from',
    _loaded_at           TIMESTAMP           COMMENT 'Load timestamp'
)
COMMENT 'SYNTHETIC credit product catalog (credit card, personal loan, mortgage). Country-agnostic, amounts in USD. Stands in for a source product catalog the dataset lacks. Static: loaded from data/reference/ref_product_catalog.csv.';

INSERT INTO IDENTIFIER(:silver_schema || '.ref_product_catalog')
SELECT
    product_code,
    product_type,
    source_product_type,
    min_amount_usd,
    max_amount_usd,
    min_rate_pct,
    max_rate_pct,
    transform(split(allowed_terms_months, '\\|'), x -> CAST(x AS INT)),
    is_synthetic,
    '0.1',
    _metadata.file_path,
    current_timestamp()
FROM read_files(
    '/Volumes/workspace/silver_latam_bank/reference/ref_product_catalog.csv',
    format => 'csv', header => true,
    schema => 'product_code STRING, product_type STRING, source_product_type STRING, min_amount_usd INT, max_amount_usd INT, min_rate_pct DOUBLE, max_rate_pct DOUBLE, allowed_terms_months STRING, is_synthetic BOOLEAN'
);

-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE IDENTIFIER(:silver_schema || '.ref_term_grid') (
    product_code        STRING  NOT NULL COMMENT 'PL, MG, or CC-<tier_code> for credit card tiers',
    product_type        STRING  NOT NULL COMMENT 'English product type',
    tier                STRING           COMMENT 'Credit card tier; null for loans',
    term_months         INT     NOT NULL COMMENT 'Term in months (cards: 60 = card validity)',
    term_years          INT     NOT NULL COMMENT 'Term in years',
    reference_rate_pct  DOUBLE  NOT NULL COMMENT 'Reference nominal annual rate, percent',
    min_amount_usd      INT     NOT NULL COMMENT 'Cards: tier minimum credit limit (USD). Loans: typical minimum amount for the term, used only to infer the term of existing loans',
    max_amount_usd      INT     NOT NULL COMMENT 'Cards: tier maximum credit limit (USD). Loans: typical maximum amount for the term, used only to infer the term of existing loans',
    is_synthetic        BOOLEAN NOT NULL COMMENT 'Always true: team-defined data',
    policy_version      STRING  NOT NULL COMMENT 'Version of the reference data set',
    _source_file        STRING           COMMENT 'Volume file the row was loaded from',
    _loaded_at          TIMESTAMP        COMMENT 'Load timestamp'
)
COMMENT 'SYNTHETIC reference rate and amount range per product and term (cards per tier). Country-agnostic, USD; local currency is computed at serving time. Derived once with data/reference/derivation/07_term_rate_amount_grid.sql from observed active products; static.';

INSERT INTO IDENTIFIER(:silver_schema || '.ref_term_grid')
SELECT product_code, product_type, tier, term_months, term_years, reference_rate_pct,
       min_amount_usd, max_amount_usd, is_synthetic,
       '0.1', _metadata.file_path, current_timestamp()
FROM read_files(
    '/Volumes/workspace/silver_latam_bank/reference/ref_term_grid.csv',
    format => 'csv', header => true,
    schema => 'product_code STRING, product_type STRING, tier STRING, term_months INT, term_years INT, reference_rate_pct DOUBLE, min_amount_usd INT, max_amount_usd INT, is_synthetic BOOLEAN'
);

-- =============================================================================================
-- Credit policy parameters (policy_version 0.4). Read by the gold SQL and by the rules service,
-- so both compute offers with the same values. See docs/CREDIT_RULES.md.
-- =============================================================================================
CREATE OR REPLACE TABLE IDENTIFIER(:silver_schema || '.ref_policy_params') (
    param_name     STRING  NOT NULL COMMENT 'Parameter name',
    param_value    STRING  NOT NULL COMMENT 'Parameter value as text; cast by the consumer according to unit',
    unit           STRING           COMMENT 'Unit or type of the value',
    description    STRING           COMMENT 'What the parameter controls',
    is_synthetic   BOOLEAN NOT NULL COMMENT 'Always true: team-defined policy',
    policy_version STRING  NOT NULL COMMENT 'Version of the policy data set',
    _source_file   STRING           COMMENT 'Volume file the row was loaded from',
    _loaded_at     TIMESTAMP        COMMENT 'Load timestamp'
)
COMMENT 'SYNTHETIC scalar credit policy parameters: 20% debt-to-income hard limit, hard-filter thresholds, cutoff date. Static: loaded from data/reference/ref_policy_params.csv.';

INSERT INTO IDENTIFIER(:silver_schema || '.ref_policy_params')
SELECT param_name, param_value, unit, description, is_synthetic,
       '0.4', _metadata.file_path, current_timestamp()
FROM read_files(
    '/Volumes/workspace/silver_latam_bank/reference/ref_policy_params.csv',
    format => 'csv', header => true,
    schema => 'param_name STRING, param_value STRING, unit STRING, description STRING, is_synthetic BOOLEAN'
);

-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE IDENTIFIER(:silver_schema || '.ref_policy_bands') (
    band               STRING  NOT NULL COMMENT 'Risk band A (best) to E',
    min_credit_score   INT     NOT NULL COMMENT 'Minimum credit_score for the band (score fallback until the risk model exists)',
    rate_adjustment_pp DOUBLE  NOT NULL COMMENT 'Percentage points added to the reference rate',
    offer_allowed      BOOLEAN NOT NULL COMMENT 'False for band E: no automatic offer',
    max_term_personal_loan_months INT NOT NULL COMMENT 'Longest personal loan term the band can take',
    max_term_mortgage_months      INT NOT NULL COMMENT 'Longest mortgage term the band can take',
    is_synthetic       BOOLEAN NOT NULL COMMENT 'Always true: team-defined policy',
    policy_version     STRING  NOT NULL COMMENT 'Version of the policy data set',
    _source_file       STRING           COMMENT 'Volume file the row was loaded from',
    _loaded_at         TIMESTAMP        COMMENT 'Load timestamp'
)
COMMENT 'SYNTHETIC risk bands by credit_score: eligibility (band E has no offer), rate adjustment and maximum loan terms (risk limits the term, not the amount). Static: loaded from data/reference/ref_policy_bands.csv.';

INSERT INTO IDENTIFIER(:silver_schema || '.ref_policy_bands')
SELECT band, min_credit_score, rate_adjustment_pp, offer_allowed,
       max_term_personal_loan_months, max_term_mortgage_months, is_synthetic,
       '0.4', _metadata.file_path, current_timestamp()
FROM read_files(
    '/Volumes/workspace/silver_latam_bank/reference/ref_policy_bands.csv',
    format => 'csv', header => true,
    schema => 'band STRING, min_credit_score INT, rate_adjustment_pp DOUBLE, offer_allowed BOOLEAN, max_term_personal_loan_months INT, max_term_mortgage_months INT, is_synthetic BOOLEAN'
);

-- ---------------------------------------------------------------------------------------------
CREATE OR REPLACE TABLE IDENTIFIER(:silver_schema || '.ref_segment_adjustments') (
    segment            STRING  NOT NULL COMMENT 'Customer segment as in customers.segment',
    rate_adjustment_pp DOUBLE  NOT NULL COMMENT 'Percentage points added to the reference rate',
    is_synthetic       BOOLEAN NOT NULL COMMENT 'Always true: team-defined policy',
    policy_version     STRING  NOT NULL COMMENT 'Version of the policy data set',
    _source_file       STRING           COMMENT 'Volume file the row was loaded from',
    _loaded_at         TIMESTAMP        COMMENT 'Load timestamp'
)
COMMENT 'SYNTHETIC rate adjustment by customer segment. Static: loaded from data/reference/ref_segment_adjustments.csv.';

INSERT INTO IDENTIFIER(:silver_schema || '.ref_segment_adjustments')
SELECT segment, rate_adjustment_pp, is_synthetic,
       '0.4', _metadata.file_path, current_timestamp()
FROM read_files(
    '/Volumes/workspace/silver_latam_bank/reference/ref_segment_adjustments.csv',
    format => 'csv', header => true,
    schema => 'segment STRING, rate_adjustment_pp DOUBLE, is_synthetic BOOLEAN'
);

-- gold_customer_credit_facts: UN registro por cliente, SIN filtro de marketing.
-- Reemplaza el uso de gold_customer_eligibility_summary para el chat. Entrega HECHOS; la decision de elegibilidad
-- la toma el motor versionado (policy/credit_policy.yaml), no una columna booleana de esta tabla.
--
-- Correcciones respecto a la version del handoff:
--   1. Sin `where accepts_marketing = true`: el consentimiento es una columna, y solo gobierna ofertas PROACTIVAS.
--   2. Montos de varias monedas se convierten a la moneda del ingreso (ASOF) antes de sumar.
--   3. Fecha de corte fija (as_of_date) en vez de current_date: la antiguedad es reproducible.
--   4. Mora medida sobre productos NO cerrados (los cerrados no representan deuda vigente).
--   5. Cuota mensual estimada de deudas existentes (el dataset no trae cuotas) con supuestos explicitos en `params`.
--   6. Nulos de score/ingreso se conservan como NULL (el consumidor los trata como "datos faltantes").
-- En dbt: reemplazar `params` por {{ var('...') }} y las vistas vw_*/silver_* por {{ ref('...') }}.

create or replace view gold_customer_credit_facts as
with params as (
    select date '2026-06-17' as as_of_date,
           0.05  as card_min_payment_pct,       -- supuesto: cuota minima de tarjeta = 5% del saldo
           36    as personal_loan_months_left,  -- supuesto
           180   as mortgage_months_left        -- supuesto
),
cust as (
    select cu.*,
           case cu.country when 'Mexico' then 'MXN' when 'México' then 'MXN' when 'Colombia' then 'COP' when 'Argentina' then 'ARS' end as income_ccy
    from vw_customers cu
),
-- tipo de cambio vigente a la fecha de corte para cada par (origen -> moneda del ingreso)
fx as (
    select source_currency, target_currency, exchange_rate
    from vw_exchange_rates, params
    where date = (select max(date) from vw_exchange_rates where date <= params.as_of_date)
),
credit_products as (
    select p.customer_id, p.product_type, p.product_status, p.days_past_due, p.interest_rate, p.credit_limit,
           p.current_balance * coalesce(case when p.currency = c.income_ccy then 1.0 end, f.exchange_rate) as balance_in_income_ccy,
           p.credit_limit    * coalesce(case when p.currency = c.income_ccy then 1.0 end, f.exchange_rate) as limit_in_income_ccy
    from silver_products p
    join cust c using (customer_id)
    left join fx f on f.source_currency = p.currency and f.target_currency = c.income_ccy
    where p.product_type in ('Tarjeta Credito', 'Prestamo Personal', 'Prestamo Hipotecario')
),
debt as (
    select cp.customer_id,
           sum(case
                 when cp.product_type = 'Tarjeta Credito' then cp.balance_in_income_ccy * pr.card_min_payment_pct
                 -- prestamo: cuota francesa, con tasa 0 el denominador se anula, se usa saldo / meses
                 when coalesce(cp.interest_rate, 0) = 0 then cp.balance_in_income_ccy /
                      (case when cp.product_type = 'Prestamo Personal' then pr.personal_loan_months_left else pr.mortgage_months_left end)
                 else cp.balance_in_income_ccy * (cp.interest_rate / 1200.0)
                      / (1 - power(1 + cp.interest_rate / 1200.0,
                                   -(case when cp.product_type = 'Prestamo Personal' then pr.personal_loan_months_left else pr.mortgage_months_left end)))
               end) filter (where cp.product_status = 'Active') as existing_monthly_debt_est,
           max(cp.days_past_due) filter (where cp.product_status <> 'Cerrado' and cp.product_status <> 'Closed') as max_days_past_due_open,
           sum(cp.limit_in_income_ccy)   filter (where cp.product_type = 'Tarjeta Credito' and cp.product_status = 'Active') as cc_limit_in_income_ccy,
           sum(cp.balance_in_income_ccy) filter (where cp.product_type = 'Tarjeta Credito' and cp.product_status = 'Active') as cc_balance_in_income_ccy
    from credit_products cp, params pr
    group by cp.customer_id
),
prod_counts as (
    select customer_id, count(*) filter (where product_status = 'Active') as active_products
    from silver_products group by customer_id
)
select c.customer_id, c.country, c.segment, c.customer_status, c.credit_score, c.estimated_monthly_income as monthly_income,
       c.income_ccy, c.accepts_marketing,
       datediff('day', c.registration_date, pr.as_of_date) as customer_tenure_days,
       coalesce(pc.active_products, 0) as active_products,
       coalesce(d.existing_monthly_debt_est, 0) as existing_monthly_debt_est,
       coalesce(d.max_days_past_due_open, 0) as max_days_past_due_open,
       case when d.cc_limit_in_income_ccy > 0 then round(d.cc_balance_in_income_ccy / d.cc_limit_in_income_ccy, 4) end as credit_card_utilization_ratio,
       coalesce(cm.critical_cases, 0) as critical_complaints_total,
       coalesce(cm.open_cases, 0) as open_complaints
from cust c
cross join params pr
left join debt d using (customer_id)
left join prod_counts pc using (customer_id)
left join gold_customer_complaints_summary cm using (customer_id);

-- Candidatos a oferta PROACTIVA = hechos + consentimiento. Es una lista de contacto posible, NO una aprobacion:
-- el backend vuelve a evaluar con el motor de politica y con el momento de la conversacion antes de ofrecer.
create or replace view gold_proactive_offer_candidates as
select * from gold_customer_credit_facts
where accepts_marketing = true and customer_status = 'Active';

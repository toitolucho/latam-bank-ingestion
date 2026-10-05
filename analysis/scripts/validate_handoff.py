"""Ejecuta las 3 consultas gold del handoff (DuckDB) sobre los CSV locales y valida grain, nulos y reglas."""
import duckdb
import pandas as pd

pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 40)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import RAW, WORK
D = str(RAW)
con = duckdb.connect()


def view(name, pat):
    con.sql(f"create view {name} as select * from read_csv_auto('{D}/{pat}', union_by_name=true, header=true)")


view("vw_customers", "customers.csv")
view("vw_products", "products.csv")
view("vw_exchange_rates", "daily_exchange_rates.csv")
view("vw_complaints", "complaints/**/*.csv")

# silver_products segun el handoff: strip_accents + TRIM, dedup por product_id (registro mas reciente)
con.sql("""create view silver_products as
select * exclude (rn) from (
  select * replace (trim(strip_accents(product_type)) as product_type,
                    trim(strip_accents(product_status)) as product_status,
                    trim(strip_accents(opening_channel)) as opening_channel),
         row_number() over (partition by product_id order by last_updated desc) rn
  from vw_products) where rn = 1""")

con.sql("""create view gold_customer_products_summary as
select customer_id, count(*) as total_products,
 count(*) filter (where product_status='Active') as active_products,
 sum(credit_limit) as total_credit_limit, sum(current_balance) as total_current_balance,
 round(avg(interest_rate),2) as avg_interest_rate, max(days_past_due) as max_days_past_due,
 max(case when days_past_due>30 then 1 else 0 end) as has_delinquent_product,
 max(case when product_type ilike '%Credito%' or product_type ilike '%Prestamo%' or product_type ilike '%Hipotecario%' then 1 else 0 end) as has_credit_product
from silver_products group by customer_id""")

con.sql("""create view gold_customer_complaints_summary as
with complaints_usd as (
 select c.complaint_id, c.customer_id, c.case_type, c.status, c.priority, c.sla_breached, c.is_repeat_complainer,
  case when c.currency='USD' or c.claimed_amount is null then c.claimed_amount else c.claimed_amount*er_claim.exchange_rate end as claimed_amount_usd
 from vw_complaints c
 asof left join vw_exchange_rates er_claim on er_claim.source_currency=c.currency and er_claim.target_currency='USD'
      and er_claim.date<=cast(c.creation_date as date))
select customer_id, count(*) as total_complaints,
 count(*) filter (where case_type='Claim') as total_claims,
 count(*) filter (where case_type='Complaint') as total_complaints_only,
 count(*) filter (where case_type='Request') as total_requests,
 count(*) filter (where case_type='Suggestion') as total_suggestions,
 count(*) filter (where status in ('Open','In Process','Escalated')) as open_cases,
 count(*) filter (where priority='Critical') as critical_cases,
 (count(*) filter (where sla_breached)>0) as has_sla_breach
from complaints_usd group by customer_id""")

con.sql("""create view gold_customer_eligibility_summary as
with credit_card_usage as (
  select customer_id, sum(credit_limit) as total_cc_limit, sum(current_balance) as total_cc_balance
  from silver_products where product_type='Tarjeta Credito' and product_status='Active' group by customer_id)
select cu.customer_id, cu.segment, cu.customer_status, cu.country, cu.credit_score, cu.estimated_monthly_income,
 cu.registration_date,
 datediff('day', cu.registration_date, current_date) as customer_tenure_days,
 coalesce(p.has_delinquent_product, 0) as has_delinquent_product,
 ccu.total_cc_limit, ccu.total_cc_balance,
 (ccu.total_cc_limit is not null) as has_active_credit_card,
 case when ccu.total_cc_limit>0 then round(ccu.total_cc_balance/ccu.total_cc_limit,4) end as credit_card_utilization_pct,
 coalesce(cm.critical_cases,0) as critical_complaints, cu.accepts_marketing,
 (cu.customer_status='Active' and coalesce(p.has_delinquent_product,0)=0 and coalesce(cm.critical_cases,0)=0
  and cu.credit_score>=600
  and (ccu.total_cc_limit is null or (ccu.total_cc_balance/nullif(ccu.total_cc_limit,0))<=0.70)) as is_eligible_for_new_credit_product
from vw_customers cu
left join gold_customer_products_summary p on p.customer_id=cu.customer_id
left join gold_customer_complaints_summary cm on cm.customer_id=cu.customer_id
left join credit_card_usage ccu on ccu.customer_id=cu.customer_id
where cu.accepts_marketing=true""")


def q(sql):
    return con.sql(sql).df()


def show(title, sql):
    print(f"\n--- {title}")
    print(q(sql).to_string(index=False))


show("grain y tamanos", """select
 (select count(*) from vw_customers) customers, (select count(*) from vw_products) products,
 (select count(*) from silver_products) silver_products, (select count(*) from vw_complaints) complaints,
 (select count(*) from gold_customer_complaints_summary) gold_complaints,
 (select count(*) from gold_customer_eligibility_summary) gold_elig,
 (select count(distinct customer_id) from gold_customer_eligibility_summary) elig_distinct""")
show("requests+suggestions (handoff: 10.045)", "select sum(total_requests) req, sum(total_suggestions) sug, sum(total_complaints) tot from gold_customer_complaints_summary")
show("accepts_marketing en la base de clientes", "select accepts_marketing, count(*) n, round(100.0*count(*)/sum(count(*)) over(),1) pct from vw_customers group by 1")
show("is_eligible_for_new_credit_product (tri-estado)", "select is_eligible_for_new_credit_product e, count(*) n, round(100.0*count(*)/sum(count(*)) over(),1) pct from gold_customer_eligibility_summary group by 1 order by 1")
show("nulos", "select round(100.0*avg((credit_score is null)::int),1) score_null, round(100.0*avg((estimated_monthly_income is null)::int),1) income_null from gold_customer_eligibility_summary")
show("credit_score>=600 entre clientes con score (todos los clientes)", "select round(100.0*avg((credit_score>=600)::int),1) pct_ge_600, round(100.0*avg((credit_score>=700)::int),1) pct_ge_700, count(*) n from vw_customers where credit_score is not null")
show("utilizacion de tarjeta (ratio, no porcentaje)", """select count(*) n, round(avg((credit_card_utilization_pct>1)::int)*100,1) pct_over_1,
 round(median(credit_card_utilization_pct),3) med, round(quantile_cont(credit_card_utilization_pct,0.9),3) p90,
 round(avg((credit_card_utilization_pct>0.7)::int)*100,1) pct_over_70 from gold_customer_eligibility_summary where has_active_credit_card""")
show("clientes con tarjetas activas en >1 moneda (la suma mezcla monedas)", """select count(*) filter (where nc>1) multi_ccy, count(*) with_card,
 round(100.0*count(*) filter (where nc>1)/count(*),1) pct from (select customer_id, count(distinct currency) nc from silver_products
 where product_type='Tarjeta Credito' and product_status='Active' group by 1)""")
show("por pais: tarjetas activas en >1 moneda", """select cu.country, count(*) filter (where nc>1) multi, count(*) n from (select customer_id, count(distinct currency) nc
 from silver_products where product_type='Tarjeta Credito' and product_status='Active' group by 1) t join vw_customers cu using(customer_id) group by 1""")
show("morosos (>30d) marcados solo por productos Cerrados", """select count(*) delinquent, count(*) filter (where only_closed) only_closed from (
 select customer_id, bool_and(product_status='Closed') filter (where days_past_due>30) only_closed
 from silver_products group by 1 having max(days_past_due)>30)""")
show("antiguedad con current_date vs corte del dataset (2026-06-17)", "select current_date today, round(avg(datediff('day', registration_date, current_date)),0) tenure_today, round(avg(datediff('day', registration_date, date '2026-06-17')),0) tenure_asof from vw_customers")
show("duplicados por clave", "select (select count(*)-count(distinct customer_id) from vw_customers) dup_cust, (select count(*)-count(distinct product_id) from vw_products) dup_prod, (select count(*)-count(distinct complaint_id) from vw_complaints) dup_compl")
show("elegibles sin ingreso registrado (la regla no mira ingreso)", "select count(*) filter (where is_eligible_for_new_credit_product) elig, count(*) filter (where is_eligible_for_new_credit_product and estimated_monthly_income is null) elig_sin_ingreso from gold_customer_eligibility_summary")

con.sql(f"copy (select * from gold_customer_eligibility_summary) to '{WORK.as_posix()}/gold_elig_handoff.parquet'")

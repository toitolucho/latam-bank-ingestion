"""Ejecuta sql/gold_customer_credit_facts.sql en DuckDB y lo contrasta con el perfil construido en pandas."""
import re
import sys
from pathlib import Path

import duckdb
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import REPO, WORK
src = (Path(__file__).resolve().parent / "validate_handoff.py").read_text(encoding="utf-8")
# reutiliza las vistas vw_*, silver_products y gold_customer_complaints_summary del script anterior
setup = src.split("def q(sql):")[0]
exec(setup)  # crea `con` con las vistas

sql = (REPO / "data/sql/gold_customer_credit_facts.sql").read_text(encoding="utf-8")
sql = re.sub(r"^--.*$", "", sql, flags=re.M)
for stmt in [s for s in sql.split(";") if s.strip()]:
    con.sql(stmt)

q = lambda s: con.sql(s).df()
pd.set_option("display.width", 200)
print(q("select count(*) n, count(distinct customer_id) distinct_ids, avg(accepts_marketing::int) share_marketing from gold_customer_credit_facts").to_string(index=False))
print(q("select (select count(*) from gold_proactive_offer_candidates) candidates").to_string(index=False))
print(q("""select round(100*avg((credit_score is null)::int),1) score_null, round(100*avg((monthly_income is null)::int),1) income_null,
 round(100*avg((income_ccy is null)::int),1) ccy_null, count(*) filter (where credit_card_utilization_ratio > 1) util_gt_1 from gold_customer_credit_facts""").to_string(index=False))
print(q("select min(customer_tenure_days) mn, round(avg(customer_tenure_days)) avg, max(customer_tenure_days) mx from gold_customer_credit_facts").to_string(index=False))

# contraste contra el perfil de pandas (mismos supuestos y tasa de la ultima fecha)
prof = pd.read_parquet(WORK / "gold_customer_credit_profile.parquet")[
    ["customer_id", "existing_monthly_debt", "max_days_past_due", "n_active_products"]]
sqlf = q("select customer_id, existing_monthly_debt_est, max_days_past_due_open, active_products from gold_customer_credit_facts")
j = prof.merge(sqlf, on="customer_id")
diff_debt = (j.existing_monthly_debt - j.existing_monthly_debt_est).abs()
print("\ncontraste SQL vs pandas")
print("clientes comparados:", len(j))
print("deuda mensual: diferencia maxima = %.6f | clientes con diferencia > 0.01: %d" % (diff_debt.max(), (diff_debt > 0.01).sum()))
print("mora: coincide en %.2f%% (pandas incluye cualquier estado != Closed)" % (100 * (j.max_days_past_due == j.max_days_past_due_open).mean()))
print("productos activos: coincide en %.2f%%" % (100 * (j.n_active_products == j.active_products).mean()))

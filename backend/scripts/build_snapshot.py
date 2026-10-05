"""Construye el snapshot de datos del prototipo (parquet) a partir del dataset del organizador.

Uso:  python backend/scripts/build_snapshot.py --customers 400
Requiere las tablas del organizador (HACKATHON_RAW_DIR) y los parquet derivados de analysis/ (HACKATHON_WORK_DIR).
El resultado NO se versiona (backend/data/snapshot/ esta en .gitignore); el repo lleva un conjunto de ejemplo propio.

Salida: backend/data/snapshot/{customers,products,branches,transactions,fx_rates,case_context}.parquet
Todo es dato sintetico del organizador. Se toma una muestra estratificada de clientes que tienen
datos suficientes para las preguntas de seguridad (productos activos y movimientos recientes).
"""
from __future__ import annotations

import argparse
import hashlib
import os
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from case_context import WINDOW_DAYS, derive_case_context

REPO = Path(__file__).resolve().parents[2]
RAW = Path(os.environ.get("HACKATHON_RAW_DIR", REPO / ".local" / "raw"))
WORK = Path(os.environ.get("HACKATHON_WORK_DIR", REPO / ".local" / "derived"))
OUT = Path(__file__).resolve().parents[1] / "data" / "snapshot"
TX_PER_CUSTOMER = 40
SEED = 42
AS_OF = date(2026, 6, 17)   # igual que Settings.as_of_date: ultimo dia de datos del dataset


def build_case_context(customer_ids: set[str], as_of: date) -> None:
    """Casos abiertos de los clientes del snapshot (ver scripts/case_context.py)."""
    comp = pd.read_parquet(WORK / "complaints.parquet", columns=[
        "complaint_id", "creation_date", "customer_id", "case_type", "category", "reception_channel",
        "origin_interaction_id", "priority", "status", "sla_breached", "is_repeat_complainer"])
    inter = pd.read_parquet(WORK / "call_center_interactions.parquet", columns=[
        "interaction_id", "interaction_date", "customer_id", "channel", "reason_category", "was_resolved",
        "requires_followup", "was_escalated", "detected_sentiment"])
    ctx = derive_case_context(comp[comp.customer_id.isin(customer_ids)], inter[inter.customer_id.isin(customer_ids)], as_of)
    ctx.to_parquet(OUT / "case_context.parquet", index=False)
    print(f"case_context: filas={len(ctx)} clientes_con_casos={ctx.customer_id.nunique()} de {len(customer_ids)} "
          f"(corte {as_of}, ventana {WINDOW_DAYS} dias)")


def add_profile_fields() -> None:
    """Agrega ocupacion y fecha de registro al snapshot EXISTENTE (preguntas de seguridad) sin cambiar su muestra de clientes."""
    path = OUT / "customers.parquet"
    snap = pd.read_parquet(path).drop(columns=["occupation", "registration_date"], errors="ignore")
    raw = pd.read_csv(RAW / "customers.csv", encoding="utf-8-sig", usecols=["customer_id", "occupation", "registration_date"])
    out = snap.merge(raw, on="customer_id", how="left")
    out.to_parquet(path, index=False)
    print(f"customers.parquet: ocupacion en {out.occupation.notna().mean():.0%} y fecha de registro en "
          f"{out.registration_date.notna().mean():.0%} de {len(out)} clientes")


def main(n_customers: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cu = pd.read_csv(RAW / "customers.csv", encoding="utf-8-sig")
    pr = pd.read_csv(RAW / "products.csv", encoding="utf-8-sig")
    br = pd.read_csv(RAW / "branches.csv", encoding="utf-8-sig")
    gold = pd.read_parquet(WORK / "gold_customer_credit_profile.parquet")
    tx = pd.read_parquet(
        WORK / "transactions.parquet",
        columns=["transaction_id", "transaction_date", "customer_id", "product_id", "transaction_type",
                 "amount", "currency", "channel", "merchant_name", "transaction_city",
                 "transaction_country", "transaction_status"],
    )

    # Normalizacion minima (silver): el pais de transacciones mezcla "Mexico"/"México"
    for df, col in ((cu, "country"), (tx, "transaction_country")):
        df[col] = df[col].replace({"Mexico": "México"})

    tx = tx[(tx.transaction_status == "Approved") & tx.transaction_city.notna()
            & tx.transaction_type.isin(["Purchase", "Withdrawal"])].copy()
    tx["transaction_date"] = pd.to_datetime(tx.transaction_date)
    tx["amount"] = pd.to_numeric(tx.amount)

    # Un mismo (cliente, tipo, dia) debe ser unico: la pregunta de seguridad nombra tipo + fecha.
    tx["day"] = tx.transaction_date.dt.date
    tx = tx.sort_values("transaction_date", ascending=False)
    tx = tx.drop_duplicates(["customer_id", "transaction_type", "day"], keep=False)

    active = pr[pr.product_status == "Active"]
    elig = (
        cu[(cu.customer_status == "Active") & cu.customer_id.isin(active.customer_id)]
        .merge(tx.groupby("customer_id").size().rename("n_tx"), left_on="customer_id", right_index=True)
        .query("n_tx >= 6")
    )
    # Estratificado por pais y por disponibilidad de datos de credito para ejercitar todos los caminos.
    elig = elig.merge(gold[["customer_id", "credit_score", "monthly_income"]], on="customer_id", suffixes=("_c", ""))
    elig["has_credit_data"] = elig.credit_score.notna() & elig.monthly_income.notna()
    rng = np.random.default_rng(SEED)
    parts = []
    for (country, ok), g in elig.groupby(["country", "has_credit_data"]):
        share = 0.7 if ok else 0.3
        k = max(1, int(n_customers * share * len(g) / max(len(elig[elig.country == country]), 1) / 3))
        parts.append(g.sample(min(k, len(g)), random_state=int(rng.integers(1e6))))
    pick = pd.concat(parts).drop_duplicates("customer_id")
    ids = set(pick.customer_id)

    customers = (
        cu[cu.customer_id.isin(ids)][["customer_id", "document_type", "document_number", "first_name",
                                      "country", "segment", "customer_status", "accepts_marketing", "email",
                                      "occupation", "registration_date"]]   # ocupacion y ano de alta: preguntas de seguridad
        .merge(gold[["customer_id", "credit_score", "monthly_income", "existing_monthly_debt",
                     "max_days_past_due", "n_active_products", "income_ccy"]], on="customer_id")
    )
    # Documentos que el banco "ya tiene": el dataset no los trae, asi que se INVENTAN de forma determinista por cliente
    # (hash del id). La identidad siempre; comprobante de domicilio en ~60%; de ingresos en ~25%.
    def docs(cid: str) -> str:
        h = hashlib.sha256(cid.encode()).digest()
        out = ["id_copy"] + (["address_proof"] if h[0] < 153 else []) + (["income_proof"] if h[1] < 64 else [])
        return ",".join(sorted(out))

    customers["docs_on_file"] = customers.customer_id.map(docs)
    products = active[active.customer_id.isin(ids)][
        ["product_id", "customer_id", "product_type", "product_number", "currency", "opening_date",
         "opening_branch_id", "opening_channel", "product_status"]
    ].copy()
    products["last4"] = products.product_number.astype(str).str[-4:]
    branches = br[["branch_id", "branch_name", "city", "state", "country"]].copy()
    branches["country"] = branches.country.replace({"Mexico": "México"})
    txs = (
        tx[tx.customer_id.isin(ids)].sort_values("transaction_date", ascending=False)
        .groupby("customer_id").head(TX_PER_CUSTOMER)
        [["transaction_id", "customer_id", "product_id", "transaction_date", "transaction_type", "amount",
          "currency", "merchant_name", "transaction_city", "transaction_country"]]
    )

    # Tasas de referencia del dataset a su ultima fecha (una fila por par de monedas)
    fx_all = pd.read_csv(RAW / "daily_exchange_rates.csv", encoding="utf-8-sig")
    fx = fx_all[fx_all.date == fx_all.date.max()][["date", "source_currency", "target_currency", "exchange_rate"]]
    fx.to_parquet(OUT / "fx_rates.parquet", index=False)
    customers.to_parquet(OUT / "customers.parquet", index=False)
    products.to_parquet(OUT / "products.parquet", index=False)
    branches.to_parquet(OUT / "branches.parquet", index=False)
    txs.to_parquet(OUT / "transactions.parquet", index=False)
    build_case_context(ids, AS_OF)
    print(f"customers={len(customers)} products={len(products)} branches={len(branches)} transactions={len(txs)}")
    print("por pais:", customers.country.value_counts().to_dict())
    print("sin datos de credito completos:", int((customers.credit_score.isna() | customers.monthly_income.isna()).sum()))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--customers", type=int, default=400)
    ap.add_argument("--case-context-only", action="store_true",
                    help="solo regenera case_context.parquet para los clientes del snapshot existente (no toca el resto)")
    ap.add_argument("--profile-only", action="store_true",
                    help="solo agrega ocupacion y fecha de registro al customers.parquet existente (no cambia la muestra)")
    args = ap.parse_args()
    if args.profile_only:
        add_profile_fields()
    elif args.case_context_only:
        OUT.mkdir(parents=True, exist_ok=True)
        build_case_context(set(pd.read_parquet(OUT / "customers.parquet").customer_id), AS_OF)
    else:
        main(args.customers)

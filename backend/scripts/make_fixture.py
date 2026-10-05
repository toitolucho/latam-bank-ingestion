"""Genera el conjunto de ejemplo del equipo (backend/data/fixture/*.parquet).

TODO ES INVENTADO POR EL EQUIPO con una semilla fija: no se deriva de ningun dato del organizador. Existe para que quien
clone el repositorio pueda ejecutar el backend, las pruebas y el CI sin acceso al bucket. Tiene la misma forma que el
snapshot derivado del dataset (ver scripts/build_snapshot.py) y cubre cada escenario de la politica.

Uso:  python scripts/make_fixture.py
"""
from __future__ import annotations

import random
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parents[1] / "data" / "fixture"
AS_OF = date(2026, 6, 17)
SEED = 7
rng = random.Random(SEED)
extra = random.Random(SEED + 101)   # campos agregados despues: generador aparte para no alterar los datos previos
nrng = np.random.default_rng(SEED)

CITIES = {
    "México": ["Ciudad de México", "Guadalajara", "Monterrey", "Puebla", "Tijuana", "Querétaro"],
    "Colombia": ["Bogotá", "Medellín", "Cali", "Barranquilla", "Cartagena"],
    "Argentina": ["Buenos Aires", "Córdoba", "Rosario", "Mendoza", "La Plata"],
}
CCY = {"México": "MXN", "Colombia": "COP", "Argentina": "ARS"}
DOC_TYPE = {"México": "DNI", "Colombia": "CC", "Argentina": "DNI"}
NAMES = ["Alicia", "Bruno", "Carla", "Daniel", "Elena", "Felipe", "Gabriela", "Héctor", "Inés", "Joaquín", "Karina",
         "Lucas", "Marisol", "Nicolás", "Olivia", "Pablo", "Renata", "Santiago", "Teresa", "Valentín", "Ximena", "Yago"]
MERCHANTS = ["Super Ahorro", "Mercado Central", "Tienda del Barrio", "Restaurante La Esquina", "Farmacia Salud", "Cine Centro"]
PRODUCTS = ["Cuenta Ahorro", "Cuenta Corriente", "Tarjeta Débito", "Tarjeta Crédito"]

# (pais, consentimiento, score, ingreso, ratio de deuda actual, mora maxima, con movimientos)
# Cada fila existe para ejercitar un camino de la politica o de la oferta proactiva.
SPEC = [
    ("México", True, 740, 95_000, 0.03, 0, True), ("México", True, 690, 62_000, 0.05, 0, True),
    ("México", False, 756, 80_000, 0.02, 0, True), ("México", False, 640, 52_000, 0.04, 0, True),
    ("México", False, 790, None, 0.0, 0, True), ("México", True, 675, 103_000, 0.03, 120, True),
    ("México", True, 502, 44_000, 0.0, 0, True), ("México", False, 619, 25_000, 0.45, 0, True),
    ("México", False, 658, 70_000, 0.03, 45, True), ("México", True, 720, 88_000, 0.02, 0, False),
    ("Colombia", True, 613, 10_500_000, 0.03, 0, True), ("Colombia", True, 700, 7_200_000, 0.04, 0, True),
    ("Colombia", False, 640, 5_800_000, 0.05, 0, True), ("Colombia", True, None, 9_000_000, 0.02, 0, True),
    ("Colombia", False, 800, None, 0.0, 0, True), ("Colombia", True, 580, 6_000_000, 0.03, 0, True),
    ("Argentina", True, 565, 586_000, 0.03, 0, True), ("Argentina", True, 720, 1_900_000, 0.04, 0, True),
    ("Argentina", False, 554, 575_000, 0.02, 0, True), ("Argentina", True, 658, 3_500_000, 0.03, 90, True),
    ("Argentina", True, 700, None, 0.0, 0, True),
]


def month_start(d: date) -> date:
    return d.replace(day=1)


OCCUPATIONS = ["Accountant", "Administrative", "Artist", "Consultant", "Director", "Doctor", "Driver", "Employee", "Engineer",
               "Entrepreneur", "Homemaker", "Independent Professional", "Lawyer", "Manager", "Merchant", "Retired",
               "Salesperson", "Student", "Teacher", "Technician"]
NO_DATA_CUSTOMER = "FXC-010"      # el cliente al que le faltan datos para el reto de seguridad (escenario I), a proposito


def add_security_question_data(customers: list[dict], products: list[dict]) -> None:
    """Ocupacion y fecha de registro INVENTADAS (generador propio: no altera los demas datos) y garantia de que cada cliente
    tiene un producto abierto en sucursal, salvo NO_DATA_CUSTOMER (sin ocupacion y sin productos abiertos en sucursal: solo
    puede recibir 2 tipos de pregunta, asi que no se le puede verificar por este canal)."""
    prof = random.Random(SEED + 303)
    for c in customers:
        year = prof.randrange(2018, 2026)
        c["registration_date"] = datetime(year, prof.randrange(1, 13), prof.randrange(1, 28), 10, 0, 0).isoformat(sep=" ")
        c["occupation"] = None if c["customer_id"] == NO_DATA_CUSTOMER else prof.choice(OCCUPATIONS)
    seen: set[str] = set()
    for p in products:
        cid = p["customer_id"]
        if cid == NO_DATA_CUSTOMER:
            p["opening_channel"] = "App" if p["opening_channel"] == "Branch" else p["opening_channel"]
        elif cid not in seen:
            p["opening_channel"] = "Branch"          # el primero de cada cliente: ciudad de apertura recordable
        seen.add(cid)


# (cliente, origen, categoria, tipo, prioridad, estado, dias abierto, escalado, SLA incumplido, sentimiento, reincidente, canal)
# Cada fila ejercita un camino de la conversacion: caso pendiente, caso critico, enojo previo, caso viejo, varios casos.
# FXC-001 queda sin casos a proposito: es el cliente "limpio" (preaprobado, con consentimiento) de varias pruebas.
CASES = [
    (11, "complaint", "Fees", "Complaint", "High", "In Process", 12, False, False, None, False, "App"),
    (2, "complaint", "Transactions", "Claim", "Critical", "Escalated", 31, True, True, None, True, "Call Center"),
    (2, "interaction", "Queja", None, None, "Unresolved", 9, True, False, "Muy Negativo", False, "Phone"),
    (3, "interaction", "Queja", None, None, "Unresolved", 20, False, False, "Negativo", False, "Phone"),
    (4, "interaction", "Transaccional", None, None, "Unresolved", 45, True, False, "Neutral", False, "Web Chat"),
    (5, "complaint", "Service", "Complaint", "Low", "Open", 400, False, False, None, False, "Branch"),   # viejo: no se menciona al saludar
    (6, "complaint", "Technical", "Request", "Medium", "Open", 6, False, False, None, False, "Web"),
    (6, "interaction", "Técnico", None, None, "Unresolved", 3, False, False, "Neutral", False, "WhatsApp"),
]


def make_case_context() -> pd.DataFrame:
    """Casos abiertos INVENTADOS (misma forma que scripts/case_context.py). Generador propio: no altera el resto."""
    r = random.Random(SEED + 202)
    rows = []
    for n, (i, src, cat, ctype, prio, status, days, esc, sla, sent, rep, chan) in enumerate(CASES, start=1):
        opened = AS_OF - timedelta(days=days)
        rows.append({
            "customer_id": f"FXC-{i:03d}", "case_source": src,
            "case_id": f"FXK-{n:03d}-{r.randrange(1000, 9999)}", "opened_on": opened.isoformat(), "days_open": days,
            "channel": chan, "category": cat, "case_type": ctype, "priority": prio, "status": status,
            "is_escalated": esc, "sla_breached": sla, "sentiment": sent, "is_repeat_complainer": rep,
            "as_of_date": AS_OF.isoformat(),
        })
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    branches = []
    for country, cities in CITIES.items():
        for city in cities:
            for k in range(3):
                branches.append({"branch_id": f"FXS-{country[:2].upper()}-{len(branches):03d}", "branch_name": f"{city} {k + 1}",
                                 "city": city, "state": city, "country": country})
    br_by_country = {c: [b for b in branches if b["country"] == c] for c in CITIES}

    used_docs: set[str] = set()
    customers, products, txs = [], [], []
    for i, (country, consent, score, income, debt_ratio, dpd, with_tx) in enumerate(SPEC, start=1):
        cid = f"FXC-{i:03d}"
        doc = f"{rng.randrange(10_000_000, 99_999_999)}"
        while doc in used_docs:
            doc = f"{rng.randrange(10_000_000, 99_999_999)}"
        used_docs.add(doc)
        ccy = CCY[country]
        home = rng.choice(CITIES[country])

        n_prod = rng.choice([3, 3, 4])
        types = rng.sample(PRODUCTS, k=n_prod)
        months = rng.sample(range(0, 90), k=n_prod)      # meses de apertura distintos entre 2018-06 y 2025-12
        last4s = rng.sample(range(1000, 9999), k=n_prod)
        cust_products = []
        for t, m, l4 in zip(types, months, last4s):
            y, mo = divmod(2018 * 12 + 5 + m, 12)
            opening = date(y, mo + 1, rng.randrange(1, 28))
            br = rng.choice(br_by_country[country])
            pid = f"FXP-{i:03d}-{l4}"
            cust_products.append(pid)
            products.append({"product_id": pid, "customer_id": cid, "product_type": t, "product_number": f"{rng.randrange(10**11, 10**12 - 1)}{l4}",
                             "currency": ccy, "opening_date": opening.isoformat(), "opening_branch_id": br["branch_id"],
                             "opening_channel": rng.choice(["Branch", "App", "Web"]), "product_status": "Active", "last4": str(l4)})

        customers.append({
            "customer_id": cid, "document_type": DOC_TYPE[country], "document_number": doc,
            "first_name": rng.choice(NAMES), "country": country, "segment": rng.choice(["Basic", "Plus", "Premium"]),
            "customer_status": "Active", "accepts_marketing": consent,
            "credit_score": float(score) if score is not None else np.nan,
            "monthly_income": float(income) if income is not None else np.nan,
            "existing_monthly_debt": float(income * debt_ratio) if income else 0.0,
            "max_days_past_due": dpd, "n_active_products": n_prod, "income_ccy": ccy,
        })

        # Correo (dominio reservado example.com) y documentos que el banco ya tiene. El primer cliente tiene todos
        # (camino directo a un asesor); el segundo, solo la identidad; el resto, al azar.
        base = unicodedata.normalize("NFKD", customers[-1]["first_name"]).encode("ascii", "ignore").decode().lower()
        on_file = ["id_copy"]
        if i == 1:
            on_file += ["address_proof", "income_proof"]
        elif i > 2:
            on_file += [d for d, pr in (("address_proof", 0.6), ("income_proof", 0.25)) if extra.random() < pr]
        customers[-1]["email"] = f"{base}{i}@example.com"
        customers[-1]["docs_on_file"] = ",".join(sorted(on_file))

        if with_tx:
            seen: set[tuple[str, date]] = set()
            scale = (income or 1_000) / 40
            for _ in range(rng.randrange(8, 13)):
                for _try in range(20):
                    day = AS_OF - timedelta(days=rng.randrange(3, 330))
                    ttype = rng.choice(["Purchase", "Purchase", "Withdrawal"])
                    if (ttype, day) not in seen:
                        seen.add((ttype, day))
                        break
                city = home if rng.random() < 0.8 else rng.choice(CITIES[country])
                txs.append({"transaction_id": f"FXT-{len(txs):05d}", "customer_id": cid, "product_id": rng.choice(cust_products),
                            "transaction_date": datetime(day.year, day.month, day.day, rng.randrange(8, 22), rng.randrange(60)),
                            "transaction_type": ttype, "amount": round(float(nrng.lognormal(mean=np.log(scale), sigma=0.6)), 2),
                            "currency": ccy, "merchant_name": rng.choice(MERCHANTS) if ttype == "Purchase" else None,
                            "transaction_city": city, "transaction_country": country})

    add_security_question_data(customers, products)
    pd.DataFrame(customers).to_parquet(OUT / "customers.parquet", index=False)
    pd.DataFrame(products).to_parquet(OUT / "products.parquet", index=False)
    pd.DataFrame(branches).to_parquet(OUT / "branches.parquet", index=False)
    pd.DataFrame(txs).to_parquet(OUT / "transactions.parquet", index=False)
    # Tasas de referencia INVENTADAS por el equipo (la forma del dataset: una fila por par de monedas y fecha de corte).
    usd = {"MXN": 17.30, "COP": 4000.0, "ARS": 350.0}
    fx = []
    for a in ["USD", "MXN", "COP", "ARS"]:
        for b in ["USD", "MXN", "COP", "ARS"]:
            if a != b:
                rate = (usd.get(b, 1.0) / usd.get(a, 1.0))
                fx.append({"date": AS_OF.isoformat(), "source_currency": a, "target_currency": b, "exchange_rate": rate})
    pd.DataFrame(fx).to_parquet(OUT / "fx_rates.parquet", index=False)
    cases = make_case_context()
    cases.to_parquet(OUT / "case_context.parquet", index=False)
    print(f"fixture: casos abiertos={len(cases)} en {cases.customer_id.nunique()} clientes")
    print(f"fixture: clientes={len(customers)} productos={len(products)} sucursales={len(branches)} movimientos={len(txs)} -> {OUT}")


if __name__ == "__main__":
    main()

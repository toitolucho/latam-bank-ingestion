"""Acceso a datos del prototipo. Lee un snapshot parquet (capa gold exportada).

La interfaz `CustomerRepository` es el punto de reemplazo: en produccion seria un SQL Warehouse
con filtros por fila; el resto del sistema no cambia.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pandas as pd


@dataclass(frozen=True)
class Customer:
    customer_id: str
    document_type: str
    document_number: str
    first_name: str
    country: str
    segment: str
    customer_status: str


@dataclass(frozen=True)
class FxQuote:
    """Tasa de referencia: 1 unidad de `source` = `rate` unidades de `target`, a la fecha de corte `as_of`."""
    source: str
    target: str
    rate: float
    as_of: str


class CustomerRepository(Protocol):
    def find_by_document(self, document_number: str) -> Customer | None: ...
    def credit_profile(self, customer_id: str) -> dict: ...
    def products(self, customer_id: str) -> list[dict]: ...
    def recent_transactions(self, customer_id: str, limit: int = 40) -> list[dict]: ...
    def branch_cities(self, country: str | None = None) -> list[str]: ...
    def branch_city(self, branch_id: str) -> str | None: ...
    def branch_country(self, branch_id: str) -> str | None: ...
    def branch_countries(self) -> list[str]: ...
    def profile_facts(self, customer_id: str) -> dict: ...
    def random_customer_id(self, rng) -> str: ...
    def fx_rate(self, source: str, target: str) -> FxQuote | None: ...
    def contact_email_masked(self, customer_id: str) -> str | None: ...
    def documents_on_file(self, customer_id: str) -> set[str]: ...
    def case_context(self, customer_id: str) -> list[dict]: ...
    def product_overview(self, customer_id: str) -> list[dict]: ...


# Lo unico que el agente puede saber de un caso abierto y de un producto. Es una lista blanca a proposito: el chat solo
# confirma que existen y los deriva; nunca detalla saldos, limites, montos reclamados ni descripciones.
CASE_FIELDS = ("case_source", "case_id", "opened_on", "days_open", "channel", "category", "case_type", "priority", "status",
               "is_escalated", "sla_breached", "sentiment", "is_repeat_complainer")
PRODUCT_FIELDS = ("product_type", "last4", "product_status")


def _clean(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if v is pd.NaT:
        return None
    return v


class SnapshotRepository:
    def __init__(self, data_dir: Path):
        self._customers = pd.read_parquet(data_dir / "customers.parquet")
        self._products = pd.read_parquet(data_dir / "products.parquet")
        self._branches = pd.read_parquet(data_dir / "branches.parquet")
        self._tx = pd.read_parquet(data_dir / "transactions.parquet")
        self._by_doc = {str(r.document_number): r.customer_id for r in self._customers.itertuples()}
        self._cust = self._customers.set_index("customer_id")
        self._branch_city = dict(zip(self._branches.branch_id, self._branches.city))
        self._branch_country = dict(zip(self._branches.branch_id, self._branches.country))
        self._cities = sorted(set(self._branches.city.dropna()))
        self._cities_by_country = {c: sorted(set(g.city.dropna())) for c, g in self._branches.groupby("country")}
        self._prod_by_c = {k: g for k, g in self._products.groupby("customer_id")}
        self._tx_by_c = {k: g.sort_values("transaction_date", ascending=False)
                         for k, g in self._tx.groupby("customer_id")}
        # Tasas de cambio (opcional): sin el archivo, el agente avisa que no puede convertir monedas.
        self._fx: dict[tuple[str, str], tuple[float, str]] = {}
        fx_path = data_dir / "fx_rates.parquet"
        if fx_path.exists():
            for r in pd.read_parquet(fx_path).itertuples():
                self._fx[(r.source_currency, r.target_currency)] = (float(r.exchange_rate), str(r.date)[:10])
        # Casos abiertos por cliente (opcional): sin el archivo, el agente simplemente no tiene historial pendiente.
        self._cases: dict[str, list[dict]] = {}
        cases_path = data_dir / "case_context.parquet"
        if cases_path.exists():
            for cid, g in pd.read_parquet(cases_path).groupby("customer_id"):
                self._cases[cid] = [{k: _clean(v) for k, v in rec.items()} for rec in g[list(CASE_FIELDS)].to_dict("records")]

    def find_by_document(self, document_number: str) -> Customer | None:
        cid = self._by_doc.get(str(document_number).strip())
        if cid is None:
            return None
        r = self._cust.loc[cid]
        return Customer(cid, r.document_type, str(r.document_number), r.first_name, r.country,
                        r.segment, r.customer_status)

    def credit_profile(self, customer_id: str) -> dict:
        r = self._cust.loc[customer_id]
        return {
            "customer_status": r.customer_status,
            "credit_score": _clean(r.credit_score),
            "monthly_income": _clean(r.monthly_income),
            "existing_monthly_debt": _clean(r.existing_monthly_debt) or 0.0,
            "max_days_past_due": int(_clean(r.max_days_past_due) or 0),
            "n_active_products": int(_clean(r.n_active_products) or 0),
            "income_ccy": r.income_ccy,
            "country": r.country,
            # Consentimiento de marketing: SOLO gobierna ofertas proactivas, nunca la respuesta a una solicitud del cliente.
            "accepts_marketing": bool(r.accepts_marketing),
        }

    def products(self, customer_id: str) -> list[dict]:
        g = self._prod_by_c.get(customer_id)
        return [] if g is None else g.to_dict("records")

    def recent_transactions(self, customer_id: str, limit: int = 40) -> list[dict]:
        g = self._tx_by_c.get(customer_id)
        return [] if g is None else g.head(limit).to_dict("records")

    def branch_cities(self, country: str | None = None) -> list[str]:
        """Ciudades con sucursal; con `country`, solo las de ese pais (los distractores de una pregunta deben salir de ahi)."""
        return self._cities if country is None else list(self._cities_by_country.get(country, []))

    def branch_city(self, branch_id: str) -> str | None:
        return self._branch_city.get(branch_id)

    def branch_country(self, branch_id: str) -> str | None:
        return self._branch_country.get(branch_id)

    def branch_countries(self) -> list[str]:
        return sorted(self._cities_by_country)

    def profile_facts(self, customer_id: str) -> dict:
        """Datos de perfil que usan las preguntas de seguridad: ocupacion registrada y ano de alta (None si no hay)."""
        r = self._cust.loc[customer_id]
        occupation = _clean(r.occupation) if "occupation" in self._cust.columns else None
        reg = _clean(r.registration_date) if "registration_date" in self._cust.columns else None
        try:
            year = int(pd.Timestamp(reg).year) if reg is not None else None
        except (ValueError, TypeError):
            year = None
        return {"occupation": str(occupation) if occupation else None, "registration_year": year}

    def random_customer_id(self, rng) -> str:
        """Un cliente cualquiera, para que el reto senuelo tenga la misma forma que los reales."""
        return self._customers.customer_id.iloc[rng.randrange(len(self._customers))]

    def fx_rate(self, source: str, target: str) -> FxQuote | None:
        """Tasa directa del dataset o, si falta el par, triangulada por USD. None si no hay datos."""
        if source == target:
            return FxQuote(source, target, 1.0, "")
        if (source, target) in self._fx:
            rate, as_of = self._fx[(source, target)]
            return FxQuote(source, target, rate, as_of)
        a, b = self._fx.get((source, "USD")), self._fx.get(("USD", target))
        if a and b:
            return FxQuote(source, target, a[0] * b[0], min(a[1], b[1]))
        return None

    def contact_email_masked(self, customer_id: str) -> str | None:
        """Correo registrado, enmascarado (j***@dominio). La direccion completa nunca sale de esta capa."""
        if "email" not in self._cust.columns:
            return None
        email = _clean(self._cust.loc[customer_id].email)
        if not email or "@" not in str(email):
            return None
        local, domain = str(email).split("@", 1)
        return f"{local[:1]}***@{domain}"

    def documents_on_file(self, customer_id: str) -> set[str]:
        """Documentos del cliente que el banco ya tiene. Sin la columna, solo la identidad (verificada en el chat)."""
        if "docs_on_file" not in self._cust.columns:
            return {"id_copy"}
        raw = _clean(self._cust.loc[customer_id].docs_on_file)
        return {d for d in str(raw).split(",") if d} if raw else set()

    def case_context(self, customer_id: str) -> list[dict]:
        """Casos abiertos del cliente (reclamos abiertos e interacciones sin resolver), solo con CASE_FIELDS."""
        return [dict(c) for c in self._cases.get(customer_id, [])]

    def product_overview(self, customer_id: str) -> list[dict]:
        """Existencia de productos: tipo, terminacion y estado. Nada de saldos, limites ni fechas."""
        return [{k: _clean(p.get(k)) for k in PRODUCT_FIELDS} for p in self.products(customer_id)]

    def sample_documents(self, n: int = 5) -> list[str]:
        """Solo para pruebas y README (datos sinteticos)."""
        return list(self._by_doc)[:n]

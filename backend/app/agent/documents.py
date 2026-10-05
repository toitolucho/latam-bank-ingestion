"""Documentos necesarios para avanzar con una solicitud: que se exige, que ya tiene el banco y que falta.

La lista y las condiciones salen de la politica (required_documents en credit_policy.yaml), no del LLM. El chat no recibe
archivos: el cliente confirma que cuenta con cada documento y un asesor los verifica despues.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.data.repository import CustomerRepository


@dataclass
class DocumentPlan:
    required: list[str]
    on_file: list[str]
    need: list[str] = field(default_factory=list)       # exigidos y que el banco aun no tiene


def required_documents(policy: dict, product: str, income_declared: bool) -> list[str]:
    cfg = policy["required_documents"]
    docs = list(cfg.get(product, cfg["personal_loan"]))
    if income_declared:
        docs += [d for d in cfg.get("if_income_declared", []) if d not in docs]
    return docs


def plan(policy: dict, repo: CustomerRepository, customer_id: str, product: str, income_declared: bool) -> DocumentPlan:
    required = required_documents(policy, product, income_declared)
    have = repo.documents_on_file(customer_id)
    return DocumentPlan(required=required, on_file=[d for d in required if d in have],
                        need=[d for d in required if d not in have])

"""Reference implementation of the credit policy 0.4 (docs/CREDIT_RULES.md) in plain Python.

It mirrors the gold SQL (data/databricks/gold/10 and 20) so the backend rules service can
compute and recompute offers with the same parameters and formulas. Parameters come from
data/reference/*.csv, the source of truth that is also loaded into silver ref_*.

Pure functions, standard library only:
    load_policy()                         read the reference CSVs
    monthly_installment / max_principal   annuity formulas (= gold fn_* and backend pmt/pv)
    offer_options(profile, policy)        baseline options for one customer (= gold options),
                                          with is_featured: the one to present first per product
    recalculate(profile, policy, ...)     profile after data declared in the chat (live recalc)
    build_credit_offer(...)               row for gold credit_offers when the customer accepts

`profile` is a dict with the columns of gold customer_credit_profile (one row). Amounts are
USD; convert local currency with profile["fx_to_usd"] (1 local unit = fx_to_usd USD).
Synthetic policy, offline results: not a real lending decision.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

REFERENCE_DIR = Path(__file__).resolve().parents[1] / "reference"
NEAR_LIMIT_SHARE = 0.19          # F02 fires at or above this debt-to-income on chat-declared income
HARD_FILTERS_FROM_BANK_DATA = ("R01", "R02", "R03", "R04", "R06", "R07")  # cannot change in a chat


def _num(value) -> float | None:
    """None for missing values, including NaN from pandas rows."""
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) else value


# ---------------------------------------------------------------------------------------------
# Policy parameters
# ---------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Policy:
    params: dict
    bands: list            # sorted by min_credit_score descending
    segments: dict         # segment -> rate adjustment pp
    catalog: dict          # product_code -> row
    grid: list             # ref_term_grid rows

    @property
    def max_dti(self) -> float:
        return float(self.params["max_debt_to_income"])

    @property
    def version(self) -> str:
        return self.params["policy_version"]


def _rows(name: str, directory: Path) -> list[dict]:
    with open(directory / f"{name}.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_policy(directory: Path = REFERENCE_DIR) -> Policy:
    params = {r["param_name"]: r["param_value"] for r in _rows("ref_policy_params", directory)}
    bands = [{"band": r["band"], "min_credit_score": int(r["min_credit_score"]),
              "rate_adjustment_pp": float(r["rate_adjustment_pp"]),
              "offer_allowed": r["offer_allowed"].lower() == "true",
              "max_term_personal_loan_months": int(r["max_term_personal_loan_months"]),
              "max_term_mortgage_months": int(r["max_term_mortgage_months"])}
             for r in _rows("ref_policy_bands", directory)]
    segments = {r["segment"]: float(r["rate_adjustment_pp"]) for r in _rows("ref_segment_adjustments", directory)}
    catalog = {r["product_code"]: {"product_code": r["product_code"], "product_type": r["product_type"],
                                   "source_product_type": r["source_product_type"],
                                   "min_amount_usd": float(r["min_amount_usd"]),
                                   "max_amount_usd": float(r["max_amount_usd"]),
                                   "min_rate_pct": float(r["min_rate_pct"]), "max_rate_pct": float(r["max_rate_pct"])}
               for r in _rows("ref_product_catalog", directory)}
    grid = [{"option_code": r["product_code"], "product_type": r["product_type"], "tier": r["tier"] or None,
             "term_months": int(r["term_months"]), "reference_rate_pct": float(r["reference_rate_pct"]),
             "min_amount_usd": float(r["min_amount_usd"]), "max_amount_usd": float(r["max_amount_usd"])}
            for r in _rows("ref_term_grid", directory)]
    return Policy(params, sorted(bands, key=lambda b: -b["min_credit_score"]), segments, catalog, grid)


# ---------------------------------------------------------------------------------------------
# Annuity formulas (identical to gold fn_monthly_installment / fn_max_principal)
# ---------------------------------------------------------------------------------------------
def monthly_installment(principal: float | None, annual_rate_pct: float | None, term_months: int | None) -> float:
    if principal is None or principal <= 0 or not term_months or term_months <= 0:
        return 0.0
    r = (annual_rate_pct or 0) / 1200
    return principal / term_months if r == 0 else principal * r / (1 - (1 + r) ** -term_months)


def max_principal(installment: float | None, annual_rate_pct: float | None, term_months: int | None) -> float:
    if installment is None or installment <= 0 or not term_months or term_months <= 0:
        return 0.0
    r = (annual_rate_pct or 0) / 1200
    return installment * term_months if r == 0 else installment * (1 - (1 + r) ** -term_months) / r


# ---------------------------------------------------------------------------------------------
# Baseline offer options (= gold customer_credit_offer_options)
# ---------------------------------------------------------------------------------------------
def offer_options(profile: dict, policy: Policy) -> list[dict]:
    """One dict per ref_term_grid option. Options are alternatives: each uses the whole capacity."""
    available = max(_num(profile.get("available_installment_usd")) or 0.0, 0.0)
    eligible = bool(profile.get("is_eligible"))
    adjustment = _num(profile.get("total_rate_adjustment_pp")) or 0.0
    out = []
    for g in policy.grid:
        product = g["option_code"].split("-")[0]
        cat = policy.catalog[product]
        if product == "CC":                     # cards: the tier credit limit range
            lo, hi, term_allowed = g["min_amount_usd"], g["max_amount_usd"], True
        else:                                   # loans: whole product range, term up to the band maximum
            lo, hi = cat["min_amount_usd"], cat["max_amount_usd"]
            max_term = _num(profile.get("max_term_personal_loan_months" if product == "PL" else "max_term_mortgage_months")) or 0
            term_allowed = g["term_months"] <= max_term
        rate = min(max(g["reference_rate_pct"] + adjustment, cat["min_rate_pct"]), cat["max_rate_pct"])
        by_capacity = max_principal(available, rate, g["term_months"])
        capped = math.floor(min(by_capacity, hi) / 100) * 100
        is_available = eligible and term_allowed and capped >= lo
        reason = None if is_available else ("customer_not_eligible" if not eligible
                                            else "term_above_band_maximum" if not term_allowed
                                            else "capacity_below_option_minimum")
        installment = round(monthly_installment(capped, rate, g["term_months"]), 2) if is_available else None
        out.append({"option_code": g["option_code"], "product_code": product, "product_type": g["product_type"],
                    "tier": g["tier"], "term_months": g["term_months"], "offer_rate_pct": round(rate, 2),
                    "option_min_amount_usd": lo, "option_max_amount_usd": hi, "term_allowed": term_allowed,
                    "is_available": is_available, "unavailable_reason": reason,
                    "offer_max_amount_usd": capped if is_available else None,
                    "offer_monthly_installment_usd": installment, "is_featured": False})
    _mark_featured(out)
    return out


def _mark_featured(options: list[dict]) -> None:
    """The option to present first per product (= gold is_featured): cards the highest available
    tier, loans the highest amount; ties (several terms at the product maximum) go to the shortest term."""
    best: dict = {}
    for o in options:
        if not o["is_available"]:
            continue
        key = (-o["option_max_amount_usd"], -o["offer_max_amount_usd"], o["term_months"])
        if o["product_code"] not in best or key < best[o["product_code"]][0]:
            best[o["product_code"]] = (key, o)
    for _, o in best.values():
        o["is_featured"] = True


# ---------------------------------------------------------------------------------------------
# Live recalculation with data the customer declares in the chat
# ---------------------------------------------------------------------------------------------
@dataclass
class Recalculation:
    profile: dict                            # profile with recomputed income, debt, capacity, eligibility
    options: list
    declared: dict = field(default_factory=dict)   # what the customer said, in USD
    flags: list = field(default_factory=list)      # F03 / F04 known now; F02 depends on the accepted amount


def recalculate(profile: dict, policy: Policy, *, declared_income_usd: float | None = None,
                additional_income_usd: float | None = None,
                external_installments_usd: float | None = None) -> Recalculation:
    """Sections 2 and 6 of CREDIT_RULES.md. Only R05 (income) and R08 (capacity) are re-evaluated;
    the other hard filters come from bank data and do not change with what the customer says."""
    p = dict(profile)
    declared = {k: v for k, v in {"declared_income_usd": declared_income_usd,
                                  "additional_income_usd": additional_income_usd,
                                  "external_installments_usd": external_installments_usd}.items() if v is not None}
    flags = ["F03_DECLARED_DATA"] if declared else []
    if (_num(p.get("open_complaints")) or 0) > 0:
        flags.append("F04_OPEN_COMPLAINTS")
    if not declared:
        # Nothing new: keep gold's capacity as stored. Recomputing it from the rounded income and
        # installments can move it by a cent and flip an amount across a 100 USD step.
        return Recalculation(p, offer_options(p, policy), declared, flags)
    income = declared_income_usd if declared_income_usd is not None else _num(p.get("income_used_usd"))
    if income is not None and additional_income_usd:
        income += additional_income_usd
    installments = (_num(p.get("current_installments_usd")) or 0.0) + (external_installments_usd or 0.0)
    p["income_used_usd"] = income
    p["income_source"] = "declared_in_chat" if declared_income_usd is not None or additional_income_usd else p.get("income_source")
    p["current_installments_usd"] = installments
    if income is not None:
        p["max_total_installment_usd"] = policy.max_dti * income
        p["available_installment_usd"] = round(policy.max_dti * income - installments, 2)
        p["current_debt_to_income"] = installments / income if income else None
    else:
        p["max_total_installment_usd"] = p["available_installment_usd"] = None

    min_income = float(policy.params["min_income_usd"])
    codes = [c for c in (p.get("reason_codes") or []) if c.split("_")[0] in HARD_FILTERS_FROM_BANK_DATA]
    if income is None:
        codes.append("R05_INCOME_MISSING")
    elif income < min_income:
        codes.append("R05_INCOME_BELOW_MIN")
    if income is not None and p["available_installment_usd"] <= 0:
        codes.append("R08_NO_CAPACITY")
    p["reason_codes"] = codes
    p["is_eligible"] = not codes

    return Recalculation(p, offer_options(p, policy), declared, flags)


# ---------------------------------------------------------------------------------------------
# Accepted offer -> gold credit_offers row
# ---------------------------------------------------------------------------------------------
def build_credit_offer(*, offer_id: str, profile: dict, option: dict, amount_usd: float, policy: Policy,
                       flags: list, offer_origin: str, created_at, session_id: str | None = None,
                       channel: str = "chat", language: str | None = None,
                       customer_declared_data: str | None = None, required_documents: list | None = None) -> dict:
    """Validates the accepted amount against the option and the 20% limit, adds F02 and returns
    the credit_offers row. The amount must be recomputed here, never taken from LLM text."""
    if not option["is_available"]:
        raise ValueError(f"option {option['option_code']}/{option['term_months']} is not available")
    if not option["option_min_amount_usd"] <= amount_usd <= option["offer_max_amount_usd"]:
        raise ValueError("amount outside the option range")
    if offer_origin not in ("proactive", "customer_interest"):
        raise ValueError("offer_origin must be proactive or customer_interest")
    installment = monthly_installment(amount_usd, option["offer_rate_pct"], option["term_months"])
    income = profile["income_used_usd"]
    dti_after = (profile["current_installments_usd"] + installment) / income
    if dti_after > policy.max_dti + 1e-9:
        raise ValueError(f"debt-to-income after offer {dti_after:.4f} exceeds {policy.max_dti}")
    flags = list(flags)
    if dti_after >= NEAR_LIMIT_SHARE and profile.get("income_source") == "declared_in_chat":
        flags.insert(0, "F02_NEAR_LIMIT_DECLARED_INCOME")
    fx = profile["fx_to_usd"]
    created_date = created_at.date() if hasattr(created_at, "date") else created_at
    return {
        "offer_id": offer_id, "customer_id": profile["customer_id"], "session_id": session_id,
        "channel": channel, "language": language, "offer_origin": offer_origin,
        "option_code": option["option_code"], "product_code": option["product_code"],
        "product_type": option["product_type"], "tier": option["tier"], "term_months": option["term_months"],
        "amount_usd": round(amount_usd, 2), "annual_rate_pct": option["offer_rate_pct"],
        "monthly_installment_usd": round(installment, 2), "local_currency": profile["local_currency"],
        "fx_to_usd": fx, "fx_date": profile.get("fx_date"), "amount_local": round(amount_usd / fx, 0),
        "monthly_installment_local": round(installment / fx, 0), "income_used_usd": round(income, 2),
        "income_source": profile.get("income_source") or "declared_profile",
        "current_installments_usd": round(profile["current_installments_usd"], 2),
        "max_total_installment_usd": round(policy.max_dti * income, 2),
        "debt_to_income_after": round(dti_after, 4), "risk_band": profile["risk_band"],
        "segment": profile.get("segment"), "rate_adjustment_pp": profile.get("total_rate_adjustment_pp") or 0.0,
        "customer_declared_data": customer_declared_data,
        "open_complaints": int(profile.get("open_complaints") or 0),
        "open_priority_complaints": int(profile.get("open_priority_complaints") or 0),
        "open_critical_complaints": int(profile.get("open_critical_complaints") or 0),
        "is_conditional": "F03_DECLARED_DATA" in flags, "flags": flags,
        "required_documents": required_documents or [], "status": "accepted",
        "handoff_ticket_id": None, "advisor_summary": None,
        "valid_until": created_date + timedelta(days=int(policy.params["offer_validity_days"])),
        "profile_as_of_date": profile["as_of_date"], "policy_version": policy.version,
        "created_at": created_at, "updated_at": None,
    }

"""Unit tests for the reference credit policy, on a team-made profile (no organizer data).

The numbers are the worked example in docs/CREDIT_RULES.md. Run: pytest data/policy
"""
from datetime import datetime

import pytest

from policy.credit_policy import (build_credit_offer, load_policy, max_principal, monthly_installment,
                                  offer_options, recalculate)

POLICY = load_policy()


def profile(**over):
    """Band C, Basic segment, income 2,500 USD from the profile, current installments 100 USD."""
    p = {"customer_id": "TEST-0001", "risk_band": "C", "segment": "Basic", "is_eligible": True,
         "reason_codes": [], "income_used_usd": 2500.0, "income_source": "declared_profile",
         "current_installments_usd": 100.0, "available_installment_usd": 400.0,
         "total_rate_adjustment_pp": 0.0, "max_term_personal_loan_months": 48,
         "max_term_mortgage_months": 300, "open_complaints": 0, "open_priority_complaints": 0,
         "open_critical_complaints": 0, "local_currency": "COP", "fx_to_usd": 0.000248,
         "fx_date": None, "as_of_date": "2026-06-30"}
    p.update(over)
    return p


def option(opts, code, term):
    return next(o for o in opts if o["option_code"] == code and o["term_months"] == term)


def test_annuity_roundtrip():
    assert monthly_installment(40_000, 6.2, 180) == pytest.approx(341.88, abs=0.005)
    assert max_principal(monthly_installment(40_000, 6.2, 180), 6.2, 180) == pytest.approx(40_000)


def test_worked_example_personal_loan():
    opts = offer_options(profile(), POLICY)
    pl24 = option(opts, "PL", 24)
    assert pl24["offer_rate_pct"] == 15.2 and pl24["offer_max_amount_usd"] == 8200
    assert pl24["offer_monthly_installment_usd"] == pytest.approx(398.37, abs=0.01)
    assert option(opts, "PL", 48)["offer_max_amount_usd"] == 12700


def test_band_maximum_term():
    pl60 = option(offer_options(profile(), POLICY), "PL", 60)
    assert not pl60["is_available"] and pl60["unavailable_reason"] == "term_above_band_maximum"


def test_options_are_alternatives_using_the_whole_capacity():
    for o in offer_options(profile(), POLICY):
        if o["is_available"]:
            assert o["offer_monthly_installment_usd"] <= 400.0 + 0.01


def test_household_income_raises_capacity_and_flags_declared_data():
    r = recalculate(profile(), POLICY, additional_income_usd=1000.0)
    assert r.profile["available_installment_usd"] == pytest.approx(600.0)
    assert option(r.options, "PL", 24)["offer_max_amount_usd"] == 12300
    assert r.flags == ["F03_DECLARED_DATA"]


def test_external_debt_lowers_capacity():
    r = recalculate(profile(), POLICY, external_installments_usd=150.0)
    assert option(r.options, "PL", 24)["offer_max_amount_usd"] == 5100


def test_debt_above_the_limit_removes_the_offer():
    r = recalculate(profile(), POLICY, external_installments_usd=500.0)
    assert not r.profile["is_eligible"] and "R08_NO_CAPACITY" in r.profile["reason_codes"]
    assert not any(o["is_available"] for o in r.options)


def test_missing_income_is_recoverable_in_the_chat():
    p = profile(income_used_usd=None, available_installment_usd=None, is_eligible=False,
                reason_codes=["R05_INCOME_MISSING"])
    r = recalculate(p, POLICY, declared_income_usd=2500.0)
    assert r.profile["is_eligible"] and r.profile["reason_codes"] == []


def test_bank_data_filters_do_not_change_with_chat_data():
    p = profile(is_eligible=False, reason_codes=["R03_DELINQUENCY"])
    r = recalculate(p, POLICY, declared_income_usd=10_000.0)
    assert not r.profile["is_eligible"] and r.profile["reason_codes"] == ["R03_DELINQUENCY"]


def test_complaints_never_change_amount_or_rate_but_are_flagged():
    base = option(offer_options(profile(), POLICY), "PL", 24)
    r = recalculate(profile(open_complaints=2), POLICY)
    assert option(r.options, "PL", 24) == base and r.flags == ["F04_OPEN_COMPLAINTS"]


def test_accepted_offer_row_and_f02_only_on_declared_income():
    created = datetime(2026, 6, 30, 12, 0)
    pl24 = option(offer_options(profile(), POLICY), "PL", 24)
    row = build_credit_offer(offer_id="o-1", profile=profile(), option=pl24, amount_usd=8200, policy=POLICY,
                             flags=[], offer_origin="proactive", created_at=created)
    assert row["debt_to_income_after"] == pytest.approx(0.1993, abs=1e-4) and row["flags"] == []
    assert row["policy_version"] == "0.4" and str(row["valid_until"]) == "2026-07-30"

    r = recalculate(profile(), POLICY, additional_income_usd=1000.0)
    pl24 = option(r.options, "PL", 24)
    row = build_credit_offer(offer_id="o-2", profile=r.profile, option=pl24, amount_usd=12300, policy=POLICY,
                             flags=r.flags, offer_origin="customer_interest", created_at=created)
    assert row["flags"] == ["F02_NEAR_LIMIT_DECLARED_INCOME", "F03_DECLARED_DATA"] and row["is_conditional"]


def test_accepting_more_than_the_option_allows_is_rejected():
    pl24 = option(offer_options(profile(), POLICY), "PL", 24)
    with pytest.raises(ValueError):
        build_credit_offer(offer_id="o-3", profile=profile(), option=pl24, amount_usd=9000, policy=POLICY,
                           flags=[], offer_origin="proactive", created_at=datetime(2026, 6, 30))


def featured(opts):
    return {o["product_code"]: (o["option_code"], o["term_months"], o["offer_max_amount_usd"])
            for o in opts if o["is_featured"]}


def test_featured_option_is_the_highest_per_product():
    # Worked example: longest personal loan term of band C, the only card tier within capacity.
    f = featured(offer_options(profile(), POLICY))
    assert f["PL"] == ("PL", 48, 12700) and f["CC"][0] == "CC-CLA"


def test_featured_mortgage_tie_at_the_maximum_goes_to_the_shortest_term():
    opts = offer_options(profile(income_used_usd=30_000.0, available_installment_usd=5_900.0), POLICY)
    capped = [o["term_months"] for o in opts if o["product_code"] == "MG" and o["offer_max_amount_usd"] == 150_000]
    assert len(capped) > 1
    assert featured(opts)["MG"] == ("MG", min(capped), 150_000)
    assert featured(opts)["CC"][0] == "CC-BLK"


def test_no_featured_option_without_availability():
    assert featured(offer_options(profile(is_eligible=False, reason_codes=["R03_DELINQUENCY"]), POLICY)) == {}

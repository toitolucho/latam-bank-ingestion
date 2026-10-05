from __future__ import annotations

import random
import re
from datetime import date

import pytest

from app.auth import kba
from app.config import Settings
from app.data.repository import Customer, SnapshotRepository

SETTINGS = Settings(_env_file=None)
REPO = SnapshotRepository(SETTINGS.data_dir)
AS_OF = SETTINGS.as_of_date
KINDS = {"occupation", "product_city", "product_year", "customer_since"}


def _customers():
    return [REPO.find_by_document(d) for d in REPO.sample_documents(10_000)]


def test_snapshot_customers_have_enough_data_for_a_challenge():
    cs = _customers()
    built = [kba.build_challenge(REPO, c, n=3, lang="es", as_of=AS_OF) for c in cs]
    missing = sum(b is None for b in built)
    assert missing / len(cs) < 0.05, f"{missing} de {len(cs)} clientes sin datos para 3 preguntas"


def test_questions_are_well_formed():
    rng = random.Random(1)
    for c in _customers()[:60]:
        for lang in ("es", "pt"):
            ch = kba.build_challenge(REPO, c, n=3, lang=lang, as_of=AS_OF, rng=rng)
            if ch is None:
                continue
            assert len({q.kind for q in ch.questions}) == 3 and {q.kind for q in ch.questions} <= KINDS
            for q in ch.questions:
                labels = [o.label for o in q.options]
                assert len(labels) == 4 and len(set(labels)) == 4, (q.kind, labels)
                assert sum(o.id == q.correct_option_id for o in q.options) == 1


def test_correct_answers_verify_and_wrong_ones_do_not():
    c = _customers()[0]
    ch = kba.build_challenge(REPO, c, n=3, lang="es", as_of=AS_OF)
    good = {q.id: q.correct_option_id for q in ch.questions}
    assert kba.verify(ch, good)
    bad = dict(good)
    q0 = ch.questions[0]
    bad[q0.id] = next(o.id for o in q0.options if o.id != q0.correct_option_id)
    assert not kba.verify(ch, bad)
    assert not kba.verify(ch, {})                                  # sin respuestas
    assert not kba.verify(ch, {**good, "extra": "x"})              # preguntas ajenas


def test_decoy_challenge_never_verifies_and_looks_real():
    d = kba.decoy_challenge(REPO, n=3, lang="es", as_of=AS_OF)
    assert len(d.questions) == 3
    for q in d.questions:
        assert len(q.options) == 4 and q.correct_option_id is None
    for q in d.questions:  # ninguna combinacion posible se acepta
        assert not kba.verify(d, {x.id: x.options[0].id for x in d.questions})


def test_public_view_hides_correct_answers():
    c = _customers()[0]
    ch = kba.build_challenge(REPO, c, n=3, lang="pt", as_of=AS_OF)
    pub = str(ch.public())
    assert "correct" not in pub


# ---------------------------------------------------------------- la serie acordada: ocupacion, ciudad y anos
def _many(lang="es", per_customer=3):
    rng = random.Random(11)
    for c in _customers():
        for _ in range(per_customer):
            ch = kba.build_challenge(REPO, c, n=3, lang=lang, as_of=AS_OF, rng=rng)
            if ch:
                yield c, ch


def test_questions_never_carry_real_identifiers_or_ask_for_amounts():
    """El texto se muestra antes de autenticar: sin terminaciones, fechas exactas ni montos."""
    for _, ch in _many():
        for q in ch.questions:
            assert not re.search(r"\d", q.text), q.text                       # ningun digito en el enunciado
            assert not re.search(r"terminaci|monto|valor|importe", q.text.lower()), q.text


def test_city_distractors_all_come_from_the_same_country_as_the_answer():
    """Con distractores de los tres paises, quien conoce el pais acertaba el 63% (no el 25%)."""
    by_country = {c: set(REPO.branch_cities(c)) for c in REPO.branch_countries()}
    seen = 0
    for _, ch in _many():
        for q in (x for x in ch.questions if x.kind == "product_city"):
            labels = {o.label for o in q.options}
            countries = [c for c, cities in by_country.items() if labels <= cities]
            assert countries, f"opciones de varios paises: {labels}"
            seen += 1
    assert seen > 50


def test_years_are_ordered_and_inside_the_valid_range():
    seen = 0
    for _, ch in _many():
        for q in (x for x in ch.questions if x.kind in kba.YEAR_KINDS):
            years = [int(o.label) for o in q.options]
            assert years == sorted(years) and all(kba.MIN_YEAR <= y <= AS_OF.year for y in years), years
            seen += 1
    assert seen > 50


def test_occupation_labels_are_gender_neutral_and_translated():
    assert set(kba.OCCUPATIONS["es"]) == set(kba.OCCUPATIONS["pt"]) and len(kba.OCCUPATIONS["es"]) == 20
    assert not {"Contadora", "Abogada", "Doctora"} & set(kba.OCCUPATIONS["es"].values())
    ch = next(ch for _, ch in _many("pt") if any(q.kind == "occupation" for q in ch.questions))
    q = next(x for x in ch.questions if x.kind == "occupation")
    assert q.text.startswith("Qual é a sua ocupação") and all(o.label in kba.OCCUPATIONS["pt"].values() for o in q.options)


# ---------------------------------------------------------------- reglas de seleccion, con un repositorio de juguete
class Stub:
    """Repositorio minimo: un cliente configurable. `prods` = lista de (tipo, fecha de apertura, canal, id de sucursal)."""

    def __init__(self, prods=(), occupation="Lawyer", reg_year=2021, others=()):
        self.prods = [{"product_type": t, "opening_date": d, "opening_channel": ch, "opening_branch_id": b,
                       "product_status": "Active", "last4": "0000"} for t, d, ch, b in prods]
        self.occupation, self.reg_year, self.others = occupation, reg_year, others
        self._cities = {"MX": ["Ciudad A", "Ciudad B", "Ciudad C", "Ciudad D", "Ciudad E"],
                        "CO": ["Ciudad F", "Ciudad G", "Ciudad H", "Ciudad I"]}

    def products(self, cid):
        return self.prods

    def profile_facts(self, cid):
        return {"occupation": self.occupation, "registration_year": self.reg_year}

    def branch_city(self, bid):
        return {"B1": "Ciudad A", "B2": "Ciudad F"}.get(bid)

    def branch_country(self, bid):
        return {"B1": "MX", "B2": "CO"}.get(bid)

    def branch_cities(self, country=None):
        return [c for cs in self._cities.values() for c in cs] if country is None else list(self._cities[country])

    def branch_countries(self):
        return sorted(self._cities)

    def random_customer_id(self, rng):
        return "X"


CUST = Customer("X", "DNI", "1", "Ana", "México", "Basic", "Active")


def build(stub, lang="es", n=3, seed=1):
    return kba.build_challenge(stub, CUST, n=n, lang=lang, as_of=AS_OF, rng=random.Random(seed))


def kinds_over(stub, runs=200):
    return {tuple(sorted(q.kind for q in ch.questions)) for ch in (build(stub, seed=s) for s in range(runs)) if ch}


FULL = [("Cuenta Ahorro", "2020-03-01", "Branch", "B1"), ("Tarjeta Crédito", "2022-07-15", "App", "B1")]


def test_prefers_a_single_year_question_when_it_has_other_kinds():
    combos = kinds_over(Stub(FULL))
    assert combos == {("occupation", "product_city", "product_year"), ("customer_since", "occupation", "product_city")}
    assert not any(set(kba.YEAR_KINDS) <= set(c) for c in combos)


def test_falls_back_to_two_year_questions_when_there_is_no_city_to_ask():
    online_only = [("Cuenta Ahorro", "2020-03-01", "Web", "B1")]
    assert kinds_over(Stub(online_only)) == {("customer_since", "occupation", "product_year")}


def test_the_city_question_needs_a_product_opened_in_a_branch():
    assert all("product_city" not in k for k in kinds_over(Stub([("Cuenta Ahorro", "2020-03-01", "Web", "B1")])))
    assert any("product_city" in k for k in kinds_over(Stub(FULL)))


def test_unavailable_when_fewer_than_three_kinds():
    assert build(Stub(FULL, occupation=None, reg_year=None)) is None            # solo ciudad y ano de apertura
    assert build(Stub([], occupation="Lawyer", reg_year=2021)) is None          # solo ocupacion y ano de alta
    assert build(Stub(FULL, occupation=None, reg_year=2021)) is not None        # ciudad + ano + alta


def test_product_naming_never_uses_the_ending_and_only_says_oldest_when_needed():
    one = build(Stub([("Cuenta Ahorro", "2020-03-01", "Branch", "B1")]))
    q = next(x for x in one.questions if x.kind == "product_city")
    assert q.text == "¿En qué ciudad abrió su cuenta de ahorro?" and "antigu" not in q.text
    two = Stub([("Cuenta Ahorro", "2020-03-01", "Branch", "B1"), ("Cuenta Ahorro", "2023-01-10", "Web", "B2")])
    q = next(x for x in build(two).questions if x.kind == "product_city")
    assert q.text == "¿En qué ciudad abrió su cuenta de ahorro más antigua?"
    assert next(o.label for o in q.options if o.id == q.correct_option_id) == "Ciudad A"      # la del producto mas antiguo


def test_a_tie_between_the_oldest_products_makes_that_type_unaskable():
    tie = Stub([("Cuenta Ahorro", "2020-03-01", "Branch", "B1"), ("Cuenta Ahorro", "2020-03-01", "Branch", "B2")],
               occupation=None, reg_year=None)
    assert build(tie) is None                                                   # sin otro tipo de producto no hay con que preguntar


def test_gender_agreement_in_the_oldest_wording():
    assert kba.product_phrase("Tarjeta Crédito", "es", True) == "su tarjeta de crédito más antigua"
    assert kba.product_phrase("Préstamo Personal", "es", True) == "su préstamo personal más antiguo"
    assert kba.product_phrase("Tarjeta Crédito", "pt", True) == "o seu cartão de crédito mais antigo"
    assert kba.product_phrase("Cuenta Ahorro", "pt", True) == "a sua conta poupança mais antiga"
    assert kba.product_phrase("Cuenta Ahorro", "pt", False) == "a sua conta poupança"


def test_the_correct_year_is_the_real_opening_year():
    stub = Stub([("Cuenta Ahorro", "2020-03-01", "Branch", "B1")], occupation=None)
    ch = build(stub, seed=4)
    q = next(x for x in ch.questions if x.kind == "product_year")
    assert next(o.label for o in q.options if o.id == q.correct_option_id) == "2020"


def test_a_year_outside_the_valid_range_is_not_asked():
    far = Stub([("Cuenta Ahorro", "2010-03-01", "Branch", "B1")], reg_year=2010, occupation=None)
    assert build(far) is None


def test_decoy_takes_its_kinds_from_a_real_customer_but_never_its_data():
    real = Stub(FULL, occupation="Lawyer", reg_year=2021)
    combos = set()
    for _ in range(60):
        d = kba.decoy_challenge(real, n=3, lang="es", as_of=AS_OF)
        combos.add(tuple(sorted(q.kind for q in d.questions)))
        assert all(q.correct_option_id is None and len(q.options) == 4 for q in d.questions)
        assert all(not re.search(r"\d", q.text) for q in d.questions)
    assert combos <= kinds_over(real)                                            # misma mezcla que un cliente real igual
    nodata = Stub([], occupation=None, reg_year=None)
    d = kba.decoy_challenge(nodata, n=3, lang="es", as_of=AS_OF)                # si el cliente al azar no sirve, no se rompe
    assert len(d.questions) == 3


def test_a_row_with_missing_values_is_skipped_instead_of_breaking_the_challenge():
    """pandas deja NaN en una celda vacia: el producto sin fecha no se usa y el que no tiene sucursal no sirve para la ciudad."""
    stub = Stub(FULL)
    stub.prods[0]["opening_date"] = float("nan")          # cuenta de ahorro (la unica abierta en sucursal): fuera
    assert kinds_over(stub) == {("customer_since", "occupation", "product_year")}
    stub2 = Stub(FULL)
    stub2.prods[0]["opening_branch_id"] = float("nan")    # sin sucursal: no se puede preguntar la ciudad
    assert all("product_city" not in k for k in kinds_over(stub2))

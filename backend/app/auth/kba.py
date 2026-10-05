"""Autenticacion por preguntas de seguridad (KBA) generadas desde datos del cliente.

Serie (decidida con el equipo; ver README): ocupacion, ciudad y anos. Nada de montos, fechas exactas ni recordar una operacion.
  occupation       ocupacion registrada en el banco                       (20 valores)
  product_city     ciudad donde abrio un producto (solo abiertos en sucursal)  (distractores: el MISMO pais)
  product_year     ano en que abrio un producto                            (2018 hasta el ano de corte)
  customer_since   ano en que se hizo cliente                              (OJO: el registro es poco fiable en el dataset)

Reglas de diseno:
- Un producto se nombra por su tipo ("su cuenta de ahorro") o, si hay varios del mismo tipo, por el mas antiguo. Nunca por su
  terminacion: el texto de la pregunta se muestra ANTES de autenticar y no debe llevar datos reales del cliente.
- Los distractores salen del mismo universo que la respuesta (ciudades del mismo pais, anos validos): si no, quien conoce el
  pais del cliente descarta opciones (con distractores de los tres paises acertaba el 63%, no el 25%).
- Un reto son n preguntas de tipos distintos. Se prefiere un solo tipo de ano; con dos, el ano de alta y el de apertura pueden
  no cuadrar en estos datos (el registro del cliente no coincide con su primer producto).
- Las respuestas correctas viven solo en el servidor; el cliente recibe ids de opcion aleatorios.
- La verificacion es en tiempo constante y exige TODAS las respuestas correctas.
- Para un documento inexistente se genera un reto senuelo con la misma forma que uno real (los tipos salen de un cliente real
  al azar), que nunca se aprueba: asi la API no revela si un documento existe.
- El LLM no participa: ni genera ni verifica preguntas, y nunca ve las respuestas.

LIMITE CONOCIDO: con 3 preguntas de 4 opciones, adivinar acierta con probabilidad 1/64 por intento. Es un prototipo: la
mitigacion es el limite de intentos y el bloqueo por documento (ver core/ratelimit.py).
"""
from __future__ import annotations

import hmac
import random
import secrets
from dataclasses import dataclass, field
from datetime import date

from app.data.repository import Customer, CustomerRepository

MIN_YEAR = 2018
YEAR_KINDS = ("product_year", "customer_since")
BRANCH = "Branch"

PRODUCT_LABELS = {
    "es": {"Cuenta Ahorro": "cuenta de ahorro", "Tarjeta Crédito": "tarjeta de crédito",
           "Cuenta Corriente": "cuenta corriente", "Tarjeta Débito": "tarjeta de débito",
           "Préstamo Personal": "préstamo personal", "Préstamo Hipotecario": "préstamo hipotecario",
           "Inversión": "inversión", "Seguro": "seguro"},
    "pt": {"Cuenta Ahorro": "conta poupança", "Tarjeta Crédito": "cartão de crédito",
           "Cuenta Corriente": "conta corrente", "Tarjeta Débito": "cartão de débito",
           "Préstamo Personal": "empréstimo pessoal", "Préstamo Hipotecario": "financiamento imobiliário",
           "Inversión": "investimento", "Seguro": "seguro"},
}
# Genero gramatical por tipo de producto e idioma: "su cuenta ... mas antigua" / "o seu cartao ... mais antigo".
PRODUCT_GENDER = {"Cuenta Ahorro": {"es": "f", "pt": "f"}, "Cuenta Corriente": {"es": "f", "pt": "f"},
                  "Tarjeta Débito": {"es": "f", "pt": "m"}, "Tarjeta Crédito": {"es": "f", "pt": "m"},
                  "Préstamo Personal": {"es": "m", "pt": "m"}, "Préstamo Hipotecario": {"es": "m", "pt": "m"},
                  "Inversión": {"es": "f", "pt": "m"}, "Seguro": {"es": "m", "pt": "m"}}
_POSSESSIVE = {"es": {"f": "su", "m": "su"}, "pt": {"f": "a sua", "m": "o seu"}}
_OLDEST = {"es": {"f": "más antigua", "m": "más antiguo"}, "pt": {"f": "mais antiga", "m": "mais antigo"}}

# Ocupaciones del dataset (en ingles) con etiquetas sin asumir genero ("Abogado/a").
OCCUPATIONS = {
    "es": {"Accountant": "Contador/a", "Administrative": "Administrativo/a", "Artist": "Artista", "Consultant": "Consultor/a",
           "Director": "Director/a", "Doctor": "Médico/a", "Driver": "Conductor/a", "Employee": "Empleado/a",
           "Engineer": "Ingeniero/a", "Entrepreneur": "Emprendedor/a", "Homemaker": "Ama/o de casa",
           "Independent Professional": "Profesional independiente", "Lawyer": "Abogado/a", "Manager": "Gerente",
           "Merchant": "Comerciante", "Retired": "Jubilado/a", "Salesperson": "Vendedor/a", "Student": "Estudiante",
           "Teacher": "Docente", "Technician": "Técnico/a"},
    "pt": {"Accountant": "Contador/a", "Administrative": "Administrativo/a", "Artist": "Artista", "Consultant": "Consultor/a",
           "Director": "Diretor/a", "Doctor": "Médico/a", "Driver": "Motorista", "Employee": "Funcionário/a",
           "Engineer": "Engenheiro/a", "Entrepreneur": "Empreendedor/a", "Homemaker": "Dono/a de casa",
           "Independent Professional": "Profissional autônomo/a", "Lawyer": "Advogado/a", "Manager": "Gerente",
           "Merchant": "Comerciante", "Retired": "Aposentado/a", "Salesperson": "Vendedor/a", "Student": "Estudante",
           "Teacher": "Professor/a", "Technician": "Técnico/a"},
}
TEXTS = {
    "es": {
        "occupation": "¿Cuál es su ocupación registrada en el banco?",
        "product_city": "¿En qué ciudad abrió {product}?",
        "product_year": "¿En qué año abrió {product}?",
        "customer_since": "¿En qué año se hizo cliente del banco?",
    },
    "pt": {
        "occupation": "Qual é a sua ocupação registrada no banco?",
        "product_city": "Em que cidade você abriu {product}?",
        "product_year": "Em que ano você abriu {product}?",
        "customer_since": "Em que ano você se tornou cliente do banco?",
    },
}


@dataclass
class Option:
    id: str
    label: str


@dataclass
class Question:
    id: str
    kind: str
    text: str
    options: list[Option]
    correct_option_id: str | None  # None en retos senuelo

    def public(self) -> dict:
        return {"id": self.id, "text": self.text, "options": [{"id": o.id, "label": o.label} for o in self.options]}


@dataclass
class Challenge:
    questions: list[Question] = field(default_factory=list)

    def public(self) -> list[dict]:
        return [q.public() for q in self.questions]


def _rid() -> str:
    return secrets.token_hex(4)


def _make_question(kind: str, text: str, correct: str, distractors: list[str], rng: random.Random,
                   ordered: bool = False) -> Question:
    """`ordered`: las opciones van ordenadas (anos de menor a mayor); si no, en orden aleatorio."""
    labels = [correct] + distractors[:3]
    if ordered:
        labels.sort()
    else:
        rng.shuffle(labels)
    options = [Option(_rid(), lab) for lab in labels]
    cid = next(o.id for o in options if o.label == correct)
    return Question(_rid(), kind, text, options, cid)


def product_phrase(product_type: str, lang: str, oldest: bool) -> str:
    """'su cuenta de ahorro' o 'su cuenta de ahorro más antigua'. Sin terminacion ni ningun dato real."""
    gender = PRODUCT_GENDER[product_type][lang]
    label = PRODUCT_LABELS[lang][product_type]
    return f"{_POSSESSIVE[lang][gender]} {label}" + (f" {_OLDEST[lang][gender]}" if oldest else "")


def _year_distractors(correct: int, as_of: date, rng: random.Random) -> list[str] | None:
    pool = [y for y in range(MIN_YEAR, as_of.year + 1) if y != correct]
    return [str(y) for y in rng.sample(pool, 3)] if len(pool) >= 3 else None


def _anchors(repo: CustomerRepository, cid: str) -> list[dict]:
    """Productos a los que se puede apuntar sin ambiguedad: el unico de su tipo o, si hay varios, el mas antiguo (sin empate)."""
    by_type: dict[str, list[dict]] = {}
    for p in repo.products(cid):
        if p.get("product_status", "Active") == "Active" and _has(p.get("opening_date")) and p.get("product_type") in PRODUCT_GENDER:
            by_type.setdefault(p["product_type"], []).append(p)
    out = []
    for group in by_type.values():
        group.sort(key=lambda p: _to_date(p["opening_date"]))
        if len(group) == 1:
            out.append({**group[0], "_oldest": False})
        elif _to_date(group[0]["opening_date"]) < _to_date(group[1]["opening_date"]):
            out.append({**group[0], "_oldest": True})
    return out


def _has(v) -> bool:
    """Valor presente (no None ni NaN, que es lo que pandas deja en una celda vacia)."""
    return v is not None and not (isinstance(v, float) and v != v)


def _to_date(v) -> date:
    if hasattr(v, "date") and callable(v.date):
        return v.date()
    return v if isinstance(v, date) else date.fromisoformat(str(v)[:10])


# -- generadores: devuelven Question o None si no hay datos suficientes ------------------------------------------

def _q_occupation(repo: CustomerRepository, cid: str, lang: str, rng: random.Random, **_) -> Question | None:
    raw = repo.profile_facts(cid).get("occupation")
    labels = OCCUPATIONS[lang]
    if not raw:
        return None
    correct = labels.get(raw, raw)
    others = [v for v in labels.values() if v != correct]
    return _make_question("occupation", TEXTS[lang]["occupation"], correct, rng.sample(others, 3), rng)


def _q_product_city(repo: CustomerRepository, cid: str, lang: str, rng: random.Random, **_) -> Question | None:
    # Solo productos abiertos en sucursal: quien abrio online no tiene una "ciudad de apertura" que recordar.
    cands = [p for p in _anchors(repo, cid) if p.get("opening_channel") == BRANCH and _has(p.get("opening_branch_id"))
             and repo.branch_city(p["opening_branch_id"]) and repo.branch_country(p["opening_branch_id"])]
    if not cands:
        return None
    p = rng.choice(cands)
    correct = repo.branch_city(p["opening_branch_id"])
    same_country = [c for c in repo.branch_cities(repo.branch_country(p["opening_branch_id"])) if c != correct]
    if len(same_country) < 3:
        return None
    text = TEXTS[lang]["product_city"].format(product=product_phrase(p["product_type"], lang, p["_oldest"]))
    return _make_question("product_city", text, correct, rng.sample(same_country, 3), rng)


def _q_product_year(repo: CustomerRepository, cid: str, lang: str, rng: random.Random, as_of: date, **_) -> Question | None:
    cands = _anchors(repo, cid)
    if not cands:
        return None
    p = rng.choice(cands)
    correct = _to_date(p["opening_date"]).year
    distractors = _year_distractors(correct, as_of, rng)
    if distractors is None or not MIN_YEAR <= correct <= as_of.year:
        return None
    text = TEXTS[lang]["product_year"].format(product=product_phrase(p["product_type"], lang, p["_oldest"]))
    return _make_question("product_year", text, str(correct), distractors, rng, ordered=True)


def _q_customer_since(repo: CustomerRepository, cid: str, lang: str, rng: random.Random, as_of: date, **_) -> Question | None:
    correct = repo.profile_facts(cid).get("registration_year")
    if correct is None or not MIN_YEAR <= correct <= as_of.year:
        return None
    distractors = _year_distractors(correct, as_of, rng)
    if distractors is None:
        return None
    return _make_question("customer_since", TEXTS[lang]["customer_since"], str(correct), distractors, rng, ordered=True)


GENERATORS = {"occupation": _q_occupation, "product_city": _q_product_city, "product_year": _q_product_year,
              "customer_since": _q_customer_since}


def pick_kinds(available: list[str], n: int, rng: random.Random) -> list[str] | None:
    """n tipos distintos. Primero los que no son de ano; los de ano solo para completar (un solo tipo de ano si se puede)."""
    if len(available) < n:
        return None
    plain = [k for k in available if k not in YEAR_KINDS]
    years = [k for k in available if k in YEAR_KINDS]
    rng.shuffle(plain)
    rng.shuffle(years)
    return (plain + years)[:n]


def build_challenge(repo: CustomerRepository, customer: Customer, *, n: int, lang: str,
                    as_of: date, rng: random.Random | None = None) -> Challenge | None:
    """Devuelve n preguntas de tipos distintos, o None si el cliente no tiene datos para n tipos."""
    rng = rng or random.Random(secrets.randbits(64))
    made = {}
    for kind, gen in GENERATORS.items():
        q = gen(repo, customer.customer_id, lang, rng, as_of=as_of)
        if q:
            made[kind] = q
    kinds = pick_kinds(list(made), n, rng)
    return Challenge([made[k] for k in kinds]) if kinds else None


def available_kinds(repo: CustomerRepository, cid: str, as_of: date, rng: random.Random) -> list[str]:
    return [k for k, gen in GENERATORS.items() if gen(repo, cid, "es", rng, as_of=as_of)]


def decoy_challenge(repo: CustomerRepository, *, n: int, lang: str, as_of: date) -> Challenge:
    """Reto senuelo con la misma forma que uno real; ninguna respuesta se acepta (correct_option_id=None).

    Los TIPOS de pregunta salen de un cliente real al azar (asi la mezcla coincide con la de los clientes reales); el contenido
    es inventado, nunca de ese cliente. Es aleatorio por sesion: uno determinista se delataria al repetir la peticion.
    """
    rng = random.Random(secrets.randbits(64))
    kinds = None
    for _ in range(20):
        kinds = pick_kinds(available_kinds(repo, repo.random_customer_id(rng), as_of, rng), n, rng)
        if kinds:
            break
    kinds = kinds or pick_kinds(list(GENERATORS), n, rng)
    qs: list[Question] = []
    for kind in kinds:
        if kind == "occupation":
            labels = rng.sample(list(OCCUPATIONS[lang].values()), 4)
            qs.append(Question(_rid(), kind, TEXTS[lang][kind], [Option(_rid(), x) for x in labels], None))
        elif kind == "product_city":
            cities = repo.branch_cities(rng.choice(repo.branch_countries()))
            product = product_phrase(rng.choice(list(PRODUCT_GENDER)), lang, rng.random() < 0.25)
            qs.append(Question(_rid(), kind, TEXTS[lang][kind].format(product=product),
                               [Option(_rid(), c) for c in rng.sample(cities, min(4, len(cities)))], None))
        else:
            years = sorted(rng.sample(range(MIN_YEAR, as_of.year + 1), 4))
            text = TEXTS[lang][kind]
            if kind == "product_year":
                text = text.format(product=product_phrase(rng.choice(list(PRODUCT_GENDER)), lang, rng.random() < 0.25))
            qs.append(Question(_rid(), kind, text, [Option(_rid(), str(y)) for y in years], None))
    return Challenge(qs)


def verify(challenge: Challenge, answers: dict[str, str]) -> bool:
    """Todas las preguntas deben estar respondidas y correctas. Recorre todo para no filtrar por tiempo."""
    ok = True
    for q in challenge.questions:
        given = answers.get(q.id, "")
        expected = q.correct_option_id or ""
        match = bool(expected) and hmac.compare_digest(given.encode(), expected.encode())
        ok = ok and match
    return ok and len(answers) == len(challenge.questions)

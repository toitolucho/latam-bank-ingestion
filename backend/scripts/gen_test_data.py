"""Genera backend/DATOS_DE_PRUEBA.md: clientes sinteticos del conjunto de datos que cubren cada escenario, con una ficha
por cliente para contestar las preguntas de seguridad.

Uso:  python scripts/gen_test_data.py
Los datos son sinteticos (dataset del organizador); no hay personas reales.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.tools import ToolContext, evaluate_credit, offer_rates  # noqa: E402
from app.auth import kba  # noqa: E402
from app.config import Settings  # noqa: E402
from app.core.fmt import fmt_date, fmt_money, fmt_month_year  # noqa: E402
from app.data.repository import SnapshotRepository  # noqa: E402
from app.policy import credit_engine as ce  # noqa: E402

import argparse

ap = argparse.ArgumentParser()
ap.add_argument("--data-dir", help="carpeta con los parquet (por defecto la que usa el backend)")
ap.add_argument("--out", default="DATOS_DE_PRUEBA.md")
args = ap.parse_args()
S = Settings(_env_file=None, **({"data_dir": Path(args.data_dir)} if args.data_dir else {}))
repo = SnapshotRepository(S.data_dir)
policy = ce.load_policy(S.policy_path)
AS_OF = S.as_of_date
PROD = {"Cuenta Ahorro": "cuenta de ahorro", "Tarjeta Crédito": "tarjeta de crédito", "Cuenta Corriente": "cuenta corriente",
        "Tarjeta Débito": "tarjeta de débito", "Préstamo Personal": "préstamo personal",
        "Préstamo Hipotecario": "préstamo hipotecario", "Inversión": "inversión", "Seguro": "seguro"}
TX = {"Purchase": "compra", "Withdrawal": "retiro"}

rows = []
for r in repo._customers.itertuples():
    cid = r.customer_id
    prof = repo.credit_profile(cid)
    ctx = ToolContext(cid, repo, policy)
    info = offer_rates(ctx)
    probe = info["probe"].decision
    pre = probe.outcome == ce.ELIGIBLE and bool(info["rates"]) and (probe.max_amount or 0) > 0
    income = prof["monthly_income"]
    ok_kba = all(kba.build_challenge(repo, repo.find_by_document(str(r.document_number)), n=3, lang="es", as_of=AS_OF)
                 for _ in range(5))
    rows.append(dict(cid=cid, doc=str(r.document_number), name=r.first_name, country=r.country, ccy=prof["income_ccy"],
                     consent=prof["accepts_marketing"], income=income, score=prof["credit_score"], dpd=prof["max_days_past_due"],
                     band=probe.band, pre=pre, max_amount=probe.max_amount, ok_kba=ok_kba, rates=info["rates"],
                     dti_now=(prof["existing_monthly_debt"] / income) if income else None))
df = pd.DataFrame(rows)


def pick(mask, n=1, prefer_countries=True):
    sub = df[mask & df.ok_kba]
    if sub.empty:
        return []
    out, seen = [], set()
    for _, r in sub.iterrows():
        if prefer_countries and r.country in seen and len(out) < n and sub.country.nunique() > len(seen):
            continue
        out.append(r); seen.add(r.country)
        if len(out) == n:
            break
    return out


SCENARIOS = [
    ("A", "Consiente marketing y está preaprobado: recibe la oferta proactiva al cerrar", pick(df.consent & df.pre, 3)),
    ("B", "NO consiente marketing pero está preaprobado: puede pedir crédito, nunca recibe oferta proactiva", pick(~df.consent & df.pre, 2)),
    ("C", "Sin ingreso registrado: el asistente pide que lo declare (queda provisional)", pick(df.income.isna() & df.score.notna() & (df.dpd <= 30), 1)),
    ("D", "Sin score registrado: no se puede evaluar solo, ofrece derivar", pick(df.score.isna() & df.income.notna(), 1)),
    ("E", "Mora de 31 a 90 días: va a revisión de un asesor", pick((df.dpd > 30) & (df.dpd <= 90) & df.income.notna() & df.score.notna(), 1)),
    ("F", "Mora de más de 90 días: crédito rechazado", pick((df.dpd > 90) & df.income.notna() & df.score.notna(), 1)),
    ("G", "Sin capacidad de endeudamiento (su deuda actual ya supera el 20% del ingreso)", pick(df.dti_now.notna() & (df.dti_now >= 0.2) & (df.dpd <= 30) & df.score.notna(), 1)),
    ("H", "Score muy bajo (banda 1): crédito rechazado", pick((df.band == 1) & (df.dpd <= 30) & df.income.notna(), 1)),
]
# Sin datos suficientes para 3 preguntas: AUTH_UNAVAILABLE
unavail = df[~df.ok_kba]


def docs_line(cid) -> str:
    names = {"id_copy": "copia del documento de identidad", "address_proof": "comprobante de domicilio",
             "income_proof": "comprobante de ingresos"}
    have = sorted(repo.documents_on_file(cid))
    return ("- Documentos que el banco ya tiene: " + (", ".join(names.get(d, d) for d in have) or "ninguno")
            + " (al avanzar con una solicitud solo se piden los que faltan)")


def card(r) -> str:
    cid = r["cid"]
    facts = repo.profile_facts(cid)
    occ = kba.OCCUPATIONS["es"].get(facts["occupation"], facts["occupation"]) if facts["occupation"] else None
    lines = [f"- Ocupación registrada: **{occ}**" if occ else "- Ocupación registrada: (ninguna)",
             f"- Año en que se hizo cliente: **{facts['registration_year'] or '(sin dato)'}**",
             "- Productos activos (año de apertura y, si se abrieron en sucursal, la ciudad; si hay varios del mismo tipo, "
             "el reto pregunta por el más antiguo):"]
    for p in repo.products(cid):
        label = kba.PRODUCT_LABELS["es"].get(p["product_type"], p["product_type"])
        year = pd.Timestamp(p["opening_date"]).year
        if p.get("opening_channel") == "Branch":
            where = f"apertura en sucursal de **{repo.branch_city(p['opening_branch_id'])}**"
        else:
            where = f"apertura por {p.get('opening_channel')} (no se pregunta la ciudad)"
        lines.append(f"  - {label}: {where}, año **{year}**")
    return "\n".join(lines + [docs_line(cid)])


def phrases(r) -> list[str]:
    out = []
    inc = r["income"]
    if r["pre"]:
        out += ["«¿qué tasas tienen para mí?»", "«gracias, eso es todo» (debe llegar la oferta)" if r["consent"] else "«gracias, eso es todo» (NO debe llegar oferta)"]
    if pd.notna(inc) and inc:
        small, big = int(inc * 0.3), int(inc * 6)
        res_s = evaluate_credit(ToolContext(r["cid"], repo, policy), "personal_loan", small, 24)
        res_b = evaluate_credit(ToolContext(r["cid"], repo, policy), "personal_loan", big, 36)
        out += [f"«quiero un préstamo de {small} a 24 meses» → {res_s.decision.outcome}",
                f"«necesito un préstamo de {big}» → {res_b.decision.outcome}"]
        out.append(f"«ahora gano {int(inc * 1.4)} al mes» (tras un rechazo por capacidad, recalcula como provisional)")
        out += [f"«necesito un préstamo de 1000 dólares a 24 meses» → convierte a {r['ccy']} con la tasa de referencia y muestra los equivalentes",
                "«sí» (a «¿Le gustaría que avancemos?») → pide solo los documentos que falten; con todo en orden deriva a un asesor",
                "«gracias, eso es todo» → resumen de la propuesta y aviso del PDF por correo (simulado)"]
    else:
        out += ["«quiero un préstamo de 3000» → pide el ingreso; luego «gano 5000»"]
    out += ["«¿eres un robot?» → responde con la verdad: es el asistente virtual del banco, no una persona",
            "«no reconozco un cargo en mi cuenta» → pide confirmar la derivación; nunca ofrece crédito",
            "«quiero hablar con un asesor» → deriva y muestra el número de seguimiento"]
    return out


def header(r) -> str:
    inc = fmt_money(r["income"], r["ccy"], 0) if pd.notna(r["income"]) else "sin ingreso registrado"
    sc = int(r["score"]) if pd.notna(r["score"]) else "sin score"
    return (f"**{r['name']}** · documento `{r['doc']}` · {r['country']} · moneda {r['ccy']} · ingreso {inc} · score {sc} · "
            f"mora máx. {int(r['dpd'])} días · marketing: {'sí' if r['consent'] else 'no'}")


md = ["# Datos de prueba del asistente",
      "",
      "Todo es **sintético**; no hay personas reales. Se genera con "
      "`python scripts/gen_test_data.py` a partir de los datos que use el backend (`data/fixture/` por defecto).",
      "",
      "## Cómo probar",
      "",
      "1. Abra la interfaz (`http://localhost:8080`) y escriba el **documento** de un cliente de abajo.",
      "2. Responda las **preguntas de seguridad** con la ficha del cliente. Las preguntas cambian en cada intento y salen "
      "de estos mismos datos: su ocupación registrada, la ciudad donde abrió un producto (solo si lo abrió en sucursal), "
      "el año de apertura de un producto y el año en que se hizo cliente. Un producto se nombra por su tipo (o «el más "
      "antiguo» si hay varios del mismo tipo). Las opciones incorrectas son inventadas y las ciudades son siempre del "
      "mismo país. Nunca se pregunta por montos ni fechas exactas.",
      "3. Pruebe las frases sugeridas de cada escenario. Para portugués, cambie el selector de idioma antes de empezar.",
      "",
      "**Flujos de crédito:** tras una evaluación favorable el asistente pregunta si quiere avanzar. Si dice que sí, pide solo los "
      "documentos que al cliente le **faltan** (los que el banco ya tiene figuran en cada ficha); el chat no recibe archivos: el "
      "cliente confirma que cuenta con ellos. Con todo en orden deriva a un asesor. Al terminar (despedida o botón «Terminar "
      "conversación») entrega el **resumen** de la propuesta y avisa que el detalle llegará por correo en un PDF: el correo es "
      "**simulado** (no se envía) y el PDF se descarga desde la interfaz. Si el cliente habla en otra moneda («dólares», «pesos "
      "colombianos»), el asistente la convierte a la de su ingreso con la tasa de referencia del conjunto de datos (fecha de corte, "
      "no cotización en vivo).",
      "",
      "Tres intentos fallidos bloquean ese documento 15 minutos (también un documento inexistente, a propósito). "
      "Para desbloquear, reinicie el backend: `docker compose restart chat-backend`.",
      "",
      "Los montos de los ejemplos están en la moneda del ingreso de cada cliente. Los resultados indicados (eligible, "
      "declined…) son los de la política provisional con los datos de hoy.",
      ""]
for letter, title, custs in SCENARIOS:
    md += [f"## Escenario {letter}: {title}", ""]
    if not custs:
        md += ["_No hay un cliente así en el snapshot actual._", ""]
        continue
    for r in custs:
        md += [header(r), "", card(r), "", "Frases para probar:", ""] + [f"- {p}" for p in phrases(r)] + [""]
md += ["## Escenario I: sin datos suficientes para 3 preguntas (no se puede verificar por este canal)", ""]
if unavail.empty:
    md += ["_No hay un cliente así en el snapshot actual._", ""]
else:
    md += ["Estos documentos reciben el aviso «No es posible verificar su identidad por este canal»: "
           + ", ".join(f"`{d}`" for d in unavail.doc.head(4)), ""]
md += ["## Escenario J: documento inexistente", "",
       "Cualquier número que no esté arriba (por ejemplo `99999999`) recibe preguntas igual que un cliente real, pero nunca "
       "se aprueban: así no se revela qué documentos existen.", ""]
out = ROOT / args.out
out.write_text("\n".join(md), encoding="utf-8")
print("escrito", out, "| escenarios con cliente:", sum(1 for _, _, c in SCENARIOS if c), "de", len(SCENARIOS), "| sin kba:", len(unavail))

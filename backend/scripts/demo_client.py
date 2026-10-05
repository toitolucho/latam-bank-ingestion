"""Cliente de demostracion: simula a una persona que SI conoce sus datos y conversa con el backend en marcha.

Uso:  python scripts/demo_client.py --base http://localhost:8000 [--lang es|pt] [--doc <documento>]

Solo para pruebas de humo: lee el snapshot local para contestar las preguntas de seguridad como lo haria el
titular. No forma parte del backend ni se incluye en la imagen.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.auth import kba  # noqa: E402
from app.config import Settings  # noqa: E402

SNAP = Settings(_env_file=None).data_dir      # snapshot local o, si no existe, el conjunto de ejemplo del equipo


def call(base: str, method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, (json.loads(r.read() or b"{}"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


class Owner:
    """Conoce los datos del titular y elige la opcion correcta de cada pregunta."""

    def __init__(self, document: str):
        cu = pd.read_parquet(SNAP / "customers.parquet")
        row = cu[cu.document_number.astype(str) == str(document)].iloc[0]
        self.cid = row.customer_id
        self.occupation, self.registration = row.get("occupation"), row.get("registration_date")
        self.products = pd.read_parquet(SNAP / "products.parquet").query("customer_id == @self.cid")
        br = pd.read_parquet(SNAP / "branches.parquet")
        self.city = dict(zip(br.branch_id, br.city))

    def _product(self, text: str, lang: str) -> pd.Series:
        """El producto al que apunta el enunciado: su tipo y, si dice 'mas antiguo', el de apertura mas temprana."""
        norm = text.lower()
        for ptype, label in kba.PRODUCT_LABELS[lang].items():
            if label in norm:
                group = self.products[self.products.product_type == ptype].sort_values("opening_date")
                if group.empty:
                    raise ValueError(f"no tiene {label}")
                return group.iloc[0]          # el unico de su tipo o el mas antiguo (el reto solo lo pregunta si no hay empate)
        raise ValueError(f"producto no reconocido en: {text}")

    def answer(self, q: dict, lang: str) -> str:
        text, labels = q["text"], {o["label"]: o["id"] for o in q["options"]}
        if "ocupa" in text:
            return labels[kba.OCCUPATIONS[lang][self.occupation]]
        if "cliente" in text and ("hizo" in text or "tornou" in text):
            return labels[str(pd.Timestamp(self.registration).year)]
        p = self._product(text, lang)
        if "ciudad" in text or "cidade" in text:
            return labels[self.city[p.opening_branch_id]]
        return labels[str(pd.Timestamp(p.opening_date).year)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--lang", default="es", choices=["es", "pt"])
    ap.add_argument("--doc")
    a = ap.parse_args()

    cu = pd.read_parquet(SNAP / "customers.parquet")
    ok = cu[cu.monthly_income.notna() & cu.credit_score.notna() & (cu.credit_score >= 680) & (cu.max_days_past_due == 0)]
    doc = a.doc or str(ok.document_number.iloc[0])
    income = float(cu[cu.document_number.astype(str) == doc].monthly_income.iloc[0])

    st, s = call(a.base, "POST", "/v1/sessions", {"document_number": doc, "language": a.lang})
    print(f"[crear sesion] {st} -> {len(s['auth']['questions'])} preguntas")
    sid, tok = s["session_id"], s["token"]
    owner = Owner(doc)
    for q in s["auth"]["questions"]:
        print("  P:", q["text"])
    answers = [{"question_id": q["id"], "option_id": owner.answer(q, a.lang)} for q in s["auth"]["questions"]]
    st, v = call(a.base, "POST", f"/v1/sessions/{sid}/verify", {"answers": answers}, tok)
    print(f"[verificar] {st} -> {v.get('status')}")
    if v.get("greeting"):
        print("  BOT:", v["greeting"])

    script = {
        "es": ["¿qué tasas tienen para mí?", f"necesito un préstamo de {int(income * 0.3)} a 24 meses",
               f"quiero un préstamo de {int(income * 6)}", f"ahora gano {int(income * 1.4)} al mes", "quiero hablar con un asesor"],
        "pt": ["quais são as taxas para mim?", f"quero um empréstimo de {int(income * 0.3)} em 24 meses",
               f"preciso de um empréstimo de {int(income * 6)}", "quero falar com um atendente"],
    }[a.lang]
    for msg in script:
        st, r = call(a.base, "POST", f"/v1/sessions/{sid}/messages", {"message": msg}, tok)
        print(f"\nTU : {msg}\nBOT: {r.get('reply', r)}\n     [{st}] intent={r.get('intent')} outcome={r.get('outcome')} awaiting={r.get('awaiting')}")
        if r.get("awaiting") == "confirm_handoff":
            st, r = call(a.base, "POST", f"/v1/sessions/{sid}/messages", {"message": "sí" if a.lang == "es" else "sim"}, tok)
            print(f"TU : (confirma)\nBOT: {r.get('reply')}\n     ticket={r.get('handoff_ticket')}")
    st, h = call(a.base, "GET", f"/v1/sessions/{sid}/handoff", None, tok)
    if st == 200:
        print("\n[resumen para el agente]")
        print(json.dumps({k: h[k] for k in ("ticket_id", "reason", "request", "evaluation", "actions_taken", "open_questions")},
                         ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()

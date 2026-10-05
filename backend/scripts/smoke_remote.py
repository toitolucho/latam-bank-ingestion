"""Verifica una URL del asistente de punta a punta antes de compartirla (local, tunel o hosting).

Uso:  python scripts/smoke_remote.py --base https://xxxx.trycloudflare.com [--doc 53464097] [--lang es|pt]

Sin --doc revisa interfaz, API, cabeceras y que la cola de agentes este cerrada. Con --doc (un documento del conjunto de
prueba que use el backend desplegado y cuyos datos esten en esta maquina) tambien autentica y mantiene una conversacion corta.
Termina con codigo 0 solo si todo pasa.
"""
from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from demo_client import Owner, call  # noqa: E402

results: list[tuple[bool, str]] = []


def check(ok: bool, what: str, detail: str = "") -> bool:
    results.append((ok, what))
    print(f"[{'OK ' if ok else 'FALLA'}] {what}{(' -> ' + detail) if detail else ''}")
    return ok


def http_status(url: str) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            return r.status, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers)
    except Exception as e:  # noqa: BLE001
        return 0, {"error": str(e)[:80]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--doc")
    ap.add_argument("--lang", default="es", choices=["es", "pt"])
    a = ap.parse_args()
    base = a.base.rstrip("/")

    st, hdr = http_status(base + "/")
    check(st == 200, "la interfaz carga", f"HTTP {st}")
    check("content-security-policy" in {k.lower() for k in hdr}, "la interfaz envia Content-Security-Policy")
    st, _ = http_status(base + "/health")
    check(st == 200, "el backend responde a /health", f"HTTP {st}")
    st, meta = call(base, "GET", "/v1/meta")
    check(st == 200 and "llm_provider" in meta, "GET /v1/meta", f"{meta.get('llm_provider')} · datos: {meta.get('data_source')}")
    st, _ = http_status(base + "/v1/handoffs")
    check(st == 404, "la cola de agentes NO se expone por el proxy publico", f"HTTP {st}")

    st, s = call(base, "POST", "/v1/sessions", {"document_number": "99999999", "language": a.lang})
    check(st == 201 and len(s.get("auth", {}).get("questions", [])) == 3, "un documento inexistente recibe 3 preguntas (no revela cuales existen)", f"HTTP {st}")
    st, _ = call(base, "POST", f"/v1/sessions/{s.get('session_id', 'x')}/messages", {"message": "hola"}, s.get("token"))
    check(st == 403, "no se puede conversar sin verificar la identidad", f"HTTP {st}")

    if a.doc:
        st, s = call(base, "POST", "/v1/sessions", {"document_number": a.doc, "language": a.lang})
        if check(st == 201, f"sesion para el documento {a.doc}", f"HTTP {st}"):
            owner = Owner(a.doc)
            answers = [{"question_id": q["id"], "option_id": owner.answer(q, a.lang)} for q in s["auth"]["questions"]]
            st, v = call(base, "POST", f"/v1/sessions/{s['session_id']}/verify", {"answers": answers}, s["token"])
            if check(v.get("status") == "authenticated", "las respuestas correctas autentican", f"HTTP {st}"):
                msg = "¿qué tasas tienen para mí?" if a.lang == "es" else "quais são as taxas para mim?"
                st, r = call(base, "POST", f"/v1/sessions/{s['session_id']}/messages", {"message": msg}, s["token"])
                check(st == 200 and bool(r.get("reply")), "una consulta recibe respuesta", f"intent={r.get('intent')} outcome={r.get('outcome')}")
                st, e = call(base, "POST", f"/v1/sessions/{s['session_id']}/end", None, s["token"])
                check(st == 200 and bool(e.get("reply")), "el cierre devuelve un mensaje", f"HTTP {st}")
                call(base, "DELETE", f"/v1/sessions/{s['session_id']}", None, s["token"])

    failed = [w for ok, w in results if not ok]
    print(f"\n{len(results) - len(failed)} de {len(results)} comprobaciones correctas")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

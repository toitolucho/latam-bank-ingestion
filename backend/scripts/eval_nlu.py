"""Evalua el NLU (reglas vs LLM vs hibrido) sobre eval/nlu_cases.py.

Uso:  python scripts/eval_nlu.py [--runs 2] [--no-llm]
Cada llamada al modelo consume saldo (~1 s y unos 500 tokens). 60 frases x runs.
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.nlu import MockNLU, NLUResult  # noqa: E402
from app.agent.orchestrator import validate_nlu  # noqa: E402
from eval.nlu_cases import CASES, HELDOUT, PENDING_TEXTS  # noqa: E402


def score(name: str, predict, cases) -> dict:
    ok = 0
    per_lang: dict[str, list[int]] = defaultdict(list)
    per_intent: dict[str, list[int]] = defaultdict(list)
    sens_tp = sens_fn = sens_fp = 0
    misses = []
    for text, intent, lang, sensitive in cases:
        r: NLUResult = predict(text, text in PENDING_TEXTS)
        r = validate_nlu(r, text)                 # incluye la guardia de derivacion explicita
        hit = r.intent == intent
        ok += hit
        per_lang[lang].append(hit)
        per_intent[intent].append(hit)
        if sensitive and r.sensitive_topic:
            sens_tp += 1
        elif sensitive:
            sens_fn += 1
        elif r.sensitive_topic:
            sens_fp += 1
        if not hit:
            misses.append((text, intent, r.intent))
    n = len(cases)
    print(f"\n### {name}: exactitud de intencion {ok}/{n} = {100 * ok / n:.0f}%  "
          + " | ".join(f"{k}: {sum(v)}/{len(v)}" for k, v in sorted(per_lang.items())))
    print("   por intencion: " + ", ".join(f"{k} {sum(v)}/{len(v)}" for k, v in sorted(per_intent.items())))
    print(f"   tema sensible: detectados {sens_tp}/{sens_tp + sens_fn}, falsos positivos {sens_fp}")
    for t, exp, got in misses:
        print(f"   x '{t}' -> {got} (esperado {exp})")
    return {"acc": ok / n, "sens_fn": sens_fn, "sens_fp": sens_fp}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--heldout", action="store_true", help="usar el conjunto reservado (medir una sola vez al final)")
    a = ap.parse_args()
    rules = MockNLU()
    cases = HELDOUT if a.heldout else CASES
    print(f"{'RESERVADO' if a.heldout else 'DESARROLLO'}: {len(cases)} frases (es/pt). Etiquetas de un solo anotador: revisar antes de citar.")
    score("Reglas (MockNLU)", lambda t, p: rules.extract(t, None, p), cases)
    if not a.no_llm:
        from app.agent.llm_anthropic import AnthropicLLM
        from app.config import Settings
        s = Settings()
        llm = AnthropicLLM(s.anthropic_api_key, s.anthropic_model)
        for run in range(a.runs):
            score(f"LLM {s.anthropic_model} (corrida {run + 1})", lambda t, p: llm.extract(t, None, p), cases)

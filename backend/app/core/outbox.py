"""Bandeja de salida de correos. PROTOTIPO: el correo NO se envia; se guarda lo que se enviaria.

Cada entrada deja un PDF y un JSON con estado `simulated_not_sent`. Solo se guarda el correo ENMASCARADO: la direccion
completa no sale de la capa de datos. En produccion esta clase se reemplaza por un servicio de correo que resuelva el
destinatario del lado del servidor al momento de enviar.
"""
from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path


class Outbox:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.records: list[dict] = []

    def queue(self, *, customer_id: str, to_masked: str | None, subject: str, pdf: bytes, language: str,
              ticket_id: str | None = None) -> dict:
        eid = "EML-" + secrets.token_hex(4).upper()
        pdf_path = self.dir / f"{eid}.pdf"
        record = {"id": eid, "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                  "status": "simulated_not_sent", "customer_id": customer_id, "to_masked": to_masked,
                  "subject": subject, "language": language, "ticket_id": ticket_id, "attachment": pdf_path.name,
                  "attachment_bytes": len(pdf)}
        with self._lock:
            pdf_path.write_bytes(pdf)
            (self.dir / f"{eid}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            self.records.append(record)
        return record

    def pdf_bytes(self, email_id: str) -> bytes | None:
        if not email_id.startswith("EML-") or not email_id[4:].isalnum():
            return None                                  # nada de rutas arbitrarias
        path = self.dir / f"{email_id}.pdf"
        return path.read_bytes() if path.exists() else None

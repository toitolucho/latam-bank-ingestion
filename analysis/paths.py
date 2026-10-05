"""Rutas de datos para los scripts y notebooks de analisis (nada de esto se versiona).

HACKATHON_RAW_DIR   carpeta con las tablas del organizador descargadas (customers.csv, products.csv, complaints/**/*.csv...)
HACKATHON_WORK_DIR  carpeta para parquet derivados (transactions.parquet, gold_customer_credit_profile.parquet...)
Por defecto: <repo>/.local/raw y <repo>/.local/derived (ignoradas por git).
"""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RAW = Path(os.environ.get("HACKATHON_RAW_DIR", REPO / ".local" / "raw"))
WORK = Path(os.environ.get("HACKATHON_WORK_DIR", REPO / ".local" / "derived"))
WORK.mkdir(parents=True, exist_ok=True)

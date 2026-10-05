# Datos: procedencia, hallazgos y cómo reconstruirlos

## Qué datos usa el proyecto

| Dato | Origen | ¿Está en el repositorio? |
|---|---|---|
| Dataset del organizador (13 tablas, banco sintético en México, Colombia y Argentina, jun-2023 a jun-2026) | Bucket S3 del organizador, acceso de solo lectura | **No** |
| Snapshot derivado (225 clientes con productos y movimientos recientes, más el perfil crediticio) | Generado por `backend/scripts/build_snapshot.py` a partir del dataset | **No** (`backend/data/snapshot/`, en `.gitignore`) |
| Conjunto de ejemplo del equipo (21 clientes) | Inventado por el equipo con semilla fija: `backend/scripts/make_fixture.py` | Sí (`backend/data/fixture/`) |
| Política de crédito (tope de endeudamiento, bandas de score, tasas) | Inventada por el equipo | Sí (`backend/policy/credit_policy.yaml`) |
| Conversaciones y frases de prueba del NLU | Escritas por el equipo (un solo anotador) | Sí (`backend/eval/nlu_cases.py`) |

## Hallazgos que condicionaron el diseño

Medidos sobre las tablas descargadas del organizador.

| Hallazgo | Evidencia | Consecuencia |
|---|---|---|
| No hay señal de riesgo de crédito aprendible | Correlación entre `credit_score` y `days_past_due`: −0,004. Solo 4,7% de los créditos tienen más de 90 días de mora | No se entrena un modelo de riesgo; se usa una política de reglas explícitas |
| Los textos de llamadas no sirven para etiquetar intenciones | `detected_intents` vale "consulta_general" en el 100% de las filas. 546 textos distintos entre 171.321 transcripciones. `contact_reason` repite 6 categorías | La intención se evalúa con frases escritas por el equipo |
| Las quejas no se pueden ligar a una transacción ni a una llamada | `complaints` no tiene `transaction_id`; `origin_interaction_id` es 100% nulo; las descripciones son plantillas | Se usó `fraud_score` y `is_fraud` solo como baseline de triaje de riesgo |
| Nulos relevantes | `credit_score` 15,0%; ingreso estimado 19,9% | Ruta de "datos faltantes": se pide el ingreso o se deriva |
| Moneda inconsistente | Todos los productos de México están en USD, con ingreso en MXN | Conversión con la tasa de la última fecha (`daily_exchange_rates`) |
| El dataset no trae cuotas | Ningún campo de cuota mensual | La deuda mensual se **estima** con supuestos declarados en la política |
| Variantes de país | "México"/"Mexico" en `transaction_country` e `ip_country` | Normalización en la capa silver |
| Filas menores a las documentadas | Quejas 67.095 de 80.000; transacciones 4,43 M de 5 M; llamadas 686.296 de 800.000. `digital_events` trae **más** (15,6 M frente a 10 M) | Preguntar a los organizadores; no se asume pérdida de datos |
| Sin claves duplicadas | 0 duplicados por clave primaria en clientes, productos y quejas | La deduplicación del handoff es inocua pero no demuestra el "2%" documentado |
| Integridad de claves | `registration_branch_id` casi nunca cruza con sucursales (5 de 150.000); la fecha de registro nunca coincide con la del primer producto | Las preguntas de seguridad usan **productos** (año y ciudad de apertura) y el perfil (ocupación). El año de registro solo entra como una pregunta más (`customer_since`) para llegar al 87% de cobertura; ver `backend/README.md` |
| `digital_events` y `campaign_sends` no aportan al crédito | 24% de los eventos sin `customer_id`; el país por IP coincide 100% con el del cliente; conversión de campañas 0,3% a 0,7% | Fuera de alcance |
| Fraude | 0,1% de las transacciones. `fraud_score` medio 49,5 en fraudes y 15,0 en el resto. Sin `fraud_score`, ningún modelo supera al azar | Solo baseline de triaje |
| Edades atípicas | 29% de los clientes tiene 66 años o más; 10.422 clientes sin productos | No se usa la edad en ninguna decisión |

## Revisión de la capa gold del handoff

Se ejecutaron las consultas `gold_customer_*` del documento de traspaso sobre los datos reales
(`analysis/scripts/validate_handoff.py`). Confirmaron cifras del handoff (67.095 quejas, 54.145 clientes, 10.045 requests y
suggestions, tasas medias 31,5% / 20% / 9%) y detectaron problemas en `gold_customer_eligibility_summary`:

1. El filtro `accepts_marketing = true` deja fuera al **50%** de los clientes (75.007 de 150.000), incluyendo a quienes piden un crédito.
2. La columna de elegibilidad puede ser `NULL` (11,3%) cuando falta el score.
3. La regla ignora el ingreso: 20% de los "elegibles" no tienen ingreso registrado, y el 31,1% de ellos no los aprueba la política con capacidad de pago.
4. Suma saldos y límites de varias monedas sin convertir (1.676 clientes con tarjetas activas en más de una moneda).
5. Usa `current_date`, por lo que la antigüedad cambia cada día; se fijó la fecha de corte del dataset.
6. Marca como morosos a 909 clientes por productos ya cerrados.

`data/sql/gold_customer_credit_facts.sql` corrige estos puntos: entrega **hechos** para los 150.000 clientes (con el
consentimiento como columna) y la decisión la toma el motor de política. La deuda mensual estimada coincide con la del
perfil calculado en pandas en los 150.000 clientes (diferencia máxima 0).

## Reconstruir los datos derivados

Requiere acceso al bucket del organizador (credenciales que entrega el organizador; **nunca** se suben al repositorio).

```bash
export HACKATHON_RAW_DIR=/ruta/a/las/tablas          # customers.csv, products.csv, complaints/**/*.csv, ...
export HACKATHON_WORK_DIR=/ruta/a/derivados          # por defecto <repo>/.local/derived
python analysis/scripts/eda1.py                      # parquet de transacciones, quejas y llamadas
python -m jupyter nbconvert --to notebook --execute --inplace analysis/notebooks/baseline_credito.ipynb   # perfil crediticio
python backend/scripts/build_snapshot.py --customers 400                                                   # snapshot del backend
```

## Databricks medallion and credit layers

The data and the credit flow are also built in Databricks (Unity Catalog, `workspace` catalog)
by the `latam_bank_medallion` job: bronze → silver → gold, with quality metrics on every run.
Run order, objects, quality checks and results are in `data/databricks/README.md`; policy and
formulas in `docs/CREDIT_RULES.md` (policy 0.4, the reference version of the credit rules).
Every file takes the schemas as parameters, so the same code runs against the `_test` schemas.

| Layer | Objects | Notes |
|---|---|---|
| bronze `bronze_latam_bank` | The 10 landing entities (`customers`, `products`, `transactions`, `complaints`, `call_center_interactions`, ...) | Loaded as delivered from the daily CSVs (`01_bronze.py`): all STRING, `_rescued_data` for schema changes; `complaints` and `call_center_interactions` verified against the source files (rows per file, nulls per column, numeric sums, text length) |
| silver `silver_latam_bank` | The same 10 tables, typed and deduplicated; `ref_product_catalog`, `ref_term_grid`, `ref_policy_params`, `ref_policy_bands`, `ref_segment_adjustments` | `02_silver.sql`: real types, one row per business key; synthetic reference tables from `data/reference/` (catalog, pricing, policy) stand in for source data the dataset lacks |
| gold `gold_latam_bank` | `customer_credit_profile`, `customer_credit_offer_options`, `credit_offers`, `customer_products_summary`, `customer_complaints_summary`, `customer_cashflow_summary`, `pipeline_quality_metrics`, `fn_monthly_installment`, `fn_max_principal` | Indicators and baseline offers for all 150,000 customers as of 2026-06-30; `credit_offers` stores offers accepted in the chat; `pipeline_quality_metrics` keeps the quality metrics of every run |

Findings from building these layers that complement the table above:
- Observed deposits are sparse (median under 2 per year per customer) and a median 20% of
  declared income, so the credit rules use declared income for the 20% limit.
- `amount_usd` is null for every USD transaction; silver fills it with `amount` for USD.
- `transaction_country` has "Mexico" without the accent in 40,515 rows; silver normalizes it to "México".
- Loans have no `expiration_date`; existing loan installments use the synthetic term grid.
- In bronze every column is a string and `credit_score` comes as `'805.0'`, so `CAST(... AS INT)`
  fails; silver casts to `DOUBLE` first.
- No key or content duplicates in the files (only 6 repeated `product_number` values across
  different products), against the "~2%" of the dataset documentation.

## Controles de calidad que existen hoy

Ejecutados en los notebooks (`analysis/notebooks/`): unicidad de claves primarias, integridad de claves foráneas, rangos
de fechas y montos, existencia de tipo de cambio por par de monedas, y tasa de nulos. **No hay todavía** un contrato de
datos formal ni una política de frescura automatizada; con datos estáticos, la corrección de una actualización
tendría que demostrarse con un fixture etiquetado.

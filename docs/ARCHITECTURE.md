# Arquitectura

Chat de crédito con verificación de identidad, política determinista, oferta proactiva y derivación a un humano.
Datos y política sintéticos (prototipo).

## Decisión principal: el LLM habla, el código decide

| Función | Quién la hace | Por qué |
|---|---|---|
| Entender el mensaje, detectar idioma, sentimiento y tema delicado | LLM, salida JSON validada | Es lenguaje, no decisión |
| Redactar saludos, cierres y preguntas de aclaración | LLM, **solo mensajes de bajo riesgo** | Las decisiones y ofertas salen de plantillas revisadas |
| Elegibilidad, monto máximo y tasa | Motor determinista (`backend/app/policy/credit_engine.py`); reference rules: policy 0.4 ([`CREDIT_RULES.md`](CREDIT_RULES.md)), computed in gold and implemented in `data/policy/` | El modelo no puede aprobar ni inventar reglas |
| Datos y permisos del cliente | Herramientas (`backend/app/agent/tools.py`), con el `customer_id` de la sesión autenticada | Ninguna herramienta recibe un `customer_id` del modelo |
| Derivar a un humano | Código: solo si el cliente lo pidió de forma explícita o confirmó una oferta de derivación | Una derivación es una acción |
| Cuándo ofrecer crédito sin que lo pidan | Código (`backend/app/agent/proactive.py`) | Es una decisión comercial y de consentimiento |
| Riesgo predictivo de crédito | **No se entrena** | Sin señal en los datos (correlación −0,004; ver `docs/DATA.md`) |

## Flujo

```
Cliente ─► Interfaz (nginx) ─► /v1 ─► API FastAPI ─► Orquestador
                                        │               ├─► NLU: Claude o reglas (esquema canónico en español)
                                        │               ├─► Validación en código (montos, plazos, derivación explícita)
                                        │               ├─► Política de crédito + herramientas
                                        │               └─► Plantillas es/pt (+ reescritura acotada del LLM)
                                        └─► Sesión (JWT atado a la sesión) · bloqueo por documento · logs JSON con trace_id
```

El nginx de la interfaz sirve la página y reenvía `/v1` al backend agregando la clave de integración en el servidor; el
puerto del backend no se publica y `/v1/handoffs` (cola de la consola del agente) se bloquea en el proxy.

## Conversación de crédito: moneda, solicitud y cierre

El orquestador sigue siendo una máquina de estados (`awaiting`: `offer_interest`, `amount`, `income`, `proceed`, `docs_all`,
`doc_item`). La moneda se detecta y convierte en código (`money.py`); los documentos pendientes salen de la política y de
`docs_on_file` (`documents.py`); el cierre (`/end`) arma el resumen y deja el PDF en una bandeja simulada (`core/outbox.py`,
`core/pdf.py`). El LLM solo clasifica y redacta mensajes de bajo riesgo; la identidad (¿eres un robot?) se responde con
plantilla y cualquier texto que afirme ser humano se descarta.

## Autenticación

Tres preguntas de seguridad de opción única generadas desde los datos del cliente: ocupación registrada, ciudad donde
abrió un producto (solo si fue en sucursal), año de apertura de un producto y año en que se hizo cliente. Sin montos ni
fechas exactas; los distractores salen siempre del mismo universo (mismo país, años válidos) y el enunciado no lleva datos
reales como terminaciones. Se exigen todas correctas; 3 fallos bloquean el documento 15 minutos; un documento inexistente
recibe un reto señuelo con la misma forma. Límite conocido: adivinar acierta 1 de 64 veces por intento. Detalle, cobertura
medida y límites en `backend/README.md`.

## Oferta proactiva

Al cerrar la conversación se ofrece un préstamo personal indicativo **solo si** el cliente acepta marketing, está
preaprobado con datos del banco (no con ingreso declarado en el chat), no hubo sentimiento negativo ni tema delicado, no
se le rechazó una solicitud, no se ofreció ya y **no le queda nada pendiente** (ni un tema de soporte en la sesión, ni un
caso crítico abierto, ni uno abierto en los últimos 180 días). Quien pide un crédito se evalúa **sin** mirar el
consentimiento de marketing: ese consentimiento solo gobierna lo proactivo.

## Soporte y contexto del cliente

El agente atiende primero lo que el cliente trae. Al autenticar lee, una vez, sus casos abiertos y la existencia de sus
productos (lista blanca de campos: nunca saldos, movimientos ni montos). Responde con datos verificados (que un producto
existe, categoría, fecha y estado de un caso), anota lo que el cliente cuenta como declarado y ofrece conectar con un
asesor; no deriva solo. El resumen para el asesor lleva ese contexto, el ánimo, una prioridad y una ruta sugeridas.
Detalle y límites en `backend/README.md`.

## Idioma

El LLM no traduce como paso aparte: entiende el mensaje y devuelve valores canónicos en español (intención, producto,
monto, ingreso, idioma). La respuesta sale en el idioma de la sesión desde plantillas revisadas en español y portugués.
Los montos y plazos se interpretan en **código** con formatos locales (1.500,00 y 1,500.00). Los datos del organizador no
traen portugués: las pruebas en ese idioma las escribió el equipo. Pendiente de confirmar con los organizadores si el
portugués es requisito real (el enunciado lo pide de forma explícita).

## Datos

The data layer runs in **Databricks** (Unity Catalog) as a medallion pipeline defined as code
([`data/databricks/`](../data/databricks/README.md), Databricks Asset Bundle):

```
S3 (organizer CSVs) → landing → bronze (all STRING, _rescued_data, lineage)
  → silver (typed, deduplicated by key, latest version wins)
  → gold: customer_credit_profile, customer_credit_offer_options, credit_offers, customer summaries
```

- **Credit policy as data:** the silver `ref_*` tables (catalog, rate and term grid, bands, segments, parameters) come from
  [`data/reference/`](../data/reference/) and are version 0.4 of the rules ([`CREDIT_RULES.md`](CREDIT_RULES.md)). Gold
  uses them to compute eligibility and offers for the 150,000 customers.
- **Jobs:** `latam_bank_medallion` (bronze → gold, ~14 min, daily at 06:00 but paused because the data is static),
  `credit_policy_refresh` (recomputes offers when the policy changes, ~1 min), `credit_gold_deploy` and
  `data_update_fixture_test`. Bounded retry per task, timeouts and one run at a time.
- **Quality and contract:** every run writes its metrics to `pipeline_quality_metrics` (history, failed runs included) and
  then stops if one fails: key and content duplicates, nulls per critical column with its own threshold, rescued rows from
  schema changes, the 20% capacity and band terms in the offers, and the **contract** of columns and types the API reads.
- **Freshness and updates:** the data ends in June 2026 and no new deliveries arrive; offers are computed as of 2026-06-30
  (`as_of_date`, a job parameter). With live data the cutoff would be the run date, and each run absorbs late arrivals
  (full reload and dedup by `process_date`). Update correctness is shown with a labeled fixture: late update, exact
  duplicate, late arrival, schema change and null key, all five handled correctly.
- **Consumption:** the backend reads a Parquet export of gold behind the `CustomerRepository` interface
  (`data/scripts/export_gold.py`), with no Databricks credentials in the container; in production it would read gold with
  row filters. Without the export it uses the team's sample set. `data/sql/` keeps the DuckDB version for local work.
- **Access (today and in production):** during the hackathon the team has broad permissions on the schemas. In
  production: a pipeline service principal writes bronze/silver/gold; an API service principal only reads the profile and
  options and inserts into `credit_offers`; people get read-only access.
- **Retention:** bronze and silver can be rebuilt from the source CSVs. `credit_offers` holds `customer_id` and would be
  kept for what each country's credit regulation requires, with `VACUUM` of the Delta history; quality metrics are kept as
  the pipeline audit trail.
- **Capacity:** the full job processes ~23 M rows in ~14 min on a 2X-Small serverless warehouse; the offer refresh takes
  ~1 min and grows with customers × 12 options. The API does not query Databricks online.

## Operación

- **Trazabilidad:** cada petición lleva `X-Trace-Id`; los logs son JSON con latencia, intención, resultado y, para el modelo,
  tokens y tiempo. No se registran documentos, respuestas de seguridad ni cuerpos de petición.
- **Reintentos acotados y respaldo seguro:** el cliente del modelo reintenta una vez; si falla o devuelve algo inválido, el
  turno cae al extractor por reglas. El texto del modelo se descarta si trae cifras ajenas a los hechos calculados.
- **Contenedores:** imágenes sin privilegios y con sistema de archivos de solo lectura; `docker compose up` levanta todo.
- **Costo:** una llamada al modelo para entender cada mensaje, más otra solo para mensajes de bajo riesgo. Con Haiku 4.5 se
  midieron ≈ 490 tokens de entrada y ≈ 105 de salida por turno (muestra pequeña).

## Qué falta para producción

- Externalizar el estado en memoria (sesiones, bloqueos y cola de derivaciones) para varias réplicas.
- Un segundo factor de autenticación real; las preguntas actuales son una simulación con datos del mismo dataset.
- Persistir la última oferta por cliente (hoy el tope de una oferta es por sesión) y límite de peticiones por IP.
- Business validation of the credit policy, and a learned risk model evaluated against the `credit_score` baseline
  (today the band comes from the score).
- Evaluación de punta a punta con un conjunto reservado de conversaciones (ver `docs/EVALUATION.md`).
- Data: least-privilege service principals, alerts on `pipeline_quality_metrics`, automatic bundle deployment from CI,
  incremental loads by `process_date` if new deliveries arrived, and the backend reading gold online.

# backend

Backend FastAPI del chat de crédito: verifica la identidad con preguntas de seguridad, conversa en español y
portugués, aplica una política de crédito determinista y deriva a un humano con un resumen estructurado.
Está **desacoplado de cualquier interfaz**: cualquier sitio o canal que hable HTTP/JSON puede integrarlo.

> Datos y política **sintéticos**. No es un sistema bancario real. Ver "Límites conocidos".

## Arranque rápido

Con Docker (requiere Docker Desktop en ejecución):

```bash
docker compose up --build
```

Sin Docker:

```bash
pip install -r requirements-dev.txt
CHAT_JWT_SECRET=un-secreto-de-al-menos-32-caracteres uvicorn app.main:app --port 8000
```

La API queda en `http://localhost:8000`; la documentación interactiva (OpenAPI) en `/docs`.
`CHAT_LLM_PROVIDER=mock` es el valor por defecto: funciona sin red ni clave.

Prueba de humo completa (simula a un titular que conoce sus datos y conversa en es o pt):

```bash
python scripts/demo_client.py --base http://localhost:8000 --lang es
```

## Flujo de integración

```
POST /v1/sessions                      documento + idioma   -> session_id, token, 3 preguntas de seguridad
POST /v1/sessions/{id}/verify          respuestas           -> authenticated | failed (nuevo reto) | 403 bloqueado
POST /v1/sessions/{id}/messages        mensaje              -> respuesta, intención, resultado, ticket de derivación
GET  /v1/sessions/{id}/handoff         resumen para el agente humano (de esa sesión)
GET  /v1/handoffs                      cola de derivaciones (consola de agentes, clave aparte)
POST /v1/sessions/{id}/end             cierre: resumen de la propuesta + aviso de correo (simulado)
GET  /v1/sessions/{id}/summary.pdf     PDF del resumen (solo si hubo propuesta)
DELETE /v1/sessions/{id}
GET  /health  ·  GET /v1/meta
```

- Todas las llamadas de `/v1` envían `X-API-Key` si hay claves configuradas (`CHAT_API_KEYS`), y las de una sesión
  envían además `Authorization: Bearer <token>`.
- El cliente nunca ve las respuestas correctas: recibe ids de opción aleatorios por reto.
- Los errores tienen siempre la forma `{"error": {"code", "message", "trace_id"}}`. Códigos: `INVALID_API_KEY`,
  `INVALID_TOKEN`, `SESSION_EXPIRED`, `AUTH_REQUIRED`, `AUTH_LOCKED`, `AUTH_UNAVAILABLE`, `MESSAGE_TOO_LONG`,
  `VALIDATION_ERROR`, `NO_HANDOFF`, `SESSION_ENDED`, `NO_SUMMARY`, `INTERNAL_ERROR`.
- `verify` devuelve además `customer` (id, nombre, país, segmento, estado: sin documento ni datos financieros) al autenticar.
- `messages` y `end` devuelven `evidence` **solo si el agente usó herramientas en ese turno** (`null` en un saludo o un
  agradecimiento): `steps[]` (herramientas ejecutadas de verdad y su estado), `verification[]` (`verified`, `inconclusive`,
  `unverified` para datos declarados por el cliente, `reference` para tasas de referencia), `customer` (perfil leído) y
  `evaluation` (evaluación de política de este turno). Se arma en `app/agent/evidence.py` desde las llamadas reales a
  `tools.py`; si una herramienta falla, `verification` va vacío. La interfaz solo pinta esto: no infiere verificaciones.
- Cada respuesta lleva `X-Trace-Id` (se acepta uno entrante) para correlacionar con los logs JSON.
- Un sitio web externo debe llamar a esta API **desde su servidor**: una `X-API-Key` en el navegador no es secreta.
  Para llamadas directas desde el navegador, configure `CHAT_CORS_ORIGINS` y trate la clave como identificador.

Ejemplo (documentos del conjunto de ejemplo del equipo, ver `DATOS_DE_PRUEBA.md`; p. ej. `53464097`, México):

```bash
curl -s localhost:8000/v1/sessions -H 'Content-Type: application/json' \
     -d '{"document_number":"53464097","language":"es"}'
```

## Autenticación por preguntas de seguridad

Tres preguntas de tipos distintos, cuatro opciones cada una, generadas desde los datos del cliente. La serie (ocupación,
ciudad y años) se eligió midiendo cada candidata con los 150.000 clientes: **sin montos, sin fechas exactas y sin pedir
recordar una operación**.

| Tipo | Ejemplo | Cobertura | Acierto al azar |
|---|---|---|---|
| `occupation` | ¿Cuál es su ocupación registrada en el banco? | 90% | 25% (20 valores uniformes) |
| `product_city` | ¿En qué ciudad abrió su cuenta de ahorro? (solo productos abiertos en sucursal) | 63% | 25%, con distractores del **mismo país** |
| `product_year` | ¿En qué año abrió su tarjeta de crédito más antigua? | 90% | 25% |
| `customer_since` | ¿En qué año se hizo cliente del banco? | 100% | 25% |

Con estos cuatro tipos, el **87%** de los clientes tiene datos para 3 preguntas de tipos distintos (con la serie anterior,
el 79%). Quien no los tiene recibe `AUTH_UNAVAILABLE` y se le deriva a un asesor.

Reglas de diseño:
- **Un producto se nombra por su tipo** ("su cuenta de ahorro") o, si hay varios del mismo tipo, "el más antiguo" (sin
  empate). Nunca por su terminación: el enunciado se muestra **antes** de autenticar y no debe llevar datos reales.
- **Los distractores salen del mismo universo que la respuesta**: ciudades del mismo país y años válidos. Con
  distractores de los tres países (solo hay 16 ciudades), quien conoce el país del cliente acertaba el 63%.
- **La ciudad solo se pregunta si el producto se abrió en sucursal**: quien abrió online no tiene una ciudad que recordar.
- **Se prefiere un solo tipo de año** por reto. Con dos, el año de alta y el de apertura pueden no cuadrar en estos datos.
- Se exigen **todas** correctas; 3 fallos por documento bloquean 15 minutos (incluso en sesiones nuevas); cada fallo
  entrega preguntas nuevas; la verificación es en tiempo constante; el LLM no ve ni genera las preguntas.
- Un documento inexistente recibe un **reto señuelo**: los *tipos* de pregunta salen de un cliente real al azar (la
  mezcla coincide con la de los clientes reales) y el contenido es inventado, nunca de ese cliente.

Por qué se descartaron las anteriores (medido): el **monto** de una operación es difícil de recordar y un atacante que
elige el valor central acierta el 45%; la **ciudad de una operación** coincide con la ciudad de residencia en el 95% de las
operaciones; el **mes** de apertura exige más memoria que el año. Tampoco entran la fecha de nacimiento (está en el
documento), el teléfono, el vencimiento de la tarjeta (impreso en ella), el estado civil ni la educación (sensibles), ni
el comercio más frecuente (solo el 3% de los clientes tiene una categoría claramente dominante).

**Límites conocidos.** (1) El texto de la pregunta todavía revela el *tipo* de un producto del cliente antes de
autenticar (sin terminación): menos que antes, pero no es cero. (2) `customer_since` usa la fecha de registro, que en este
dataset no cuadra con la del primer producto (`docs/DATA.md`): se mantiene para llegar al 87% de cobertura; sin él, bajaría
al 57% (ocupación + ciudad + año de apertura obligatorios). (3) Todo se midió sobre datos sintéticos: con datos reales
las distribuciones serán distintas. (4) La verificación por preguntas es débil por naturaleza; lo que protege es el límite
de intentos y el bloqueo.

## Agente

- **LLM** (opcional): extrae intención y datos a un esquema canónico en español y puede reescribir la respuesta
  para sonar más natural. No decide, no calcula, no ejecuta acciones.
- **Código**: contrasta montos y plazos con el texto original, interpreta formatos numéricos es/pt, aplica la
  política (`policy/credit_policy.yaml` + `app/policy/credit_engine.py`) y ejecuta las herramientas.
- **Herramientas**: ninguna recibe `customer_id`; el contexto lo fija la sesión autenticada.
- **Acciones con confirmación**: derivar a un humano solo ocurre tras un "sí" explícito (o si el cliente lo pide).
- **Respuesta del LLM**: se descarta si contiene números que no están en los hechos calculados.
- **Resumen de derivación**: solicitud, evaluación con versión de política, hechos verificados, acciones, preguntas
  abiertas y los últimos mensajes. Sin cadena de pensamiento del modelo. Con contexto del cliente: ver "Soporte, contexto
  y resumen para el asesor".

Para usar Claude: `CHAT_LLM_PROVIDER=anthropic` y `ANTHROPIC_API_KEY` en `.env` (no entra en la imagen). Si la llamada
falla o devuelve algo inválido, el turno cae al extractor por reglas.

**Qué puede hacer el modelo y qué no** (verificado con pruebas sin red y con el modelo real):

- Extrae intención y datos. El código contrasta montos y plazos con el texto original, y una **derivación a humano solo
  se acepta si el cliente la pidió de forma explícita**; un incidente (cargo no reconocido, fraude) pide confirmación.
- Solo reescribe mensajes de bajo riesgo (saludo, cierre, preguntas de monto o ingreso, aceptación o rechazo de una
  oferta, y en soporte: tema ajeno, incidente, detalle anotado). Las decisiones de crédito, las ofertas, las derivaciones,
  los avisos de simulación y **todo mensaje con hechos del banco** (productos, casos abiertos) salen **siempre de la
  plantilla revisada**: el guardia de números no detecta frases nuevas que cambien el compromiso. Se ajusta con
  `CHAT_LLM_REWRITE_KINDS` (lista por comas; `none` = el modelo nunca reescribe).
- Su texto se descarta si trae números que no están en los hechos calculados, si **promete** algo (resultado, plazo,
  reembolso: "se resolverá", "le garantizo"…) o si, en un mensaje que espera respuesta (p. ej. "¿lo conecto?"), deja de
  preguntarlo.

Medición con `claude-haiku-4-5-20251001` (13 turnos, 5 conversaciones en es/pt, `scripts/e2e_llm.py`):
18 llamadas, 0 caídas a reglas, latencia por llamada p50 ≈ 1,1 s y p95 ≈ 1,7 s, unos 490 tokens de entrada y 105 de
salida por turno. Es una muestra pequeña, no un benchmark. `scripts/smoke_llm.py` prueba la clave y la extracción.

### Evaluación del NLU (intención, sentimiento, tema delicado)

`python scripts/eval_nlu.py` mide el extractor por reglas y el modelo con frases en es/pt (`eval/nlu_cases.py`).
Hay un conjunto de desarrollo (78 frases, usado para afinar el prompt y las reglas) y uno reservado (29 frases,
escrito antes de afinar y medido una vez).

| Conjunto | Reglas | Claude (claude-haiku-4-5) |
|---|---|---|
| Desarrollo (78), **optimista**: se afinó mirando estos fallos | 77/78 (99%) | **sin remedir** (ver abajo) |
| **Reservado (29)**, ya visto: **no es limpio** (ver abajo) | 27/29 (93%) | 28/29 y 27/29 con el prompt anterior |

**Cambio de taxonomía (soporte).** Se agregaron las intenciones `account_inquiry` (saldo, movimientos, qué productos
tiene) y `case_status` (estado de un reclamo o caso ya abierto); un incidente sigue siendo `other_topic` con
`sensitive_topic`. Por eso se **reetiquetaron 4 frases** (saldo/extracto → `account_inquiry`, "llevo semanas con un
reclamo sin respuesta" → `case_status`) y se agregaron 13 al desarrollo. Al medir, "alguien usó mi tarjeta sin permiso"
pasó de tema ajeno a `account_inquiry` (un reporte de fraude recibiría "sí veo su tarjeta"); se corrigió ampliando los
marcadores de uso no autorizado en las reglas. **Esa corrección se hizo viendo una frase del reservado, así que el
reservado ya no es limpio para las reglas.** El prompt de Claude también cambió (intenciones nuevas, tono, promesas) y
**no se volvió a medir con el modelo real** (no hay clave en el entorno de desarrollo): hay que correr
`python scripts/eval_nlu.py` con `ANTHROPIC_API_KEY` antes de citar una cifra del modelo.

Antes de afinar, el modelo acertaba 49/60 (82%): confundía tasas y límites con otro tema en portugués y tomaba "no
gracias" como despedida por no saber que había una pregunta pendiente (ahora se le informa). En el reservado, el único
fallo constante era "necesito que me atienda una persona": lo degradaba la guardia de derivación explícita porque su
léxico no la cubría; se amplió el léxico, pero **esa corrección se hizo mirando el reservado, así que esa cifra ya no
es limpia**. Detección de tema sensible (reglas): 2/2 en el reservado y 9/10 en desarrollo, 0 falsos positivos. Límites: muestra
pequeña, etiquetas de un solo anotador (el equipo debe revisarlas), y las dos corridas del modelo difieren en una frase.

## Oferta proactiva de crédito

El chat ofrece un crédito por iniciativa del banco solo al **cerrar la conversación** ("gracias", "eso es todo"), y solo
si no se atendió ningún tema de soporte en la sesión: **ya no se ofrece crédito justo después de derivar un problema**.
Es una decisión en código (`app/agent/proactive.py`); el LLM solo redacta el mensaje. La respuesta de `/messages` trae
`proactive_offer: true` y `awaiting: "offer_interest"`.

| Camino | Qué mira | Qué NO mira |
|---|---|---|
| **Reactivo**: el cliente pide un crédito, tasas o su capacidad | Política de crédito con datos del banco (y el ingreso que declare, como provisional) | `accepts_marketing` |
| **Proactivo**: el banco ofrece | Todo lo siguiente a la vez (abajo) | El ingreso declarado en el chat |

Se ofrece solo si se cumplen **todas**: el cliente acepta marketing; está preaprobado por la política con datos del
banco; no hubo sentimiento negativo ni tema delicado (fraude, disputa, reclamo, tarjeta robada, cargo no reconocido) en
la sesión; no se le rechazó una solicitud en la sesión; y no se ofreció ya ni dijo que no. Además **no le queda nada
pendiente**: ni un tema de soporte en esta conversación, ni una derivación, ni un caso **crítico** abierto, ni un caso
abierto en los últimos 180 días. Si acepta, entra al flujo normal de elegibilidad; si rechaza, no se repite. La oferta
queda en `actions_taken` y `verified_facts` del resumen de derivación para que el agente la vea.

## Soporte, contexto y resumen para el asesor

Antes de hablar de crédito, el agente atiende lo que el cliente trae. Reglas: **solo confirma que un producto existe y
deriva el detalle**; nunca muestra saldos, movimientos, montos ni resoluciones.

- **Contexto al autenticar** (`app/agent/context.py`, `sessions.verify`): casos abiertos del cliente (reclamos abiertos de
  cualquier edad e interacciones sin resolver en 90 días; tabla gold `customer_case_context`, en el snapshot
  `case_context.parquet`) y existencia de productos. El repositorio solo entrega una lista blanca de campos.
- **Bienvenida**: si hay un caso abierto de **≤ 180 días**, abre con él ("Veo un reclamo sobre… ¿quiere que le cuente?");
  los más antiguos no se mencionan (en los datos hay reclamos "abiertos" desde hace años) pero sí van al asesor.
- **Intenciones de soporte**: `account_inquiry` (¿tengo una tarjeta?, mi saldo → confirma tipo y terminación y ofrece
  derivar), `case_status` (categoría, fecha y estado del caso; el avance lo informa un asesor), incidentes (fraude,
  cargo no reconocido: se reconoce, se pide lo básico y se ofrece conectar) y otros temas (se anota y se ofrece conectar).
  Ninguno deriva solo: la derivación sigue exigiendo un "sí".
- **Notas del cliente**: lo que cuenta mientras decide queda anotado como *declarado, sin verificar*. Números largos
  (tarjetas, cuentas, documentos) y correos se omiten en las notas y en los últimos mensajes del resumen.
- **Empatía**: si el cliente se muestra molesto, la respuesta abre reconociéndolo (no más de una vez cada 3 turnos).
- **Resumen v2** (`GET /v1/sessions/{id}/handoff`, `GET /v1/handoffs`): además de lo anterior trae `topic`, `case_notes`,
  `customer_context` (casos abiertos priorizados, conteos, banderas, productos), `sentiment` (curva y frustración),
  `priority` (`normal|high|urgent`), `suggested_route`, `suggested_next_actions` y `narrative` (párrafo para leer de un
  vistazo). La narrativa la escribe el código; si hay LLM, la suya la reemplaza solo si no agrega datos ajenos al
  resumen ni promesas (`narrative_source`: `rules` o `llm`). Con el modelo real, esta ruta **no está probada**.

Límites: el tope de una oferta por sesión no se persiste entre sesiones (hace falta guardar la última oferta por
cliente); la oferta indica la capacidad máxima de la política (20% de endeudamiento), lo cual es agresivo para una
propuesta comercial: conviene que el equipo decida un tope menor; y el sentimiento y el tema delicado los detecta
un léxico simple en modo `mock`, no un modelo.

## Moneda, solicitud, resumen y tono

- **Moneda.** El código (`app/agent/money.py`) detecta la moneda que menciona el cliente (USD, MXN, COP, ARS; «pesos» sin
  país se interpreta en la moneda del cliente). Convierte con la tabla de tipos de cambio del dataset (última fecha
  disponible, triangulando por USD: **no es una cotización en vivo**) y evalúa la política siempre en la moneda del ingreso;
  el mensaje muestra ambos montos con la misma tasa. BRL y EUR se informan como no soportadas en vez de inventar una tasa.
- **Solicitud.** Tras una evaluación favorable el asistente pregunta si quiere avanzar. Si acepta, calcula los documentos
  que exige la política (`required_documents` en `credit_policy.yaml`), resta los que el banco ya tiene (`docs_on_file`,
  sintético) y pide uno por uno solo los que faltan. El chat **no recibe archivos**: el cliente confirma que los tiene y
  el asesor los verifica. Con todo en orden se deriva a un asesor con el resumen; si falta algo, se le dice qué.
- **Cierre.** Al despedirse o llamar a `POST /end`, el asistente resume la oferta y avisa que el detalle llegará por correo
  en PDF. **El envío es simulado:** el PDF y un JSON `simulated_not_sent` quedan en `CHAT_OUTBOX_DIR` y solo se muestra el
  correo enmascarado. El PDF se descarga con `GET /summary.pdf`. Un incidente (fraude, reclamo) nunca genera resumen comercial.
- **Tono e identidad.** Las respuestas usan un tono cercano y varían su formulación. El asistente se presenta una vez como
  «asistente virtual», nunca afirma ser una persona y, si el cliente pregunta si es un robot o una IA, responde con la
  verdad (intención `ask_identity`). Un texto del modelo que diga ser humano se descarta.

## Configuración (variables de entorno, ver `.env.example`)

| Variable | Defecto | Uso |
|---|---|---|
| `CHAT_ENV` | `dev` | Con `dev`, `GET /v1/handoffs` no exige clave; en otro valor se exige `CHAT_ADMIN_API_KEYS` |
| `CHAT_API_KEYS` | vacío | Claves de integración (lista por comas); vacío = sin clave |
| `CHAT_JWT_SECRET` | aleatorio | Secreto de tokens (≥ 32 caracteres); si falta, las sesiones no sobreviven al reinicio |
| `CHAT_CORS_ORIGINS` | vacío | Orígenes permitidos |
| `CHAT_LLM_PROVIDER` | `mock` | `mock` o `anthropic` |
| `CHAT_DATA_DIR` | `data/snapshot` si existe; si no, `data/fixture` | Carpeta con los parquet (montar como volumen en otros entornos) |
| `CHAT_OUTBOX_DIR` | carpeta temporal del sistema | Bandeja de correos **simulados** (PDF + JSON) |
| `CHAT_SESSION_TTL_MINUTES` · `CHAT_AUTH_MAX_ATTEMPTS` · `CHAT_AUTH_LOCKOUT_MINUTES` | 30 · 3 · 15 | Sesión y bloqueo |

## Datos

Hay dos orígenes, con la misma forma (clientes, productos, sucursales, movimientos recientes, perfil crediticio y `accepts_marketing`):

- `data/fixture/`: **conjunto de ejemplo inventado por el equipo** (21 clientes, semilla fija; `scripts/make_fixture.py`).
  Está en el repositorio y es lo que usan las pruebas, el CI y un clon limpio.
- `data/snapshot/`: muestra derivada del dataset del organizador (225 clientes). **No se versiona** (`.gitignore`);
  si existe, el backend lo prefiere. `GET /v1/meta` indica el origen en uso (`data_source`). Se regenera con:

```bash
python backend/scripts/build_snapshot.py --customers 400    # desde la raíz; requiere las tablas del organizador (ver docs/DATA.md)
```

## Pruebas

```bash
pip install -r requirements-dev.txt && pytest
```

155 pruebas: moneda y conversión, solicitud y documentos, resumen/PDF/correo simulado, tono e identidad, generación y verificación de preguntas, bloqueo, tokens, expiración, API key, formatos numéricos,
intenciones es/pt, política, derivación, inyección de instrucciones, consola de agentes y oferta proactiva
(consentimiento, preaprobación, momento adecuado, tema delicado, aceptación y rechazo) y salvaguardas contra un LLM
que se equivoca (derivación no pedida, reescritura de decisiones, números ajenos, caída del modelo).

## Límites conocidos

- **Correo simulado:** no hay envío real; el PDF se genera y se descarga, y el aviso lo dice con claridad.
- **Sin carga de archivos:** el cliente confirma que tiene los documentos; la verificación es del asesor. `docs_on_file` es sintético.
- **Tipos de cambio:** son los del dataset en su última fecha (no en vivo); solo USD, MXN, COP y ARS.
- **Tokens:** el historial crece con la conversación, así que el costo por turno aumenta en sesiones largas.

- **Seguridad de las preguntas:** con 3 preguntas de 4 opciones, adivinar acierta 1 de cada 64 veces por intento; la
  mitigación es el bloqueo, pero no sustituye un segundo factor real (OTP, biometría) en producción. Los datos de las
  preguntas salen del mismo dataset que el cliente declararía, así que es una simulación, no una prueba de identidad.
- **Estado en memoria:** sesiones, bloqueos y cola de derivaciones viven en un proceso. Una sola réplica; para más hay
  que externalizar `SessionStore`, `AuthLockout` y `HandoffQueue` (Redis o base de datos).
- **Un cliente sin datos suficientes para 3 preguntas** recibe `AUTH_UNAVAILABLE` (revela que el documento existe);
  en el snapshot derivado del dataset les pasa a 4 de 225 clientes (1,8%); en el conjunto de ejemplo, a 1 de 21 (a propósito).
- **Política sintética:** tope de 20% de endeudamiento, bandas de score y tasas son valores provisionales; no hay
  verdad de terreno externa. Las cuotas de deudas existentes se estiman con supuestos del YAML del baseline.
- **Claude probado solo con una muestra pequeña** (ver arriba). Falta medir clasificación de intención y detección de
  sentimiento y tema delicado con un conjunto etiquetado a mano, en es y pt.
- **Imagen Docker verificada** (652 MB): arranca como usuario no root (uid 10001), con sistema de archivos de solo
  lectura, pasa el `HEALTHCHECK` y completó el flujo es/pt desde `scripts/demo_client.py`. Un primer `docker build`
  falló por una descarga corrupta de un paquete (hash no coincidente) y funcionó al reintentar.
- No hay límite de peticiones por IP ni protección contra concurrencia sobre una misma sesión.
- Los logs no incluyen documentos, respuestas de seguridad ni cuerpos de petición; los mensajes del cliente sí se
  guardan en memoria durante la sesión y se incluyen (últimos 8, con números largos y correos omitidos) en el resumen de
  derivación.

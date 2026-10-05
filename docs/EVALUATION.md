# Evaluación: qué se midió, qué falló y qué falta

Todas las mediciones son **offline, sobre datos sintéticos y con una política inventada por el equipo**. No son mejoras
medidas en producción. Los tamaños de muestra son pequeños y se indican siempre.

## 1. Intención del NLU (reglas frente a Claude)

`backend/scripts/eval_nlu.py` sobre `backend/eval/nlu_cases.py`. Etiquetas de **un solo anotador**: el equipo debe
revisarlas antes de citar las cifras. Los ejemplos del prompt no aparecen en ninguna frase de prueba.

| Conjunto | Frases | Reglas | Claude Haiku 4.5 |
|---|---|---|---|
| Desarrollo, **antes** de afinar el prompt | 60 | 51/60 (85%) | 49/60 (82%) |
| Desarrollo, después de afinar (**optimista**: se afinó mirando estos fallos) | 60 | 57/60 (95%) | 60/60 (100%) |
| **Reservado** (escrito antes de afinar, medido una vez) | 29 | 23/29 (79%) | 28/29 y 27/29 (dos corridas: 93–97%) |

Errores del modelo antes de afinar: tasas y límites en portugués clasificados como "otro tema"; "no gracias" tomado como
despedida porque el modelo no sabía que había una pregunta pendiente; temas ajenos a la banca clasificados como "otro tema".
Correcciones: definiciones y ejemplos en el prompt, aviso de pregunta sí/no pendiente, y reglas más completas.

En el reservado, el único fallo constante fue "necesito que me atienda una persona", y no era del modelo: la guardia de
derivación explícita no reconocía esa frase. Se amplió su léxico mirando ese caso, **por lo que esa cifra ya no es limpia**.
Detección de tema sensible: 2/2 en el reservado y 5/5 en desarrollo, sin falsos positivos. Las dos corridas del modelo
difieren en una frase: no es determinista.

## 2. Conversaciones completas con el modelo real

`backend/scripts/e2e_llm.py`: 5 conversaciones (13 turnos) en español y portugués.

| | Antes de restringir la reescritura | Después |
|---|---|---|
| Llamadas al modelo por 13 turnos | 26 | 18 |
| Caídas a reglas | 0 | 0 |
| Latencia por llamada | p50 ≈ 1,2 s, p95 ≈ 1,6 s | p50 ≈ 1,1 s, p95 ≈ 1,7 s |
| Tokens por turno (entrada / salida) | ≈ 536 / 176 | ≈ 487 / 105 |

Fallos hallados en esa prueba y corregidos:

1. El modelo clasificó un incidente ("no reconozco un cargo… estoy furioso") como petición de humano y se creó la derivación
   sin confirmación. Ahora una derivación solo se acepta si el cliente la pidió de forma explícita en su texto.
2. La reescritura del modelo añadía frases no verificadas (el guardia solo revisa números) y trataba al cliente de "o senhor".
   Ahora el modelo solo reescribe mensajes de bajo riesgo; decisiones, ofertas, derivaciones y avisos salen de plantillas revisadas.
3. Tasas en portugués mal enrutadas (ver sección 1).

Segunda corrida en vivo tras los flujos de moneda, solicitud, resumen e identidad (`e2e_llm.py`, 6 conversaciones): ~1,0 s
mediana y ~1,4 s p95 por llamada, ≈ 979 tokens de entrada y ≈ 93 de salida por turno (más que antes: el historial y los
nuevos prompts). Se probaron frases de identidad; la reescritura del modelo se restringió porque en saludos y rechazos
empeoraba el texto de las plantillas. El conjunto de desarrollo del NLU creció 5 casos de `ask_identity` (65/65 con Claude,
~98% con reglas, optimista porque se desarrolló sobre esos casos); el conjunto reservado no se tocó.

## 3. Pruebas de fallos y seguridad (155 pruebas automáticas, sin red)

| Escenario del reto | Cobertura |
|---|---|
| Datos faltantes | Sin ingreso: pide el dato y queda provisional. Sin score: ofrece derivar |
| Sesión expirada | 401 `SESSION_EXPIRED`; token atado a su sesión |
| Acceso no autorizado | No se puede conversar sin verificar identidad; bloqueo tras 3 fallos, también para documentos inexistentes |
| Inyección de instrucciones | El texto del cliente es dato: intento de forzar una aprobación no la produce (con LLM falso y con reglas; una frase real se probó con el modelo en vivo) |
| Falla del LLM | Cae a reglas sin romper el turno; el LLM falso que se equivoca a propósito no logra derivar, ni reescribir decisiones, ni introducir cifras |
| Ambigüedad multilingüe | Español, portugués, formatos numéricos locales (1.500,00 y 1,500.00) |
| Moneda | Detección, conversión con tasa del dataset, equivalentes con la misma tasa, monedas no soportadas |
| Solicitud y documentos | Solo se piden los que faltan; derivación con todo en orden; aviso si falta algo; sin resumen en incidentes |
| Identidad | Responde con la verdad a «¿eres un robot?»; un texto del modelo que diga ser persona se descarta |
| Consentimiento y momento de la oferta proactiva | Sin consentimiento, con tema sensible, con sentimiento negativo, tras un rechazo, o ya ofrecida: no se ofrece |

**No cubierto:** fallos de herramientas distintos de la caída del LLM (no hay herramientas externas reales: los datos son
un snapshot local) y la inyección con muchas variantes contra el modelo real.

## 4. Baselines de datos

- **Política de crédito** sobre 150.000 clientes, solicitud tipo (préstamo personal, 36 meses, 3 veces el ingreso): 44,2%
  elegible, 27,2% datos faltantes, 18,5% revisión humana, 10,1% rechazado. Una preaprobación fija por segmento
  (Premium y Plus) aprobaría clientes que la política rechaza en 3,9% o manda a pedir datos en 27,4%, y dejaría fuera a un
  40,6% que sí es elegible. Es la política preliminar del backend: no hay verdad de terreno externa.
- **Credit policy 0.4 in gold** (Databricks, 150,000 customers, cutoff 2026-06-30): 50,707 eligible (33.8%), 24,953 with a
  proactive offer and 25,754 only if the customer asks. The Python reference implementation
  (`data/policy/credit_policy.py`) matches gold on all 1,800,000 options (`data/scripts/check_engine_parity.py`).
- **Data pipeline quality:** 90 metrics per run in `pipeline_quality_metrics`; 0 key duplicates and 0 content duplicates
  except 6 repeated `product_number` values; gold built on the typed silver is identical to the previous one, customer by
  customer. Update fixture (static data): 5 of 5 cases handled correctly, and the assertions fail without the delivery.
- **Triaje de fraude** (conjunto de prueba de 686.502 transacciones y 603 fraudes, partición temporal): el `fraud_score`
  del organizador da PR-AUC 0,577 y recall 58% revisando el 1% de mayor riesgo, con precisión de 5%. Un modelo sin
  `fraud_score` queda al nivel del azar (PR-AUC 0,0009).

## 5. Qué falta medir (frente a lo que pide el enunciado)

El enunciado pide evaluar con casos reservados y reportar, con tamaños de muestra y denominadores:

- resolución automática segura sobre todos los casos en alcance, y la proporción en que se intentó automatizar;
- contención (y por qué no basta);
- calidad del escalamiento: derivaciones perdidas e innecesarias, y utilidad del contexto entregado al agente;
- resultados inseguros (divulgación o acción no autorizada, resultado materialmente incorrecto) con conteos;
- latencia p50/p95 y costo por caso intentado y por resolución exitosa;
- comparación por idioma y por segmento, con las limitaciones de muestra.

**Nada de esto está medido todavía a nivel de conversación completa.** Lo anterior (secciones 1 a 3) son piezas parciales.
El plan: un conjunto reservado de guiones de conversación en español y portugués con resultado esperado (el motor de
política es determinista, así que el resultado correcto de cada caso se conoce), ejecutados contra el sistema y contra un
baseline (todo a humano), con estas métricas.

## 6. Reproducir

```bash
cd backend
pytest                                          # 96 pruebas, sin red
python scripts/eval_nlu.py --no-llm             # reglas; sin --no-llm usa Claude (necesita ANTHROPIC_API_KEY y consume saldo)
python scripts/eval_nlu.py --heldout --runs 2   # conjunto reservado (úselo con criterio: ya fue medido)
python scripts/e2e_llm.py                       # conversaciones completas con Claude
```

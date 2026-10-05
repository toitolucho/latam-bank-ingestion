# Datos de prueba del asistente

Todo es **sintético**; no hay personas reales. Se genera con `python scripts/gen_test_data.py` a partir de los datos que use el backend (`data/fixture/` por defecto).

## Cómo probar

1. Abra la interfaz (`http://localhost:8080`) y escriba el **documento** de un cliente de abajo.
2. Responda las **preguntas de seguridad** con la ficha del cliente. Las preguntas cambian en cada intento y salen de estos mismos datos: su ocupación registrada, la ciudad donde abrió un producto (solo si lo abrió en sucursal), el año de apertura de un producto y el año en que se hizo cliente. Un producto se nombra por su tipo (o «el más antiguo» si hay varios del mismo tipo). Las opciones incorrectas son inventadas y las ciudades son siempre del mismo país. Nunca se pregunta por montos ni fechas exactas.
3. Pruebe las frases sugeridas de cada escenario. Para portugués, cambie el selector de idioma antes de empezar.

**Flujos de crédito:** tras una evaluación favorable el asistente pregunta si quiere avanzar. Si dice que sí, pide solo los documentos que al cliente le **faltan** (los que el banco ya tiene figuran en cada ficha); el chat no recibe archivos: el cliente confirma que cuenta con ellos. Con todo en orden deriva a un asesor. Al terminar (despedida o botón «Terminar conversación») entrega el **resumen** de la propuesta y avisa que el detalle llegará por correo en un PDF: el correo es **simulado** (no se envía) y el PDF se descarga desde la interfaz. Si el cliente habla en otra moneda («dólares», «pesos colombianos»), el asistente la convierte a la de su ingreso con la tasa de referencia del conjunto de datos (fecha de corte, no cotización en vivo).

Tres intentos fallidos bloquean ese documento 15 minutos (también un documento inexistente, a propósito). Para desbloquear, reinicie el backend: `docker compose restart chat-backend`.

Los montos de los ejemplos están en la moneda del ingreso de cada cliente. Los resultados indicados (eligible, declined…) son los de la política provisional con los datos de hoy.

## Escenario A: Consiente marketing y está preaprobado: recibe la oferta proactiva al cerrar

**Bruno** · documento `53464097` · México · moneda MXN · ingreso 95.000 MXN · score 740 · mora máx. 0 días · marketing: sí

- Ocupación registrada: **Ingeniero/a**
- Año en que se hizo cliente: **2019**
- Productos activos (año de apertura y, si se abrieron en sucursal, la ciudad; si hay varios del mismo tipo, el reto pregunta por el más antiguo):
  - cuenta de ahorro: apertura en sucursal de **Tijuana**, año **2022**
  - tarjeta de crédito: apertura por Web (no se pregunta la ciudad), año **2024**
  - tarjeta de débito: apertura por Web (no se pregunta la ciudad), año **2019**
- Documentos que el banco ya tiene: comprobante de domicilio, copia del documento de identidad, comprobante de ingresos (al avanzar con una solicitud solo se piden los que faltan)

Frases para probar:

- «¿qué tasas tienen para mí?»
- «gracias, eso es todo» (debe llegar la oferta)
- «quiero un préstamo de 28500 a 24 meses» → eligible
- «necesito un préstamo de 570000» → declined
- «ahora gano 133000 al mes» (tras un rechazo por capacidad, recalcula como provisional)
- «necesito un préstamo de 1000 dólares a 24 meses» → convierte a MXN con la tasa de referencia y muestra los equivalentes
- «sí» (a «¿Le gustaría que avancemos?») → pide solo los documentos que falten; con todo en orden deriva a un asesor
- «gracias, eso es todo» → resumen de la propuesta y aviso del PDF por correo (simulado)
- «¿eres un robot?» → responde con la verdad: es el asistente virtual del banco, no una persona
- «no reconozco un cargo en mi cuenta» → pide confirmar la derivación; nunca ofrece crédito
- «quiero hablar con un asesor» → deriva y muestra el número de seguimiento

**Daniel** · documento `59689823` · Colombia · moneda COP · ingreso 10.500.000 COP · score 613 · mora máx. 0 días · marketing: sí

- Ocupación registrada: **Jubilado/a**
- Año en que se hizo cliente: **2019**
- Productos activos (año de apertura y, si se abrieron en sucursal, la ciudad; si hay varios del mismo tipo, el reto pregunta por el más antiguo):
  - cuenta de ahorro: apertura en sucursal de **Medellín**, año **2022**
  - tarjeta de débito: apertura en sucursal de **Medellín**, año **2022**
  - cuenta corriente: apertura por App (no se pregunta la ciudad), año **2025**
- Documentos que el banco ya tiene: copia del documento de identidad (al avanzar con una solicitud solo se piden los que faltan)

Frases para probar:

- «¿qué tasas tienen para mí?»
- «gracias, eso es todo» (debe llegar la oferta)
- «quiero un préstamo de 3150000 a 24 meses» → eligible
- «necesito un préstamo de 63000000» → declined
- «ahora gano 14699999 al mes» (tras un rechazo por capacidad, recalcula como provisional)
- «necesito un préstamo de 1000 dólares a 24 meses» → convierte a COP con la tasa de referencia y muestra los equivalentes
- «sí» (a «¿Le gustaría que avancemos?») → pide solo los documentos que falten; con todo en orden deriva a un asesor
- «gracias, eso es todo» → resumen de la propuesta y aviso del PDF por correo (simulado)
- «¿eres un robot?» → responde con la verdad: es el asistente virtual del banco, no una persona
- «no reconozco un cargo en mi cuenta» → pide confirmar la derivación; nunca ofrece crédito
- «quiero hablar con un asesor» → deriva y muestra el número de seguimiento

**Valentín** · documento `11542972` · Argentina · moneda ARS · ingreso 586.000 ARS · score 565 · mora máx. 0 días · marketing: sí

- Ocupación registrada: **Director/a**
- Año en que se hizo cliente: **2024**
- Productos activos (año de apertura y, si se abrieron en sucursal, la ciudad; si hay varios del mismo tipo, el reto pregunta por el más antiguo):
  - tarjeta de débito: apertura en sucursal de **Córdoba**, año **2021**
  - tarjeta de crédito: apertura en sucursal de **Mendoza**, año **2020**
  - cuenta corriente: apertura por Web (no se pregunta la ciudad), año **2018**
  - cuenta de ahorro: apertura por App (no se pregunta la ciudad), año **2018**
- Documentos que el banco ya tiene: copia del documento de identidad, comprobante de ingresos (al avanzar con una solicitud solo se piden los que faltan)

Frases para probar:

- «¿qué tasas tienen para mí?»
- «gracias, eso es todo» (debe llegar la oferta)
- «quiero un préstamo de 175800 a 24 meses» → eligible
- «necesito un préstamo de 3516000» → declined
- «ahora gano 820400 al mes» (tras un rechazo por capacidad, recalcula como provisional)
- «necesito un préstamo de 1000 dólares a 24 meses» → convierte a ARS con la tasa de referencia y muestra los equivalentes
- «sí» (a «¿Le gustaría que avancemos?») → pide solo los documentos que falten; con todo en orden deriva a un asesor
- «gracias, eso es todo» → resumen de la propuesta y aviso del PDF por correo (simulado)
- «¿eres un robot?» → responde con la verdad: es el asistente virtual del banco, no una persona
- «no reconozco un cargo en mi cuenta» → pide confirmar la derivación; nunca ofrece crédito
- «quiero hablar con un asesor» → deriva y muestra el número de seguimiento

## Escenario B: NO consiente marketing pero está preaprobado: puede pedir crédito, nunca recibe oferta proactiva

**Valentín** · documento `31667923` · México · moneda MXN · ingreso 80.000 MXN · score 756 · mora máx. 0 días · marketing: no

- Ocupación registrada: **Gerente**
- Año en que se hizo cliente: **2023**
- Productos activos (año de apertura y, si se abrieron en sucursal, la ciudad; si hay varios del mismo tipo, el reto pregunta por el más antiguo):
  - cuenta corriente: apertura en sucursal de **Ciudad de México**, año **2019**
  - tarjeta de débito: apertura por Web (no se pregunta la ciudad), año **2025**
  - tarjeta de crédito: apertura en sucursal de **Querétaro**, año **2024**
- Documentos que el banco ya tiene: comprobante de domicilio, copia del documento de identidad (al avanzar con una solicitud solo se piden los que faltan)

Frases para probar:

- «¿qué tasas tienen para mí?»
- «gracias, eso es todo» (NO debe llegar oferta)
- «quiero un préstamo de 24000 a 24 meses» → eligible
- «necesito un préstamo de 480000» → declined
- «ahora gano 112000 al mes» (tras un rechazo por capacidad, recalcula como provisional)
- «necesito un préstamo de 1000 dólares a 24 meses» → convierte a MXN con la tasa de referencia y muestra los equivalentes
- «sí» (a «¿Le gustaría que avancemos?») → pide solo los documentos que falten; con todo en orden deriva a un asesor
- «gracias, eso es todo» → resumen de la propuesta y aviso del PDF por correo (simulado)
- «¿eres un robot?» → responde con la verdad: es el asistente virtual del banco, no una persona
- «no reconozco un cargo en mi cuenta» → pide confirmar la derivación; nunca ofrece crédito
- «quiero hablar con un asesor» → deriva y muestra el número de seguimiento

**Bruno** · documento `41532215` · Colombia · moneda COP · ingreso 5.800.000 COP · score 640 · mora máx. 0 días · marketing: no

- Ocupación registrada: **Gerente**
- Año en que se hizo cliente: **2024**
- Productos activos (año de apertura y, si se abrieron en sucursal, la ciudad; si hay varios del mismo tipo, el reto pregunta por el más antiguo):
  - cuenta de ahorro: apertura en sucursal de **Medellín**, año **2024**
  - cuenta corriente: apertura por App (no se pregunta la ciudad), año **2021**
  - tarjeta de débito: apertura en sucursal de **Medellín**, año **2022**
  - tarjeta de crédito: apertura por App (no se pregunta la ciudad), año **2021**
- Documentos que el banco ya tiene: copia del documento de identidad, comprobante de ingresos (al avanzar con una solicitud solo se piden los que faltan)

Frases para probar:

- «¿qué tasas tienen para mí?»
- «gracias, eso es todo» (NO debe llegar oferta)
- «quiero un préstamo de 1740000 a 24 meses» → eligible
- «necesito un préstamo de 34800000» → declined
- «ahora gano 8119999 al mes» (tras un rechazo por capacidad, recalcula como provisional)
- «necesito un préstamo de 1000 dólares a 24 meses» → convierte a COP con la tasa de referencia y muestra los equivalentes
- «sí» (a «¿Le gustaría que avancemos?») → pide solo los documentos que falten; con todo en orden deriva a un asesor
- «gracias, eso es todo» → resumen de la propuesta y aviso del PDF por correo (simulado)
- «¿eres un robot?» → responde con la verdad: es el asistente virtual del banco, no una persona
- «no reconozco un cargo en mi cuenta» → pide confirmar la derivación; nunca ofrece crédito
- «quiero hablar con un asesor» → deriva y muestra el número de seguimiento

## Escenario C: Sin ingreso registrado: el asistente pide que lo declare (queda provisional)

**Alicia** · documento `52410090` · México · moneda MXN · ingreso sin ingreso registrado · score 790 · mora máx. 0 días · marketing: no

- Ocupación registrada: **Médico/a**
- Año en que se hizo cliente: **2020**
- Productos activos (año de apertura y, si se abrieron en sucursal, la ciudad; si hay varios del mismo tipo, el reto pregunta por el más antiguo):
  - cuenta corriente: apertura en sucursal de **Monterrey**, año **2025**
  - tarjeta de crédito: apertura por App (no se pregunta la ciudad), año **2021**
  - cuenta de ahorro: apertura en sucursal de **Tijuana**, año **2019**
  - tarjeta de débito: apertura por App (no se pregunta la ciudad), año **2020**
- Documentos que el banco ya tiene: comprobante de domicilio, copia del documento de identidad, comprobante de ingresos (al avanzar con una solicitud solo se piden los que faltan)

Frases para probar:

- «quiero un préstamo de 3000» → pide el ingreso; luego «gano 5000»
- «¿eres un robot?» → responde con la verdad: es el asistente virtual del banco, no una persona
- «no reconozco un cargo en mi cuenta» → pide confirmar la derivación; nunca ofrece crédito
- «quiero hablar con un asesor» → deriva y muestra el número de seguimiento

## Escenario D: Sin score registrado: no se puede evaluar solo, ofrece derivar

**Carla** · documento `46395401` · Colombia · moneda COP · ingreso 9.000.000 COP · score sin score · mora máx. 0 días · marketing: sí

- Ocupación registrada: **Jubilado/a**
- Año en que se hizo cliente: **2022**
- Productos activos (año de apertura y, si se abrieron en sucursal, la ciudad; si hay varios del mismo tipo, el reto pregunta por el más antiguo):
  - tarjeta de débito: apertura en sucursal de **Cartagena**, año **2021**
  - cuenta corriente: apertura en sucursal de **Barranquilla**, año **2024**
  - cuenta de ahorro: apertura en sucursal de **Cartagena**, año **2022**
- Documentos que el banco ya tiene: copia del documento de identidad (al avanzar con una solicitud solo se piden los que faltan)

Frases para probar:

- «quiero un préstamo de 2700000 a 24 meses» → needs_data
- «necesito un préstamo de 54000000» → needs_data
- «ahora gano 12600000 al mes» (tras un rechazo por capacidad, recalcula como provisional)
- «necesito un préstamo de 1000 dólares a 24 meses» → convierte a COP con la tasa de referencia y muestra los equivalentes
- «sí» (a «¿Le gustaría que avancemos?») → pide solo los documentos que falten; con todo en orden deriva a un asesor
- «gracias, eso es todo» → resumen de la propuesta y aviso del PDF por correo (simulado)
- «¿eres un robot?» → responde con la verdad: es el asistente virtual del banco, no una persona
- «no reconozco un cargo en mi cuenta» → pide confirmar la derivación; nunca ofrece crédito
- «quiero hablar con un asesor» → deriva y muestra el número de seguimiento

## Escenario E: Mora de 31 a 90 días: va a revisión de un asesor

**Héctor** · documento `44325214` · México · moneda MXN · ingreso 70.000 MXN · score 658 · mora máx. 45 días · marketing: no

- Ocupación registrada: **Artista**
- Año en que se hizo cliente: **2022**
- Productos activos (año de apertura y, si se abrieron en sucursal, la ciudad; si hay varios del mismo tipo, el reto pregunta por el más antiguo):
  - tarjeta de débito: apertura en sucursal de **Querétaro**, año **2023**
  - cuenta corriente: apertura por App (no se pregunta la ciudad), año **2024**
  - cuenta de ahorro: apertura en sucursal de **Querétaro**, año **2025**
  - tarjeta de crédito: apertura por App (no se pregunta la ciudad), año **2022**
- Documentos que el banco ya tiene: copia del documento de identidad (al avanzar con una solicitud solo se piden los que faltan)

Frases para probar:

- «quiero un préstamo de 21000 a 24 meses» → needs_review
- «necesito un préstamo de 420000» → needs_review
- «ahora gano 98000 al mes» (tras un rechazo por capacidad, recalcula como provisional)
- «necesito un préstamo de 1000 dólares a 24 meses» → convierte a MXN con la tasa de referencia y muestra los equivalentes
- «sí» (a «¿Le gustaría que avancemos?») → pide solo los documentos que falten; con todo en orden deriva a un asesor
- «gracias, eso es todo» → resumen de la propuesta y aviso del PDF por correo (simulado)
- «¿eres un robot?» → responde con la verdad: es el asistente virtual del banco, no una persona
- «no reconozco un cargo en mi cuenta» → pide confirmar la derivación; nunca ofrece crédito
- «quiero hablar con un asesor» → deriva y muestra el número de seguimiento

## Escenario F: Mora de más de 90 días: crédito rechazado

**Joaquín** · documento `70002780` · México · moneda MXN · ingreso 103.000 MXN · score 675 · mora máx. 120 días · marketing: sí

- Ocupación registrada: **Docente**
- Año en que se hizo cliente: **2020**
- Productos activos (año de apertura y, si se abrieron en sucursal, la ciudad; si hay varios del mismo tipo, el reto pregunta por el más antiguo):
  - tarjeta de crédito: apertura en sucursal de **Puebla**, año **2023**
  - tarjeta de débito: apertura por App (no se pregunta la ciudad), año **2021**
  - cuenta corriente: apertura por Web (no se pregunta la ciudad), año **2025**
  - cuenta de ahorro: apertura por Web (no se pregunta la ciudad), año **2020**
- Documentos que el banco ya tiene: comprobante de domicilio, copia del documento de identidad, comprobante de ingresos (al avanzar con una solicitud solo se piden los que faltan)

Frases para probar:

- «quiero un préstamo de 30900 a 24 meses» → declined
- «necesito un préstamo de 618000» → declined
- «ahora gano 144200 al mes» (tras un rechazo por capacidad, recalcula como provisional)
- «necesito un préstamo de 1000 dólares a 24 meses» → convierte a MXN con la tasa de referencia y muestra los equivalentes
- «sí» (a «¿Le gustaría que avancemos?») → pide solo los documentos que falten; con todo en orden deriva a un asesor
- «gracias, eso es todo» → resumen de la propuesta y aviso del PDF por correo (simulado)
- «¿eres un robot?» → responde con la verdad: es el asistente virtual del banco, no una persona
- «no reconozco un cargo en mi cuenta» → pide confirmar la derivación; nunca ofrece crédito
- «quiero hablar con un asesor» → deriva y muestra el número de seguimiento

## Escenario G: Sin capacidad de endeudamiento (su deuda actual ya supera el 20% del ingreso)

**Lucas** · documento `21523163` · México · moneda MXN · ingreso 25.000 MXN · score 619 · mora máx. 0 días · marketing: no

- Ocupación registrada: **Profesional independiente**
- Año en que se hizo cliente: **2022**
- Productos activos (año de apertura y, si se abrieron en sucursal, la ciudad; si hay varios del mismo tipo, el reto pregunta por el más antiguo):
  - tarjeta de débito: apertura en sucursal de **Ciudad de México**, año **2023**
  - cuenta corriente: apertura por Web (no se pregunta la ciudad), año **2023**
  - cuenta de ahorro: apertura por Web (no se pregunta la ciudad), año **2021**
- Documentos que el banco ya tiene: comprobante de domicilio, copia del documento de identidad, comprobante de ingresos (al avanzar con una solicitud solo se piden los que faltan)

Frases para probar:

- «quiero un préstamo de 7500 a 24 meses» → declined
- «necesito un préstamo de 150000» → declined
- «ahora gano 35000 al mes» (tras un rechazo por capacidad, recalcula como provisional)
- «necesito un préstamo de 1000 dólares a 24 meses» → convierte a MXN con la tasa de referencia y muestra los equivalentes
- «sí» (a «¿Le gustaría que avancemos?») → pide solo los documentos que falten; con todo en orden deriva a un asesor
- «gracias, eso es todo» → resumen de la propuesta y aviso del PDF por correo (simulado)
- «¿eres un robot?» → responde con la verdad: es el asistente virtual del banco, no una persona
- «no reconozco un cargo en mi cuenta» → pide confirmar la derivación; nunca ofrece crédito
- «quiero hablar con un asesor» → deriva y muestra el número de seguimiento

## Escenario H: Score muy bajo (banda 1): crédito rechazado

**Renata** · documento `77695536` · México · moneda MXN · ingreso 44.000 MXN · score 502 · mora máx. 0 días · marketing: sí

- Ocupación registrada: **Docente**
- Año en que se hizo cliente: **2024**
- Productos activos (año de apertura y, si se abrieron en sucursal, la ciudad; si hay varios del mismo tipo, el reto pregunta por el más antiguo):
  - cuenta corriente: apertura en sucursal de **Tijuana**, año **2018**
  - cuenta de ahorro: apertura por App (no se pregunta la ciudad), año **2019**
  - tarjeta de débito: apertura en sucursal de **Ciudad de México**, año **2025**
- Documentos que el banco ya tiene: comprobante de domicilio, copia del documento de identidad (al avanzar con una solicitud solo se piden los que faltan)

Frases para probar:

- «quiero un préstamo de 13200 a 24 meses» → declined
- «necesito un préstamo de 264000» → declined
- «ahora gano 61599 al mes» (tras un rechazo por capacidad, recalcula como provisional)
- «necesito un préstamo de 1000 dólares a 24 meses» → convierte a MXN con la tasa de referencia y muestra los equivalentes
- «sí» (a «¿Le gustaría que avancemos?») → pide solo los documentos que falten; con todo en orden deriva a un asesor
- «gracias, eso es todo» → resumen de la propuesta y aviso del PDF por correo (simulado)
- «¿eres un robot?» → responde con la verdad: es el asistente virtual del banco, no una persona
- «no reconozco un cargo en mi cuenta» → pide confirmar la derivación; nunca ofrece crédito
- «quiero hablar con un asesor» → deriva y muestra el número de seguimiento

## Escenario I: sin datos suficientes para 3 preguntas (no se puede verificar por este canal)

Estos documentos reciben el aviso «No es posible verificar su identidad por este canal»: `50312198`

## Escenario J: documento inexistente

Cualquier número que no esté arriba (por ejemplo `99999999`) recibe preguntas igual que un cliente real, pero nunca se aprueban: así no se revela qué documentos existen.

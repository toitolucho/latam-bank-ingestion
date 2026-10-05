# frontend (UNICORN)

Interfaz de chat para el `backend`: documento, preguntas de seguridad, conversación en español y portugués, oferta indicativa
y derivación a un asesor. Se presenta como una plataforma de **inteligencia de clientes con IA**: el cliente ve la respuesta,
y junto a ella **qué hizo realmente el agente** para darla (datos consultados, validaciones, sellos de verificación).

HTML, CSS y JavaScript puros: **sin dependencias ni paso de compilación**, así que se puede servir con nginx, subir a
Cloudflare Pages o copiar junto a otra aplicación.

> Prototipo con datos sintéticos. La interfaz lo indica en la barra lateral y en el pie.

## Arranque

Desde la raíz del repositorio (levanta backend e interfaz; el backend lee `backend/.env`):

```bash
docker compose up --build
```

Abra `http://localhost:8080`. El puerto del backend no se publica: el navegador solo habla con el nginx de la
interfaz, que reenvía `/v1` al backend y agrega ahí la clave de integración (`CHAT_API_KEY`), de modo que **la clave
nunca llega al navegador** y no hace falta CORS.

Sin Docker, para desarrollo: sirva esta carpeta con cualquier servidor estático y ponga en `config.js`
`apiBase: "http://127.0.0.1:8000"`; el backend debe permitir ese origen con `CHAT_CORS_ORIGINS`.

## Estructura

| Archivo | Contenido |
|---|---|
| `index.html` | Esqueleto: barra lateral, encabezado, vistas (documento, preguntas, chat, fin) y panel de datos. Sprite de iconos. |
| `styles.css` | Tokens de diseño (`:root`), layout, componentes, panel y responsive. Tema oscuro único. |
| `components.js` | Componentes como funciones que construyen DOM (`window.UNI`): `agentMessage`, `investigationDetails`, `toolActivity`, `verificationBadge`, `agentPipeline`, `dataSources`, `relevantData`, `customerProfile`, `escalationCard`, `errorState`, `loadingState`, `emptyState`… |
| `app.js` | Estado, cliente de la API, flujo de pantallas, menús y cajones. |
| `i18n.js` | Todos los textos en `es` y `pt`. Ningún componente lleva texto propio. |
| `assets/unicorn.svg` | Mascota en pixel art (sprite 16×16, un `<rect>` por píxel). Sirve de logo, avatar, favicon y estado de carga. |

## Diseño

Oscuro y sobrio (azul noche, morado eléctrico, cian, menta para lo verificado). El pixel art identifica la marca
(logo, avatar del agente, estados vacíos y de carga); el resto es UI de producto, no de videojuego.

- **Tres zonas**: barra lateral (marca, estado, navegación), conversación y panel «Datos y herramientas».
  Por debajo de 1180 px el panel pasa a **cajón** (botón «Investigación» en el encabezado); por debajo de 700 px es una
  **hoja inferior**; por debajo de 860 px la barra lateral también es un cajón.
- **Flujo visible**: Pregunta → Agente IA → Datos → Validación → Respuesta, sobre el chat. Se ilumina según lo que ocurrió
  en el último turno; las etapas que no hizo falta recorrer salen atenuadas («No necesario»).
- **Respuesta del agente**: tarjeta con la respuesta, sellos de verificación y un acordeón «Detalles de la investigación»
  (cerrado por defecto) con cada paso y sus datos.
- **Panel**: fuentes de datos (marca las que se usaron en la respuesta), datos relevantes (la evaluación de crédito,
  las tasas o el caso de soporte, con «Ver detalles») y perfil del cliente.
- Estados: investigando, error (con «Reintentar»), verificación parcial, atención humana sugerida y derivación con número de caso.
- Idioma: se toma del navegador (es o pt) y se cambia con ES | PT sin recargar; los componentes se vuelven a pintar
  (el texto del agente conserva el idioma en que respondió). Atajos: `Enter` envía, `/` enfoca el cuadro de mensaje, `Esc` cierra menús.

## Qué se muestra y de dónde sale (sin inventar)

La interfaz **no genera** verificaciones, pasos ni registros: los pinta a partir de la respuesta del backend.

- `POST /v1/sessions/{id}/verify` devuelve `customer` (id, nombre, país, segmento, estado) → «Perfil del cliente».
- `POST /v1/sessions/{id}/messages` devuelve `evidence` **solo si el agente usó herramientas** en ese turno
  (`backend/app/agent/evidence.py`). Sin `evidence` (saludo, agradecimiento…) la respuesta se muestra simple, sin sellos.
  - `steps[]`: `customer_profile`, `fx_rates`, `credit_policy`, `offer_rates`, `handoff`, `summary_email`, con su estado `success | failed`.
  - `verification[]`: `verified` (comprobación concluyente), `inconclusive` (requiere revisión), `unverified` (dato declarado por el
    cliente, p. ej. el ingreso) y `reference` (dato de referencia, no en vivo). El flujo solo termina en «Respuesta verificada» si
    **todas** son concluyentes; si no, queda en «Verificación parcial».
  - Si una herramienta falló (`failed`), el backend no envía sellos y la interfaz marca la respuesta como **sin verificar**.
  - `evaluation` y `customer` alimentan «Datos relevantes» y el perfil.
- «Conectado / En línea» sale de `GET /health` (cada 30 s y tras cada llamada); es el mismo estado para todas las fuentes,
  no una comprobación individual.
- Mientras el agente trabaja solo se sabe que está en curso: se muestra «Unicorn está investigando…» con una barra
  indeterminada, **sin pasos inventados**.

Lo que **no** existe en el backend y por eso no se muestra: puntaje de confianza, base de conocimiento, transacciones,
analítica. Las entradas de menú Clientes, Transacciones, Base de conocimiento, Analítica y Configuración aparecen
deshabilitadas con la etiqueta «Pronto».

## Pantallas

1. **Documento**: valida el formato antes de llamar a la API (4 a 32 letras, números, puntos o guiones).
2. **Preguntas de seguridad**: tres preguntas de opción única; «Verificar» se activa al responder todas. Si fallan,
   muestra los intentos restantes y las preguntas nuevas; al bloquearse vuelve al inicio con el aviso.
3. **Chat**: ver «Diseño». Oferta indicativa cuando la API marca `proactive_offer`; tarjeta de **soporte humano solicitado**
   con el número de caso cuando hay derivación; tarjeta de **resumen listo** con el PDF cuando `summary_ready`.
4. **Fin**: «Terminar conversación» (menú del usuario) pide el cierre al servidor (`POST /v1/sessions/{id}/end`): si hay una
   propuesta evaluada, muestra su resumen y el aviso de que el detalle se enviaría por correo en un PDF (simulado), y deja
   descargarlo. «Nueva conversación» cierra la sesión en el servidor.

## Seguridad

- Todo texto que llega de la API se inserta con `textContent`, nunca como HTML. El PDF se descarga con `fetch` y el token de sesión
  (no hay un enlace público al archivo).
- El token de sesión vive solo en memoria de la página (no en `localStorage`): recargar la página cierra la sesión.
- nginx añade `Content-Security-Policy` estricta (sin scripts ni estilos en línea; solo mismo origen),
  `X-Content-Type-Options` y `Referrer-Policy: no-referrer`. Por eso los iconos son un sprite SVG en el HTML, no hay fuentes
  externas (se usa la pila de fuentes del sistema) y el estilo vive solo en `styles.css`.
  El contenedor corre sin privilegios y con el sistema de archivos en solo lectura.
- No se muestran los códigos internos de error al cliente, salvo el `trace_id` en errores inesperados (para soporte).

## Despliegue en un hosting estático (p. ej. Cloudflare Pages)

Suba el contenido de esta carpeta (menos `nginx/`, `Dockerfile` y este README), ponga en `config.js` la URL pública
del backend en `apiBase` y configure `CHAT_CORS_ORIGINS` en el backend con el origen de la página. **Una `apiKey` en
`config.js` sería visible para cualquiera**: si el backend exige clave de integración, use un proxy que la agregue en
el servidor (como hace el nginx de este contenedor) en vez de ponerla en el navegador.

## Qué se probó y qué no

Probado en Chrome (headless, manejado por CDP) contra el backend real con el LLM simulado y la CSP de producción
(sin errores de consola ni violaciones de la CSP): acceso y preguntas de seguridad, consulta de elegibilidad con
sellos y detalles, conversión de moneda, derivación con tarjeta de caso, caso incierto (mora → revisión), ingreso declarado
(verificación parcial), cambio de idioma en plena conversación, error de red con «Reintentar» y la vista de escritorio, tablet y teléfono
(cajones). El backend tiene pruebas de la evidencia (`backend/tests/test_evidence.py`).

No hay pruebas automáticas de la interfaz, ni auditoría de accesibilidad con lector de pantalla (hay etiquetas, `role="log"`,
foco gestionado, `aria-expanded` en cajones y menús, y se respeta `prefers-reduced-motion`, pero no se verificó con herramientas
asistivas), ni pruebas en Safari o Firefox. No se probó con el LLM real ni con el contenedor nginx de producción
(sí con un servidor que imita sus cabeceras). La interfaz no incluye la consola del agente humano
(`GET /v1/handoffs` del backend queda sin pantalla).

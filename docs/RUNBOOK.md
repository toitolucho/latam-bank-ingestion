# Runbook: levantar el servicio para la evaluación

Los organizadores avisarán cuándo empieza la evaluación; el servicio se levanta entonces y se apaga al terminar, para no
incurrir en costos. Este documento es para que **cualquiera del equipo** pueda hacerlo en pocos minutos.

## Antes (con anticipación, una sola vez)

1. Clonar el repositorio y comprobar que arranca desde cero: `docker compose up --build` y abrir `http://localhost:8080`.
2. Para usar Claude, crear `backend/.env` desde `backend/.env.example` con `CHAT_LLM_PROVIDER=anthropic` y
   `ANTHROPIC_API_KEY` (clave creada en la Console de Anthropic; **nunca** se sube al repositorio ni se pega en un chat).
3. **Fijar un tope de gasto mensual** en la Console de Anthropic. Anotar aquí la cifra: ____
4. Definir el origen de los datos: sin `backend/data/snapshot/` se usa el conjunto de ejemplo del equipo; con él, el
   snapshot derivado del dataset (se reconstruye según `docs/DATA.md`). Los documentos de prueba están en
   `backend/DATOS_DE_PRUEBA.md` (conjunto de ejemplo).
5. Instalar `cloudflared` si se va a exponer desde un equipo local: `winget install Cloudflare.cloudflared`.
6. Ensayar todo este runbook al menos una vez.

## Levantar

```bash
docker compose up -d --build
docker compose ps          # esperar a que ambos servicios estén "healthy"
```

## Exponer un enlace público

```bash
cloudflared tunnel --no-autoupdate --url http://localhost:8080
```

Imprime un enlace `https://….trycloudflare.com`. Cambia cada vez que se reinicia el túnel: enviar el enlace a los
organizadores **después** de levantarlo. Expone solo el puerto de la interfaz (8080); el backend no se publica.

## Verificar antes de enviar el enlace

```bash
python backend/scripts/smoke_remote.py --base https://XXXX.trycloudflare.com --doc <documento-de-prueba>
```

Debe terminar con todas las comprobaciones correctas: la interfaz carga y envía su política de seguridad, el backend
responde, `/v1/handoffs` devuelve 404, un documento inexistente recibe 3 preguntas, no se conversa sin verificar, y con un
documento de prueba se autentica y se recibe una respuesta. `--doc` necesita que los datos de ese cliente estén en la
máquina donde se ejecuta el script.

## Bandeja de correos simulados

Los resúmenes quedan en `CHAT_OUTBOX_DIR` (PDF + JSON `simulated_not_sent`) dentro del contenedor, que es efímero. No se envía
ningún correo real.

## Durante la evaluación

| Qué | Cómo |
|---|---|
| Ver actividad y errores | `docker compose logs -f chat-backend` (JSON; no incluye documentos ni respuestas de seguridad) |
| Un documento quedó bloqueado (3 fallos) | `docker compose restart chat-backend` (también cierra todas las sesiones) |
| Consumo del modelo | Console de Anthropic; se esperan unos 490 tokens de entrada y 105 de salida por turno |
| Sesiones | Expiran a los 30 minutos de inactividad y se pierden si el backend se reinicia |

## Si algo falla

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| El script marca falla en `/health` | El backend no arrancó | `docker compose logs chat-backend`; revisar `backend/.env` y reiniciar |
| Respuestas con tono muy básico | El modelo no está disponible y el turno cayó al extractor por reglas | Revisar la clave y el saldo en la Console; el servicio sigue funcionando con reglas |
| `INVALID_TOKEN` en mitad de una conversación | Se reinició el backend (el secreto de tokens es temporal si no se fijó `CHAT_JWT_SECRET`) | Es esperado: iniciar una conversación nueva |
| El enlace dejó de abrir | El túnel se cerró o cambió de dirección | Volver a ejecutar `cloudflared`, verificar y enviar el enlace nuevo |
| `AUTH_UNAVAILABLE` para un documento | El cliente no tiene datos para 3 preguntas | Es esperado en algunos clientes; usar otro documento de prueba |

## Apagar

```powershell
Stop-Process -Name cloudflared
```

```bash
docker compose down
```

Revisar el gasto en la Console. Si la clave llegó a quedar expuesta, revocarla y crear otra.

## Respaldo si el enlace no está disponible

El video de 3 minutos muestra el flujo completo. Añadir capturas o un GIF de la conversación al README antes de la entrega.

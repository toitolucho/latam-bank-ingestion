// Configuración de despliegue (sin secretos).
//   apiBase: URL base de la API. Vacío = mismo origen (el nginx del contenedor reenvía /v1 al backend).
//            Para un hosting estático separado (p. ej. Cloudflare Pages): "https://api.midominio.com"
//            y configure CHAT_CORS_ORIGINS en el backend con el origen de esta página.
//   apiKey:  NO la ponga aquí en producción: una clave en el navegador no es secreta. El proxy la agrega en el servidor.
window.CHAT_CONFIG = {
  apiBase: "",
  apiKey: "",
};

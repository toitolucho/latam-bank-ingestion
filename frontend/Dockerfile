FROM nginxinc/nginx-unprivileged:1.27-alpine

# Variables que sustituye la plantilla de nginx al arrancar
ENV BACKEND_URL=http://chat-backend:8000 \
    CHAT_API_KEY=""

COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY index.html styles.css app.js components.js i18n.js config.js /usr/share/nginx/html/
COPY assets/ /usr/share/nginx/html/assets/

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1

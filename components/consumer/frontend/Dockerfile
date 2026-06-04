# =============================================================================
# HAMq Consumer UI — standalone nginx image (build context: components/consumer/frontend/)
# Exposed port: 80
# =============================================================================

FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci --prefer-offline
COPY . .
ARG VITE_API_URL="http://localhost:8001"
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM nginx:1.25-alpine AS runtime
LABEL org.opencontainers.image.title="HAMq Consumer UI" \
      org.opencontainers.image.description="React SPA for the HAMq Consumer" \
      org.opencontainers.image.version="1.0.0"

RUN printf 'server {\n\
    listen 80;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    gzip on;\n\
    gzip_types text/plain text/css application/javascript application/json image/svg+xml;\n\
    location / { try_files $uri $uri/ /index.html; }\n\
    location /healthz { access_log off; return 200 "ok"; add_header Content-Type text/plain; }\n\
}\n' > /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]

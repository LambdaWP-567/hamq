# =============================================================================
# HAMq Producer UI — standalone nginx image (build context: components/producer/frontend/)
#
# Used when deploying the frontend as a SEPARATE container (sidecar pattern).
# The backend API URL is injected at build time via VITE_API_URL.
#
# Exposed port: 80
# =============================================================================

# ─── Stage 1: Build ──────────────────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci --prefer-offline

COPY . .

# VITE_API_URL must point to the backend service in the same cluster, e.g.
# http://hamq-producer-backend:8000
ARG VITE_API_URL="http://localhost:8000"
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build

# ─── Stage 2: nginx ───────────────────────────────────────────────────────────
FROM nginx:1.25-alpine AS runtime

LABEL org.opencontainers.image.title="HAMq Producer UI" \
      org.opencontainers.image.description="React SPA for the HAMq Producer" \
      org.opencontainers.image.version="1.0.0"

# nginx config that handles SPA routing (all 404s → index.html)
RUN printf 'server {\n\
    listen 80;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    # Enable gzip for static assets\n\
    gzip on;\n\
    gzip_types text/plain text/css application/javascript application/json image/svg+xml;\n\
    location / {\n\
        # Try exact file, then directory, then fall back to index.html for SPA\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
    location /api {\n\
        # API calls are proxied to the backend service by the Ingress / K8s service\n\
        return 404;\n\
    }\n\
    # Health check endpoint consumed by Kubernetes liveness probe\n\
    location /healthz {\n\
        access_log off;\n\
        return 200 "ok";\n\
        add_header Content-Type text/plain;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]

# =============================================================================
# HAMq Arbiter UI — Multi-stage Dockerfile
# Stage 1: Build the React/Vite app
# Stage 2: Serve the static bundle with Nginx
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: Builder
# -----------------------------------------------------------------------------
FROM node:20-alpine AS builder

WORKDIR /app

# Copy dependency manifests first for better layer caching
COPY package.json package-lock.json* ./

# Install all dependencies (including devDependencies needed for build)
RUN npm ci --ignore-scripts

# Copy the full source tree
COPY . .

# Build the production bundle
RUN npm run build

# -----------------------------------------------------------------------------
# Stage 2: Runtime (Nginx)
# -----------------------------------------------------------------------------
FROM nginx:1.25-alpine AS runtime

# Remove the default Nginx configuration
RUN rm /etc/nginx/conf.d/default.conf

# Custom Nginx config for SPA routing (all unknown paths → index.html)
COPY --chown=nginx:nginx <<'EOF' /etc/nginx/conf.d/default.conf
server {
    listen       3002;
    server_name  _;
    root         /usr/share/nginx/html;
    index        index.html;

    # Gzip compression for text assets
    gzip on;
    gzip_types text/plain text/css application/javascript application/json image/svg+xml;
    gzip_min_length 1024;

    # Cache static assets aggressively (Vite appends content hashes)
    location ~* \.(js|css|woff2?|ttf|eot|svg|png|jpg|jpeg|gif|ico|webp)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
        try_files $uri =404;
    }

    # Health check endpoint (used by Kubernetes liveness probe)
    location /healthz {
        access_log off;
        return 200 "ok\n";
        add_header Content-Type text/plain;
    }

    # SPA fallback — all other routes serve index.html so React Router handles them
    location / {
        try_files $uri $uri/ /index.html;
    }
}
EOF

# Copy built assets from the builder stage
COPY --from=builder --chown=nginx:nginx /app/dist /usr/share/nginx/html

# Nginx listens on port 3002 (unprivileged — matches service.frontend.port)
EXPOSE 3002

CMD ["nginx", "-g", "daemon off;"]

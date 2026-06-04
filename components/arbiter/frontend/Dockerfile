# =============================================================================
# HAMq Arbiter UI — Multi-stage Dockerfile
# Stage 1: Build the React/Vite app with Node 20
# Stage 2: Serve the static bundle with Nginx on port 3002
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

# Write custom Nginx config for SPA routing
RUN printf 'server {\n\
    listen       3002;\n\
    server_name  _;\n\
    root         /usr/share/nginx/html;\n\
    index        index.html;\n\
\n\
    gzip on;\n\
    gzip_types text/plain text/css application/javascript application/json image/svg+xml;\n\
    gzip_min_length 1024;\n\
\n\
    location ~* \\.(js|css|woff2?|ttf|eot|svg|png|jpg|jpeg|gif|ico|webp)$ {\n\
        expires 1y;\n\
        add_header Cache-Control "public, immutable";\n\
        try_files $uri =404;\n\
    }\n\
\n\
    location /healthz {\n\
        access_log off;\n\
        return 200 "ok\\n";\n\
        add_header Content-Type text/plain;\n\
    }\n\
\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

# Copy built assets from the builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Nginx listens on port 3002 (matches service.frontend.port in values.yaml)
EXPOSE 3002

CMD ["nginx", "-g", "daemon off;"]

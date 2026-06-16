# Build context is the PROJECT ROOT (set in docker-compose.yml as context: .)
# This lets a single Dockerfile reach both frontend/ and nginx/ directories.

# ── Stage 1: build the React app ──────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Copy only the package files first so npm install is cached as its own layer.
# Rebuilds skip this layer unless package.json / package-lock.json changed.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Copy the rest of the frontend source
COPY frontend/ ./

# CLOUD ENGINEERING NOTE:
# VITE_APP_ENV is baked into the JS bundle at build time (not a runtime env var).
# In CI/CD, pass --build-arg APP_ENV=production to stamp the build.
# The value appears in the UI header so you can tell which environment you're on.
ARG APP_ENV=production
ENV VITE_APP_ENV=$APP_ENV

# VITE_API_URL is empty in local/docker-compose (Nginx proxy handles /api/).
# Set it to the backend's public URL when building for cloud deployments so the
# React bundle calls the backend directly without an Nginx proxy in the middle.
ARG VITE_API_URL=""
ENV VITE_API_URL=$VITE_API_URL

RUN npm run build
# React build output lands in /app/dist


# ── Stage 2: serve with Nginx ─────────────────────────────────────────────────
FROM nginx:1.27-alpine

# NGINX_ENV selects the nginx config:
#   local (default) — includes /api/ proxy to backend container (docker-compose)
#   prod            — static files only; React calls the backend URL directly
ARG NGINX_ENV=local

# Remove the default placeholder config
RUN rm /etc/nginx/conf.d/default.conf

# Copy both configs then pick the right one
COPY nginx/nginx.conf nginx/nginx.prod.conf /tmp/nginx/
RUN if [ "$NGINX_ENV" = "prod" ]; then \
      mv /tmp/nginx/nginx.prod.conf /etc/nginx/conf.d/app.conf; \
    else \
      mv /tmp/nginx/nginx.conf /etc/nginx/conf.d/app.conf; \
    fi && \
    rm -rf /tmp/nginx

# Copy the compiled React app
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

# Check that nginx is up and serving the React app
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ > /dev/null || exit 1

# Build context is the PROJECT ROOT (set in docker-compose.yml as context: .)
# This lets a single Dockerfile reach both frontend/ and nginx/ directories.

# ── Stage 1: build the React app ──────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Copy only the package files first so npm install is cached as its own layer.
# Rebuilds skip this layer unless package.json / package-lock.json changed.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --silent

# Copy the rest of the frontend source
COPY frontend/ ./

# CLOUD ENGINEERING NOTE:
# VITE_APP_ENV is baked into the JS bundle at build time (not a runtime env var).
# In CI/CD, pass --build-arg APP_ENV=production to stamp the build.
# The value appears in the UI header so you can tell which environment you're on.
ARG APP_ENV=production
ENV VITE_APP_ENV=$APP_ENV

RUN npm run build
# React build output lands in /app/dist


# ── Stage 2: serve with Nginx ─────────────────────────────────────────────────
FROM nginx:1.27-alpine

# Remove the default placeholder config
RUN rm /etc/nginx/conf.d/default.conf

# nginx.conf lives in nginx/ at the project root — reachable because context is .
COPY nginx/nginx.conf /etc/nginx/conf.d/app.conf

# Copy the compiled React app
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

# Check that nginx is up and serving the React app
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO- http://127.0.0.1/ > /dev/null || exit 1

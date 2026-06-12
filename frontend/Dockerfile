# ── Stage 1: build the React app ──────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json ./
RUN npm install

COPY . .

# CLOUD ENGINEERING NOTE:
# VITE_APP_ENV is baked into the JS bundle at build time.
# In CI/CD, pass --build-arg APP_ENV=production here.
# The value appears in the UI header so you can see which environment you're on.
ARG APP_ENV=production
ENV VITE_APP_ENV=$APP_ENV

RUN npm run build
# Output is in /app/dist


# ── Stage 2: serve with Nginx ──────────────────────────────────────────────────
FROM nginx:1.27-alpine

# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Copy our custom config
COPY ../nginx/nginx.conf /etc/nginx/conf.d/app.conf

# Copy the React build output
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s \
  CMD wget -qO- http://localhost/health || exit 1

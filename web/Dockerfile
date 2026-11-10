# Build context: repository root -> docker build -f web/Dockerfile .

# 1) Build the static files
FROM node:22-alpine AS build
WORKDIR /app
# Dependencies first: this layer stays cached when only the code changes
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ .
RUN npm run build

# 2) Serve them with nginx; it also proxies /api and /agent to the services
# The unprivileged image runs as a non-root user and listens on 8080
FROM nginxinc/nginx-unprivileged:1.31-alpine
COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

# 127.0.0.1, not localhost: in Alpine localhost resolves to ::1 first, and nginx
# listens on IPv4 only
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://127.0.0.1:8080/ || exit 1

FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# Override .env.production for custom builds (e.g. selfhost)
ARG VITE_ENV_FILE
RUN if [ -n "$VITE_ENV_FILE" ]; then cp "$VITE_ENV_FILE" .env.production; fi

RUN npm run build

FROM nginxinc/nginx-unprivileged:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]

FROM node:22-slim

WORKDIR /app

COPY docker/defuddle/package.json docker/defuddle/package-lock.json ./
RUN npm ci --omit=dev

ENV PLAYWRIGHT_BROWSERS_PATH=/opt/ms-playwright
RUN npx playwright install --with-deps chromium

# Browser bundle for Playwright init script injection
RUN cp node_modules/defuddle/dist/index.full.js defuddle_bundle.js

COPY docker/defuddle/app.js ./

RUN chown -R node:node /opt/ms-playwright /app

USER node
ENV NODE_ENV=production
EXPOSE 8001
CMD ["node", "app.js"]

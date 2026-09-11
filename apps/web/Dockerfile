# ---- deps ----
FROM node:20-alpine AS deps
WORKDIR /srv/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci

# ---- dev (used by docker-compose.dev.yml) ----
FROM deps AS dev
COPY apps/web .
CMD ["npm", "run", "dev"]

# ---- build ----
FROM deps AS build
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
COPY apps/web .
RUN npm run build

# ---- runtime ----
FROM node:20-alpine AS runtime
WORKDIR /srv/web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /srv/web/.next/standalone ./
COPY --from=build /srv/web/.next/static ./.next/static
COPY --from=build /srv/web/public ./public
EXPOSE 3000
CMD ["node", "server.js"]

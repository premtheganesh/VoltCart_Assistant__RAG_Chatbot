# VoltCart web (chat page, widget, admin). Build from frontend/:
#   docker build -t voltcart-web --build-arg NEXT_PUBLIC_API_URL=https://api.example.com frontend
# NEXT_PUBLIC_* values are baked into the browser code at build time, so they are build args.

FROM node:22.20.0-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22.20.0-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG WIDGET_ALLOWED_PARENTS=*
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    WIDGET_ALLOWED_PARENTS=$WIDGET_ALLOWED_PARENTS \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build

# Runtime: only the standalone server Next.js produced (no dev dependencies, no source)
FROM node:22.20.0-alpine
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build --chown=node /app/.next/standalone ./
COPY --from=build --chown=node /app/.next/static ./.next/static
COPY --from=build --chown=node /app/public ./public
USER node
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1
CMD ["node", "server.js"]

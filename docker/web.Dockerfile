# syntax=docker/dockerfile:1
# Next.js dashboard — standalone output. Installs deps in web/ directly
# (bypassing the pnpm workspace to keep the build simple).

FROM node:22-alpine AS builder
WORKDIR /app/web
RUN corepack enable && corepack prepare pnpm@10.33.0 --activate
COPY web/package.json web/pnpm-lock.yaml* ./
RUN pnpm install --no-frozen-lockfile
COPY web/ .
ARG NEXT_PUBLIC_API_BASE_URL=https://tracker.example.com
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3001
ENV HOSTNAME=0.0.0.0
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /app/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/web/.next/static ./web/.next/static
COPY --from=builder --chown=nextjs:nodejs /app/web/public ./public
USER nextjs
EXPOSE 3001
CMD ["node", "web/server.js"]

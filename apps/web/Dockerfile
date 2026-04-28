FROM node:20-alpine AS base
RUN apk add --no-cache libc6-compat
RUN npm install -g pnpm@9
WORKDIR /repo

FROM base AS builder
# Single stage: copy workspace + sources, then install ALL deps (including
# devDependencies — postcss/tailwindcss/autoprefixer are needed for next build
# to compile CSS). Splitting into deps/builder lost the per-package symlinks.
ENV NODE_ENV=development
# NEXT_PUBLIC_* variables are baked into the client bundle at build time.
# Pass them via --build-arg from CI; defaults are dev-friendly.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY apps/web ./apps/web
RUN pnpm install --frozen-lockfile --prod=false --filter web...
WORKDIR /repo/apps/web
RUN pnpm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 nextjs
# In a pnpm workspace + Next.js standalone build, server.js lives at
# /app/apps/web/server.js and serves /_next/static from apps/web/.next/static
# (relative to its own location). Copy public + static into that subdir.
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/public ./apps/web/public
COPY --from=builder --chown=nextjs:nodejs /repo/apps/web/.next/static ./apps/web/.next/static
USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"
CMD ["node", "apps/web/server.js"]

# WA-AKG (gateway WhatsApp) na tag fixada, com o Prisma trocado de MySQL para PostgreSQL
# (o schema so usa Text/Json; o projeto documenta as duas opcoes). Reaplicar este patch a cada atualizacao.
ARG WA_AKG_TAG=v1.6.3

FROM alpine:3.20 AS src
ARG WA_AKG_TAG
RUN apk add --no-cache git
RUN git clone --depth 1 --branch ${WA_AKG_TAG} https://github.com/mrifqidaffaaditya/WA-AKG.git /src \
 && sed -i 's/provider = "mysql"/provider = "postgresql"/' /src/prisma/schema.prisma \
 && grep -q 'provider = "postgresql"' /src/prisma/schema.prisma

FROM node:26-alpine AS builder
RUN apk add --no-cache openssl ca-certificates
WORKDIR /app
COPY --from=src /src/package*.json ./
COPY --from=src /src/patches ./patches/
COPY --from=src /src/prisma ./prisma/
RUN npm ci --legacy-peer-deps && npm cache clean --force
COPY --from=src /src/ .
RUN npx prisma generate && NODE_OPTIONS=--max-old-space-size=1536 npm run build
RUN npm prune --omit=dev && npm install --no-save tsx typescript

FROM node:26-alpine AS runner
RUN apk add --no-cache openssl ca-certificates
WORKDIR /app
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/src ./src
COPY --from=builder /app/prisma ./prisma
COPY --from=builder /app/public ./public
COPY --from=builder /app/tsconfig.json ./
COPY --from=builder /app/scripts ./scripts
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
EXPOSE 3000
CMD ["sh", "-c", "npx prisma db push && (if [ -n \"$ADMIN_EMAIL\" ] && [ -n \"$ADMIN_PASSWORD\" ]; then node scripts/setup-admin.js \"$ADMIN_EMAIL\" \"$ADMIN_PASSWORD\"; fi) && node node_modules/tsx/dist/cli.mjs src/server/index.ts"]

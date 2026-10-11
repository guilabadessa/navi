#!/bin/bash
# Compila e assina o APK da NAVI. Uso (no servidor): mobile/build.sh
# Segredos ficam em /opt/noc/secrets (google-services.json, navi-release.jks, ks.pass) e nunca vao para o git.
set -euo pipefail
cd "$(dirname "$0")"
ROOT=$(cd .. && pwd)
IMG=navi-android-builder
docker image inspect $IMG >/dev/null 2>&1 || docker build -f Dockerfile.builder -t $IMG .
mkdir -p "$ROOT/storage/app"
# --memory: se faltar RAM, morre so o build (nao o Zabbix/NAVI)
docker run --rm --memory=1800m --memory-swap=1800m --cpus=1.5 \
  -v "$PWD":/work -v "$ROOT/secrets":/secrets -v "$ROOT/storage/app":/out -v "$ROOT/frontend/public/brand":/brand:ro \
  -v navi-gradle:/root/.gradle -v navi-npm:/root/.npm \
  $IMG bash /work/inner-build.sh
echo "APK: $ROOT/storage/app/navi.apk"

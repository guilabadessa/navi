#!/bin/bash
set -euo pipefail
cd /work
[ -f /secrets/google-services.json ] || { echo "falta /opt/noc/secrets/google-services.json"; exit 1; }
if [ ! -f /secrets/navi-release.jks ]; then
  head -c 24 /dev/urandom | base64 | tr -d '/+=' > /secrets/ks.pass; chmod 600 /secrets/ks.pass
  keytool -genkeypair -keystore /secrets/navi-release.jks -alias navi -keyalg RSA -keysize 2048 -validity 10000 \
    -storepass "$(cat /secrets/ks.pass)" -keypass "$(cat /secrets/ks.pass)" -dname "CN=NAVI, O=Orca TI, C=BR"
  chmod 600 /secrets/navi-release.jks
fi
npm install --no-audit --no-fund
rm -rf android && npx cap add android
cp /secrets/google-services.json android/app/google-services.json
# icone do app a partir da marca
R=android/app/src/main/res
rm -rf $R/mipmap-anydpi-v26
for d in mdpi:48 hdpi:72 xhdpi:96 xxhdpi:144 xxxhdpi:192; do
  convert /brand/pwa-512.png -resize ${d#*:}x${d#*:} $R/mipmap-${d%%:*}/ic_launcher.png
  cp $R/mipmap-${d%%:*}/ic_launcher.png $R/mipmap-${d%%:*}/ic_launcher_round.png
  cp $R/mipmap-${d%%:*}/ic_launcher.png $R/mipmap-${d%%:*}/ic_launcher_foreground.png
done
npx cap sync android
cd android
echo "org.gradle.jvmargs=-Xmx1g -XX:MaxMetaspaceSize=384m" >> gradle.properties
./gradlew assembleRelease --no-daemon --console=plain
APK=$(ls app/build/outputs/apk/release/*.apk | head -1)
export KSP=$(cat /secrets/ks.pass)
apksigner sign --ks /secrets/navi-release.jks --ks-pass env:KSP --key-pass env:KSP --out /out/navi.apk "$APK"
apksigner verify /out/navi.apk && echo "assinado ok"

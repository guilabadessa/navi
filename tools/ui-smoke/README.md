# Teste de fumaça da interface (dados reais)

Renderiza todas as telas da NAVI (inclusive o portal do cliente) em jsdom, abre as abas e os formulários e falha se algo
quebrar. Usa o **backend em execução** (127.0.0.1:8100) com uma sessão forjada, por isso é uso **local**, não de CI.

```bash
# 1) sessões (admin e cliente) em sess.txt / sess_cli.txt (token e csrf, uma por linha) — veja o histórico do projeto
# 2) copie frontend/src, package.json, vite.config.js e index.html para uma pasta de trabalho junto com estes arquivos e rode:
docker run --rm --network host -v "$PWD":/work -w /work node:20-slim sh -c \
  "npm i --save-dev vitest@2.1.8 jsdom@25 @testing-library/react@16 @testing-library/dom@10 && npx vitest run"
```

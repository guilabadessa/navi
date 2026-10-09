"""Variaveis minimas para importar a aplicacao nos testes (nenhuma conexao real e aberta)."""
import os

for k, v in {"NAVI_DB_HOST": "localhost", "NAVI_DB_PASSWORD": "x", "NAVI_SECRET_KEY": "ci-secret-key-ci-secret-key-ci-secret"}.items():
    os.environ.setdefault(k, v)

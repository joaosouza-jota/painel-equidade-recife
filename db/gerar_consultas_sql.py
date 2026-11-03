"""
Gera db/consultas.sql (entregável "SQL das consultas") a partir de db/consultas.py.

Cada consulta sai com os valores de exemplo no lugar dos parâmetros, pronta para rodar no psql
ou em qualquer cliente PostgreSQL. A interface executa exatamente o mesmo SQL, com os valores
escolhidos na tela.

Uso:  python db/gerar_consultas_sql.py   (precisa de DATABASE_URL, para formatar os valores como o banco)
"""

import os
from pathlib import Path

import psycopg

from consultas import CONSULTAS, EXEMPLO

SAIDA = Path(__file__).resolve().parent / "consultas.sql"

partes = ["""-- =====================================================================
-- Painel de Equidade em Saúde do Recife
-- Banco de Dados · Etapa 03 · Entregável 2 · SQL das consultas
-- SGBD: PostgreSQL · rodar depois de schema.sql + carregar_banco.py
--
-- Os valores de exemplo (quadrimestre 2026.2, Distrito Sanitário 8...)
-- estão no lugar dos parâmetros. Na interface (página Banco de Dados do
-- app), o usuário escolhe esses valores e o mesmo SQL é executado.
-- Gerado por db/gerar_consultas_sql.py a partir de db/consultas.py.
-- ====================================================================="""]

with psycopg.connect(os.environ["DATABASE_URL"]) as con:
    cur = psycopg.ClientCursor(con)
    for c in CONSULTAS.values():
        params = {p: EXEMPLO[p] for p in c["params"]}
        partes.append(
            f"\n-- ---------------------------------------------------------------------\n"
            f"-- {c['titulo']}\n"
            f"-- {c['pergunta']}\n"
            f"-- Técnicas: {c['tecnicas']}\n"
            f"-- Parâmetros: {', '.join(f'{k} = {v}' for k, v in params.items()) or 'nenhum'}\n"
            f"-- ---------------------------------------------------------------------\n"
            + cur.mogrify(c["sql"], params).strip() + ";\n")

SAIDA.write_text("\n".join(partes), encoding="utf-8")
print(f"ok: {SAIDA} ({len(CONSULTAS)} consultas)")

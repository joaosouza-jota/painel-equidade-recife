#!/usr/bin/env bash
# =====================================================================
# Copia o banco local (painel_equidade) inteiro para o Neon, na nuvem.
#
# Leva tudo: tabelas, dados (inclusive respostas_sinteticas do notebook
# e as datas de entrada), sequências, índices e visões. Usa pg_dump +
# pg_restore, as ferramentas oficiais do PostgreSQL.
#
# A string do Neon vem de .streamlit/secrets.toml (DATABASE_URL), que
# não vai para o GitHub. Ela nunca é impressa na tela.
#
# Uso (na raiz do projeto):  bash db/migrar_para_neon.sh
# ATENÇÃO: apaga o que já existir no banco do Neon antes de copiar.
# =====================================================================
set -euo pipefail
cd "$(dirname "$0")/.."

LOCAL="${LOCAL_URL:-postgresql:///painel_equidade}"
NEON=$(sed -n 's/^DATABASE_URL *= *"\(.*\)"$/\1/p' .streamlit/secrets.toml)
# keepalive: detecta conexão caída em vez de ficar esperando para sempre
NEON="${NEON}&keepalives=1&keepalives_idle=30&keepalives_interval=10&keepalives_count=3"
case "$NEON" in *neon.tech*) ;; *) echo "DATABASE_URL do secrets.toml não parece ser do Neon"; exit 1;; esac

DUMP=$(mktemp -t painel_equidade).dump
echo "1/3 Exportando o banco local..."
pg_dump --format=custom --no-owner --no-acl --file="$DUMP" "$LOCAL"

echo "2/3 Restaurando no Neon (alguns minutos)..."
pg_restore --clean --if-exists --no-owner --no-acl --verbose --dbname="$NEON" "$DUMP" 2>&1 | grep -E "processando dados|processing data|criando INDEX|creating INDEX|erro|error" || true
psql "$NEON" -X -q -c "ANALYZE"
rm -f "$DUMP"

echo "3/3 Conferindo: linhas por tabela (local x Neon)"
SQL="SELECT relname || '=' || n FROM (
  SELECT 'bairro' relname, COUNT(*) n FROM bairro UNION ALL SELECT 'unidade_saude', COUNT(*) FROM unidade_saude
  UNION ALL SELECT 'equipe', COUNT(*) FROM equipe UNION ALL SELECT 'cidadao', COUNT(*) FROM cidadao
  UNION ALL SELECT 'ficha_cadastro', COUNT(*) FROM ficha_cadastro UNION ALL SELECT 'ficha_deficiencia', COUNT(*) FROM ficha_deficiencia
  UNION ALL SELECT 'tipo_deficiencia', COUNT(*) FROM tipo_deficiencia UNION ALL SELECT 'quadrimestre', COUNT(*) FROM quadrimestre
  UNION ALL SELECT 'indicador_equipe', COUNT(*) FROM indicador_equipe UNION ALL SELECT 'respostas_sinteticas', COUNT(*) FROM respostas_sinteticas
  UNION ALL SELECT 'visoes', COUNT(*) FROM pg_views WHERE schemaname = 'public'
  UNION ALL SELECT 'indices_ix', COUNT(*) FROM pg_indexes WHERE indexname LIKE 'ix_%') x ORDER BY 1"
diff <(psql "$LOCAL" -X -At -c "$SQL") <(psql "$NEON" -X -At -c "$SQL") && echo "OK: Neon idêntico ao local" \
  && psql "$NEON" -X -At -c "$SQL" | column -t -s=

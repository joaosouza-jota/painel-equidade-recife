"""
Dados do Painel e da página Estatísticas: um lugar só para carregar.

- Com banco (DATABASE_URL na variável de ambiente ou nos segredos do Streamlit, ex.: Neon):
  lê as visões materializadas que a pipeline atualiza (db/painel.sql, src/pipeline.py),
  com o risco do modelo de ML (indicador_equipe.risco_previsto). Uma importação de fichas
  aparece no painel assim que a pipeline termina.
- Sem banco: lê os agregados versionados em app/dados/*.parquet (cópia estática, sem modelo).

Nos dois casos o painel só recebe AGREGADOS por equipe, USF e distrito, nunca ficha de pessoa.
"""

import os
from pathlib import Path

import pandas as pd
import streamlit as st

DADOS = Path(__file__).resolve().parent / "dados"
TABELAS = ["resumo_equipes", "estados_distrito", "populacao_usf", "territorio_usf"]

SQL = {
    "resumo_equipes": """
        SELECT m.*, i.risco_previsto::float8 AS risco_previsto
        FROM mv_resumo_equipe m
        JOIN quadrimestre q ON q.ano || '.' || q.numero = m.quadrimestre
        LEFT JOIN indicador_equipe i ON i.ine = m.ine AND i.id_quadrimestre = q.id_quadrimestre
        ORDER BY m.ine, m.quadrimestre""",
    "estados_distrito": "SELECT * FROM mv_estados_distrito",
    "populacao_usf": "SELECT * FROM mv_populacao_usf",
    "territorio_usf": """
        SELECT u.cnes, u.nome AS nome_unidade, b.nome AS bairro, b.nr_distrito AS distrito_sanitario,
               u.latitude::float8 AS latitude, u.longitude::float8 AS longitude
        FROM unidade_saude u JOIN bairro b ON b.id_bairro = u.id_bairro""",
}


def url_banco():
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    try:
        return st.secrets.get("DATABASE_URL")
    except Exception:  # sem secrets.toml
        return None


@st.cache_data(show_spinner="Carregando dados...", ttl=600)
def carregar():
    """Devolve (tabelas, origem). origem = 'banco' ou 'arquivos'."""
    url = url_banco()
    if url:
        try:
            import psycopg

            with psycopg.connect(url) as con:
                tabelas = {}
                for nome in TABELAS:
                    cur = con.execute(SQL[nome])
                    tabelas[nome] = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
            for col in ["distrito_sanitario", "n_fichas", "n_elegiveis", "critica", "pessoas", "elegiveis", "sem_pergunta"]:
                for t in tabelas.values():
                    if col in t.columns:
                        t[col] = t[col].astype(int)
            return tabelas, "banco"
        except Exception as e:  # banco fora do ar: o painel continua com a cópia estática
            st.warning(f"Banco indisponível ({type(e).__name__}); mostrando a cópia estática dos dados.")
    return {nome: pd.read_parquet(DADOS / f"{nome}.parquet") for nome in TABELAS}, "arquivos"


def risco(resumo):
    """Risco de cada equipe estar crítica no quadrimestre seguinte: o do modelo, se houver;
    sem modelo (cópia estática), a baseline de persistência (crítica agora = 1)."""
    if "risco_previsto" in resumo.columns and resumo["risco_previsto"].notna().any():
        return resumo["risco_previsto"]
    return resumo["critica"].astype(float)

"""
Painel de Equidade em Saúde do Recife (Estação 5): ponto de entrada do app.

Duas páginas:
  - Painel          (paginas/painel.py): visão da gestão, lê só dados agregados (app/dados)
  - Banco de Dados  (paginas/banco_de_dados.py): consultas, gráficos e cadastro direto no PostgreSQL.
                    Só funciona com a variável DATABASE_URL definida (versão local)

Uso (na raiz do projeto):  streamlit run app/app.py
"""

import streamlit as st

st.set_page_config(page_title="Painel de Equidade em Saúde", page_icon="📊", layout="wide")

st.navigation([
    st.Page("paginas/painel.py", title="Painel", icon="📊", default=True),
    st.Page("paginas/banco_de_dados.py", title="Banco de Dados", icon="🗄️"),
]).run()

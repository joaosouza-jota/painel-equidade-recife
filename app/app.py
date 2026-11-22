"""
Painel de Equidade em Saúde do Recife (Estação 5): ponto de entrada do app.

Cinco páginas:
  - Painel          (paginas/painel.py): visão da gestão, lê só dados agregados (app/dados)
  - Dashboard       (paginas/dashboard.py): indicadores e 8 gráficos estatísticos calculados no PostgreSQL (BD Etapa 06)
  - Estatísticas    (paginas/estatisticas.py): detalhamento das estatísticas de resumo por equipe (app/dados)
  - Banco de Dados  (paginas/banco_de_dados.py): consultas, gráficos e cadastro direto no PostgreSQL.
                    Só funciona com a variável DATABASE_URL definida (versão local)
  - Formulário da equipe (paginas/formulario.py): ficha de cadastro preenchida pela equipe, gravada no banco

Uso (na raiz do projeto):  streamlit run app/app.py
"""

import streamlit as st

st.set_page_config(page_title="Painel de Equidade em Saúde", page_icon="📊", layout="wide")

st.navigation([
    st.Page("paginas/painel.py", title="Painel", icon="📊", default=True),
    st.Page("paginas/dashboard.py", title="Dashboard", icon="📉"),
    st.Page("paginas/estatisticas.py", title="Estatísticas", icon="📈"),
    st.Page("paginas/banco_de_dados.py", title="Banco de Dados", icon="🗄️"),
    st.Page("paginas/formulario.py", title="Formulário da equipe", icon="📝"),
]).run()

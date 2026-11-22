"""
Formulário da equipe: Ficha de Cadastro Individual (e-SUS APS v5.3) preenchida pela equipe e gravada no PostgreSQL.

Diferente da aba "Fichas de cadastro" da página Banco de Dados (CRUD para quem administra o banco), esta página é
para a equipe de saúde no dia a dia:
- escolhe distrito -> unidade -> equipe;
- os campos aparecem conforme as respostas (criança não vê orientação/identidade; tipos de deficiência só com "sim");
- raça/cor, deficiência e "deseja informar?" são obrigatórios: o formulário não deixa a equipe gerar N/I,
  que é exatamente a falha que o painel mede. A recusa da pessoa ("não deseja informar") continua possível;
- confere tudo antes de enviar, com mensagens em português (as restrições CHECK do banco continuam valendo);
- grava cidadão, ficha e tipos de deficiência numa transação só e devolve o número da ficha (protocolo);
- mostra na hora o índice de completude da equipe no quadrimestre atual, calculado pela função
  fn_indice_completude (Etapa 05) direto das fichas.

Página do roteador app/app.py.
"""

import sys
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dados_painel import url_banco  # noqa: E402

URL = url_banco()

st.title("Formulário da equipe")
st.caption("Ficha de Cadastro Individual · e-SUS APS v5.3 · bloco de identificação e marcadores de equidade. "
           "Cada envio grava direto no banco do projeto.")

if not URL:
    st.info("Este formulário grava direto no PostgreSQL e precisa da conexão `DATABASE_URL` "
            "(variável de ambiente ou segredo do Streamlit). Veja o README.")
    st.stop()

import psycopg  # noqa: E402

RECIFE = ZoneInfo("America/Recife")

RACAS = {"branca": "Branca", "preta": "Preta", "parda": "Parda", "amarela": "Amarela", "indigena": "Indígena"}
ORIENTACOES = {"heterossexual": "Heterossexual", "gay": "Gay", "lesbica": "Lésbica", "bissexual": "Bissexual",
               "assexual": "Assexual", "pansexual": "Pansexual", "outra": "Outra"}
IDENTIDADES = {"mulher_cis": "Mulher cisgênero", "homem_cis": "Homem cisgênero", "mulher_trans": "Mulher transgênero",
               "homem_trans": "Homem transgênero", "travesti": "Travesti", "nao_binario": "Não binário",
               "outra": "Outra"}
SEXOS = {"F": "Feminino", "M": "Masculino", "I": "Indeterminado"}
SIM_NAO = {"sim": "Sim", "nao": "Não"}
CATEGORIAS = {"auditiva": "Auditiva", "visual": "Visual", "intelectual": "Intelectual/cognitiva",
              "fisica": "Física", "tea": "Transtorno do espectro autista", "outra": "Outra"}

# Campos do formulário (chaves do session_state): limpos depois de cada envio
CAMPOS = ["f_tipo", "f_cidadao", "f_situacao", "f_data", "f_idade", "f_sexo", "f_nome_social", "f_raca", "f_def",
          "f_tipos_def", "f_des_os", "f_os", "f_des_ig", "f_ig"]


def consultar(comando, params=None):
    with psycopg.connect(URL) as con, con.cursor() as cur:
        cur.execute(comando, params)
        return pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])


@st.cache_data(ttl=3600, show_spinner=False)
def territorio():
    return consultar("""
        SELECT b.nr_distrito, u.cnes, u.nome AS unidade, e.ine, e.nome AS equipe
        FROM equipe e
        JOIN unidade_saude u ON u.cnes = e.cnes
        JOIN bairro b ON b.id_bairro = u.id_bairro
        ORDER BY b.nr_distrito, u.nome, e.nome""")


@st.cache_data(ttl=3600, show_spinner=False)
def tipos_deficiencia():
    return consultar("SELECT id_tipo_deficiencia, descricao, categoria FROM tipo_deficiencia ORDER BY categoria, descricao")


# Limpa o formulário depois de um envio (precisa ser antes de os campos serem desenhados)
if st.session_state.pop("limpar_formulario", False):
    for k in CAMPOS:
        st.session_state.pop(k, None)

# ---------------------------------------------------------------------------
# 1 · Quem está preenchendo
# ---------------------------------------------------------------------------

terr = territorio()
with st.container(border=True):
    st.markdown("##### 1 · Equipe responsável")
    c1, c2, c3 = st.columns([1, 2, 2])
    distrito = c1.selectbox("Distrito Sanitário", sorted(terr["nr_distrito"].unique()), format_func=lambda d: f"DS {d}",
                            key="f_distrito")
    t_ds = terr[terr["nr_distrito"] == distrito]
    unidades = dict(zip(t_ds["cnes"], t_ds["unidade"]))
    cnes = c2.selectbox("Unidade de saúde", list(unidades), format_func=unidades.get, key="f_unidade")
    t_us = t_ds[t_ds["cnes"] == cnes]
    equipes = dict(zip(t_us["ine"], t_us["equipe"]))
    ine = c3.selectbox("Equipe", list(equipes), format_func=lambda i: f"{equipes[i]} · INE {i}", key="f_equipe")

# Quadrimestre de hoje e índice da equipe nele, calculado pela função da Etapa 05
hoje = date.today()
quad_atual = consultar("""
    SELECT id_quadrimestre, ano || '.' || numero AS rotulo FROM quadrimestre
    WHERE %(d)s BETWEEN data_inicio AND data_fim""", {"d": hoje})
if len(quad_atual):
    q = quad_atual.iloc[0]
    situacao_eq = consultar("""
        SELECT COUNT(*)                                                   AS fichas,
               COUNT(*) FILTER (WHERE f.data_entrada::date = CURRENT_DATE) AS fichas_hoje,
               fn_indice_completude(%(ine)s, %(q)s)                       AS indice
        FROM ficha_cadastro f
        JOIN quadrimestre q ON f.data_envio BETWEEN q.data_inicio AND q.data_fim
        WHERE f.ine = %(ine)s AND q.id_quadrimestre = %(q)s""", {"ine": ine, "q": int(q["id_quadrimestre"])}).iloc[0]
    m = st.columns(3)
    m[0].metric(f"Fichas da equipe em {q['rotulo']}", f"{int(situacao_eq['fichas']):,}".replace(",", "."))
    m[1].metric("Enviadas hoje", int(situacao_eq["fichas_hoje"]))
    m[2].metric(f"Índice de completude em {q['rotulo']}",
                "–" if situacao_eq["indice"] is None else f"{float(situacao_eq['indice']):.1f}".replace(".", ","),
                help="Calculado agora pela função fn_indice_completude, direto das fichas da equipe no quadrimestre. "
                     "Fichas com todos os marcadores preenchidos fazem o índice subir.")

# ---------------------------------------------------------------------------
# 2 · Identificação da pessoa
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.markdown("##### 2 · Identificação")
    c1, c2, c3 = st.columns(3)
    tipo = c1.radio("Tipo de ficha", ["novo", "atualizacao"], horizontal=True, key="f_tipo",
                    format_func={"novo": "Cadastro novo", "atualizacao": "Atualização"}.get)
    if tipo == "atualizacao":
        cod_cidadao = c2.text_input("Código do cidadão", max_chars=8, key="f_cidadao", placeholder="c0001234",
                                    help="Código da pessoa já cadastrada (o banco não guarda nome, CPF nem CNS).")
        situacao = c3.selectbox("Situação", ["ativo", "mudou_se", "obito"], key="f_situacao",
                                format_func={"ativo": "Ativo", "mudou_se": "Mudou-se", "obito": "Óbito"}.get)
    else:
        cod_cidadao, situacao = None, "ativo"
        c2.caption("Cidadão novo: o código é gerado pelo banco no envio.")
    c4, c5, c6, c7 = st.columns(4)
    data_envio = c4.date_input("Data do atendimento", hoje, max_value=hoje, format="DD/MM/YYYY", key="f_data")
    idade = c5.number_input("Idade (anos)", 0, 110, None, key="f_idade", placeholder="obrigatório")
    sexo = c6.selectbox("Sexo", list(SEXOS), None, format_func=SEXOS.get, key="f_sexo", placeholder="Escolha")
    c7.write("")
    nome_social = c7.checkbox("Usa nome social", key="f_nome_social")

# ---------------------------------------------------------------------------
# 3 · Marcadores de equidade
# ---------------------------------------------------------------------------

crianca = idade is not None and idade <= 10
with st.container(border=True):
    st.markdown("##### 3 · Marcadores de equidade")
    c1, c2 = st.columns(2)
    raca = c1.radio("Raça/cor", list(RACAS), None, format_func=RACAS.get, horizontal=True, key="f_raca")
    tem_def = c2.radio("Tem alguma deficiência?", list(SIM_NAO), None, format_func=SIM_NAO.get, horizontal=True,
                       key="f_def")
    tipos_escolhidos = []
    if tem_def == "sim":
        tipos = tipos_deficiencia()
        nome_tipo = {r.id_tipo_deficiencia: f"{CATEGORIAS[r.categoria]} · {r.descricao}" for r in tipos.itertuples()}
        tipos_escolhidos = c2.multiselect("Qual(is)?", list(nome_tipo), format_func=nome_tipo.get, key="f_tipos_def")

    des_os = orientacao = des_ig = identidade = None
    if idade is None:
        st.caption("Informe a idade para ver as perguntas de orientação sexual e identidade de gênero.")
    elif crianca:
        st.caption("Pessoa de 0 a 10 anos: a ficha não pergunta orientação sexual nem identidade de gênero.")
    else:
        c3, c4 = st.columns(2)
        des_os = c3.radio("Deseja informar orientação sexual?", list(SIM_NAO), None, format_func=SIM_NAO.get,
                          horizontal=True, key="f_des_os")
        if des_os == "sim":
            orientacao = c3.selectbox("Orientação sexual", list(ORIENTACOES), None, format_func=ORIENTACOES.get,
                                      key="f_os", placeholder="Escolha")
        des_ig = c4.radio("Deseja informar identidade de gênero?", list(SIM_NAO), None, format_func=SIM_NAO.get,
                          horizontal=True, key="f_des_ig")
        if des_ig == "sim":
            identidade = c4.selectbox("Identidade de gênero", list(IDENTIDADES), None, format_func=IDENTIDADES.get,
                                      key="f_ig", placeholder="Escolha")
    st.caption("\"Não\" em \"deseja informar\" registra que a pessoa **recusou**, o que é diferente de a equipe não "
               "perguntar. Por isso a resposta é obrigatória.")

# ---------------------------------------------------------------------------
# 4 · Conferência e envio
# ---------------------------------------------------------------------------

pendencias = []
if tipo == "atualizacao":
    cod = (cod_cidadao or "").strip().lower()
    if not cod:
        pendencias.append("Informe o código do cidadão (ficha de atualização).")
    elif consultar("SELECT 1 FROM cidadao WHERE cod_cidadao = %s", (cod,)).empty:
        pendencias.append(f"O código {cod} não existe no banco. Para uma pessoa nova, use \"Cadastro novo\".")
    cod_cidadao = cod
if idade is None:
    pendencias.append("Informe a idade.")
if sexo is None:
    pendencias.append("Informe o sexo.")
if raca is None:
    pendencias.append("Responda raça/cor.")
if tem_def is None:
    pendencias.append("Responda se a pessoa tem deficiência.")
elif tem_def == "sim" and not tipos_escolhidos:
    pendencias.append("Escolha pelo menos um tipo de deficiência.")
if idade is not None and not crianca:
    if des_os is None:
        pendencias.append("Responda se a pessoa deseja informar orientação sexual.")
    elif des_os == "sim" and orientacao is None:
        pendencias.append("Escolha a orientação sexual (ou marque que a pessoa não deseja informar).")
    if des_ig is None:
        pendencias.append("Responda se a pessoa deseja informar identidade de gênero.")
    elif des_ig == "sim" and identidade is None:
        pendencias.append("Escolha a identidade de gênero (ou marque que a pessoa não deseja informar).")

PROXIMO_CIDADAO = """
    INSERT INTO cidadao (cod_cidadao)
    SELECT 'c' || LPAD((COALESCE(MAX(SUBSTRING(cod_cidadao FROM 2)::int), 0) + 1)::text, 7, '0') FROM cidadao
    RETURNING cod_cidadao"""
INSERIR_FICHA = """
    INSERT INTO ficha_cadastro (data_envio, tipo_ficha, situacao, idade, sexo, usa_nome_social, raca_cor,
                                tem_deficiencia, deseja_informar_os, orientacao_sexual,
                                deseja_informar_ig, identidade_genero, ine, cod_cidadao)
    VALUES (%(data_envio)s, %(tipo_ficha)s, %(situacao)s, %(idade)s, %(sexo)s, %(usa_nome_social)s, %(raca_cor)s,
            %(tem_deficiencia)s, %(deseja_informar_os)s, %(orientacao_sexual)s,
            %(deseja_informar_ig)s, %(identidade_genero)s, %(ine)s, %(cod_cidadao)s)
    RETURNING id_ficha, data_entrada"""
INSERIR_DEFICIENCIA = "INSERT INTO ficha_deficiencia (id_ficha, id_tipo_deficiencia) VALUES (%s, %s)"


def enviar():
    """Grava cidadão (se novo), ficha e tipos de deficiência numa transação só."""
    executados = []
    with psycopg.connect(URL) as con, con.transaction(), con.cursor() as cur:
        def rodar(comando, params):
            cur.execute(comando, params)
            executados.append(psycopg.ClientCursor(con).mogrify(comando, params).strip())
            return cur.fetchone() if cur.description else None

        cidadao = cod_cidadao if tipo == "atualizacao" else rodar(PROXIMO_CIDADAO, None)[0]
        id_ficha, entrada = rodar(INSERIR_FICHA, {
            "data_envio": data_envio, "tipo_ficha": tipo, "situacao": situacao, "idade": int(idade), "sexo": sexo,
            "usa_nome_social": bool(nome_social), "raca_cor": raca, "tem_deficiencia": tem_def,
            "deseja_informar_os": des_os, "orientacao_sexual": orientacao,
            "deseja_informar_ig": des_ig, "identidade_genero": identidade,
            "ine": ine, "cod_cidadao": cidadao})
        for t in tipos_escolhidos:
            rodar(INSERIR_DEFICIENCIA, (id_ficha, int(t)))
    return {"id_ficha": id_ficha, "cidadao": cidadao, "entrada": entrada, "equipe": equipes[ine],
            "sql": executados}


with st.container(border=True):
    st.markdown("##### 4 · Enviar")
    if pendencias:
        st.warning("Falta completar:\n" + "\n".join(f"- {p}" for p in pendencias))
    if st.button("Enviar ficha", type="primary", disabled=bool(pendencias), width="stretch"):
        try:
            st.session_state["ultimo_envio"] = enviar()
        except psycopg.Error as e:   # última barreira: as restrições do próprio banco
            st.error(f"O banco recusou a ficha (nada foi gravado): {e.diag.message_primary or e}")
        else:
            st.cache_data.clear()                      # Dashboard e demais páginas releem o banco
            st.session_state["limpar_formulario"] = True
            st.rerun()

envio = st.session_state.get("ultimo_envio")
if envio:
    st.success(f"Ficha nº **{envio['id_ficha']}** gravada em "
               f"{envio['entrada'].astimezone(RECIFE):%d/%m/%Y às %H:%M:%S} · cidadão {envio['cidadao']} · "
               f"{envio['equipe']}. Guarde o número da ficha como protocolo.")
    with st.expander("SQL executado (uma transação)"):
        st.code("BEGIN;\n\n" + ";\n\n".join(envio["sql"]) + ";\n\nCOMMIT;", language="sql")

# ---------------------------------------------------------------------------
# 5 · Últimas fichas da equipe
# ---------------------------------------------------------------------------

st.markdown(f"##### Últimas fichas recebidas da equipe {equipes[ine]}")
ultimas = consultar("""
    SELECT f.id_ficha                                                    AS ficha,
           f.data_entrada                                                AS recebida_em,
           f.data_envio                                                  AS atendimento,
           f.cod_cidadao                                                 AS cidadao,
           f.idade,
           fn_estado_marcador('raca',        f.raca_cor,           f.idade) AS raca_cor,
           fn_estado_marcador('deficiencia', f.tem_deficiencia,    f.idade) AS deficiencia,
           fn_estado_marcador('orientacao',  f.deseja_informar_os, f.idade) AS orientacao_sexual,
           fn_estado_marcador('identidade',  f.deseja_informar_ig, f.idade) AS identidade_genero
    FROM ficha_cadastro f
    WHERE f.ine = %(ine)s
    ORDER BY f.data_entrada DESC, f.id_ficha DESC
    LIMIT 10""", {"ine": ine})
if len(ultimas):
    ultimas["recebida_em"] = pd.to_datetime(ultimas["recebida_em"]).dt.tz_convert(RECIFE).dt.strftime("%d/%m/%Y %H:%M")
    ultimas = ultimas.fillna({c: "fora (criança)" for c in ["orientacao_sexual", "identidade_genero"]})
st.dataframe(ultimas, hide_index=True, width="stretch")
st.caption("Estado de cada marcador pela função fn_estado_marcador (Etapa 05): Preenchido, Recusou ou N/I. "
           "Para corrigir ou excluir uma ficha, use a aba Fichas de cadastro da página Banco de Dados "
           "(as alterações ficam registradas no log de auditoria).")

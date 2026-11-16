"""
Ingestão de fichas por arquivo (CSV ou planilha Excel) direto no PostgreSQL.

Fluxo usado pela aba "Importar arquivo" da página Banco de Dados:
  1. ler()      · lê o CSV (separador e acentuação detectados) ou o .xlsx
  2. validar()  · confere cada linha contra as mesmas regras do banco (CHECKs do schema.sql) e
                  devolve as linhas válidas + uma tabela de erros (linha, coluna, problema)
  3. gravar()   · numa transação só: cidadãos novos, fichas, tipos de deficiência e o
                  RECÁLCULO de indicador_equipe nos quadrimestres que receberam fichas.
                  Todas as fichas da importação ficam com a mesma data_entrada (hora da transação)

Formato do arquivo: as colunas da Ficha de Cadastro Individual (as mesmas de
data/raw/fichas_cadastro.parquet). Campo vazio nos marcadores = N/I (a equipe não registrou).

O índice de completude é recalculado em SQL com a mesma fórmula de src/indicadores.py
(conferido: reproduz os 3.072 indicadores da carga inicial com diferença zero).
"""

import io
from datetime import date

import pandas as pd

# coluna do arquivo -> aceita também estes nomes
SINONIMOS = {
    "cod_cidadao": ["id_cidadao"],
    "data_envio": ["data_ficha"],
    "usa_nome_social": ["nome_social"],
}
OBRIGATORIAS = ["cod_cidadao", "ine", "data_envio", "idade", "sexo"]
OPCIONAIS = ["id_ficha", "tipo_ficha", "situacao", "usa_nome_social", "raca_cor", "tem_deficiencia",
             "tipo_deficiencia", "deseja_informar_os", "orientacao_sexual", "deseja_informar_ig",
             "identidade_genero"]
COLUNAS = OBRIGATORIAS + OPCIONAIS

# Mesmos domínios dos CHECKs de db/schema.sql
DOMINIOS = {
    "tipo_ficha": {"novo", "atualizacao"},
    "situacao": {"ativo", "mudou_se", "obito"},
    "sexo": {"F", "M", "I"},
    "raca_cor": {"branca", "preta", "parda", "amarela", "indigena"},
    "tem_deficiencia": {"sim", "nao"},
    "deseja_informar_os": {"sim", "nao"},
    "deseja_informar_ig": {"sim", "nao"},
    "orientacao_sexual": {"heterossexual", "gay", "lesbica", "bissexual", "assexual", "pansexual", "outra"},
    "identidade_genero": {"mulher_cis", "homem_cis", "mulher_trans", "homem_trans", "travesti",
                          "nao_binario", "outra"},
}
CATEGORIAS_DEFICIENCIA = {"auditiva", "visual", "intelectual", "fisica", "tea", "outra"}
VERDADEIRO = {"sim", "true", "1", "verdadeiro", "s"}
FALSO = {"nao", "false", "0", "falso", "n", ""}

MODELO = pd.DataFrame([
    {"cod_cidadao": "c0001054", "ine": "9000000002", "data_envio": "2026-09-15", "idade": 34, "sexo": "F",
     "tipo_ficha": "atualizacao", "situacao": "ativo", "usa_nome_social": "nao", "raca_cor": "parda",
     "tem_deficiencia": "nao", "tipo_deficiencia": "", "deseja_informar_os": "sim",
     "orientacao_sexual": "heterossexual", "deseja_informar_ig": "sim", "identidade_genero": "mulher_cis"},
    {"cod_cidadao": "c9000001", "ine": "9000000002", "data_envio": "2026-09-16", "idade": 52, "sexo": "M",
     "tipo_ficha": "novo", "situacao": "ativo", "usa_nome_social": "nao", "raca_cor": "preta",
     "tem_deficiencia": "sim", "tipo_deficiencia": "visual;fisica", "deseja_informar_os": "nao",
     "orientacao_sexual": "", "deseja_informar_ig": "", "identidade_genero": ""},
    {"cod_cidadao": "c9000002", "ine": "9000000002", "data_envio": "2026-09-16", "idade": 7, "sexo": "F",
     "tipo_ficha": "novo", "situacao": "ativo", "usa_nome_social": "nao", "raca_cor": "",
     "tem_deficiencia": "", "tipo_deficiencia": "", "deseja_informar_os": "",
     "orientacao_sexual": "", "deseja_informar_ig": "", "identidade_genero": ""},
])


def _sem_acento(texto):
    tabela = str.maketrans("áàâãéêíóôõúüç", "aaaaeeiooouuc")
    return texto.lower().translate(tabela)


def ler(arquivo, nome):
    """CSV (separador , ou ; e acentuação utf-8 ou latin-1) ou planilha .xlsx. Tudo lido como texto."""
    if nome.lower().endswith((".xlsx", ".xlsm")):
        df = pd.read_excel(arquivo, dtype=str, keep_default_na=False)
    else:
        bruto = arquivo.read() if hasattr(arquivo, "read") else open(arquivo, "rb").read()
        try:
            texto = bruto.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = bruto.decode("latin-1")
        df = pd.read_csv(io.StringIO(texto), sep=None, engine="python", dtype=str, keep_default_na=False)
    df.columns = [_sem_acento(str(c).strip()).replace(" ", "_") for c in df.columns]
    for oficial, outros in SINONIMOS.items():
        for outro in outros:
            if outro in df.columns and oficial not in df.columns:
                df = df.rename(columns={outro: oficial})
    return df


def validar(df, ines_validos, hoje=None):
    """Devolve (válidas, erros). válidas: DataFrame pronto para gravar. erros: linha, coluna, valor, problema.
    A linha do erro é a do arquivo (cabeçalho = linha 1)."""
    hoje = hoje or date.today()
    faltando = [c for c in OBRIGATORIAS if c not in df.columns]
    if faltando:
        raise ValueError(f"Colunas obrigatórias ausentes: {', '.join(faltando)}")

    d = df.copy()
    for c in COLUNAS:
        if c not in d.columns:
            d[c] = ""
    d = d[COLUNAS].astype(str).apply(lambda s: s.str.strip())
    d.insert(0, "linha", range(2, len(d) + 2))

    texto = [c for c in DOMINIOS if c != "sexo"] + ["tipo_deficiencia", "usa_nome_social"]
    for c in texto:
        d[c] = d[c].map(_sem_acento)
    d["sexo"] = d["sexo"].str.upper()
    d["ine"] = d["ine"].str.replace(r"\.0$", "", regex=True).str.zfill(10)
    d["tipo_ficha"] = d["tipo_ficha"].replace("", "novo")
    d["situacao"] = d["situacao"].replace("", "ativo")

    erros = []

    def erro(mascara, coluna, problema):
        for r in d[mascara].itertuples():
            erros.append({"linha": r.linha, "coluna": coluna, "valor": getattr(r, coluna, ""), "problema": problema})

    # Formatos
    erro(~d["cod_cidadao"].str.fullmatch(r"c\d{7}"), "cod_cidadao", "código pseudônimo deve ser 'c' + 7 dígitos")
    erro(~d["ine"].isin(ines_validos), "ine", "equipe (INE) não cadastrada no banco")

    datas = pd.to_datetime(d["data_envio"], format="%Y-%m-%d", errors="coerce")
    datas = datas.fillna(pd.to_datetime(d["data_envio"], format="%d/%m/%Y", errors="coerce"))
    erro(datas.isna(), "data_envio", "data inválida (use AAAA-MM-DD ou DD/MM/AAAA)")
    erro(datas.dt.date > hoje, "data_envio", "data no futuro")
    erro(datas.dt.year < 2017, "data_envio", "data anterior a 2017 (fora dos quadrimestres cadastrados)")
    d["data_envio"] = datas.dt.date

    idade = pd.to_numeric(d["idade"], errors="coerce")
    erro(idade.isna() | (idade % 1 != 0) | ~idade.between(0, 110), "idade", "idade deve ser inteiro de 0 a 110")
    d["idade"] = idade

    nome_social = d["usa_nome_social"]
    erro(~nome_social.isin(VERDADEIRO | FALSO), "usa_nome_social", "use sim ou não")
    d["usa_nome_social"] = nome_social.isin(VERDADEIRO)

    id_ficha = pd.to_numeric(d["id_ficha"].replace("", None), errors="coerce")
    erro((d["id_ficha"] != "") & (id_ficha.isna() | (id_ficha <= 0)), "id_ficha", "id_ficha deve ser inteiro positivo")
    erro((d["id_ficha"] != "") & d["id_ficha"].duplicated(keep=False), "id_ficha", "id_ficha repetido no arquivo")
    d["id_ficha"] = id_ficha

    # Domínios (vazio = N/I, aceito nos marcadores)
    for c, validos in DOMINIOS.items():
        invalido = ~d[c].isin(validos) if c in ("tipo_ficha", "situacao", "sexo") else (d[c] != "") & ~d[c].isin(validos)
        erro(invalido, c, f"valor fora da lista: {', '.join(sorted(validos))}")

    # Regras entre campos (as mesmas dos CHECKs)
    for pergunta, resposta in [("deseja_informar_os", "orientacao_sexual"), ("deseja_informar_ig", "identidade_genero")]:
        erro((d[pergunta] == "sim") & (d[resposta] == ""), resposta, f"{pergunta} = sim exige a resposta")
        erro((d[pergunta] != "sim") & (d[resposta] != ""), resposta, f"resposta preenchida sem {pergunta} = sim")
        erro((idade <= 10) & (d[pergunta] != ""), pergunta, "crianças de 0 a 10 anos ficam fora desta pergunta")

    tipos = d["tipo_deficiencia"].str.split(";").apply(lambda l: [t.strip() for t in l if t.strip()])
    erro(tipos.apply(lambda l: any(t not in CATEGORIAS_DEFICIENCIA for t in l)), "tipo_deficiencia",
         f"categorias válidas: {', '.join(sorted(CATEGORIAS_DEFICIENCIA))} (separe por ;)")
    erro((tipos.str.len() > 0) & (d["tem_deficiencia"] != "sim"), "tipo_deficiencia",
         "tipo informado sem tem_deficiencia = sim")
    d["tipo_deficiencia"] = tipos.apply(";".join)

    erros = pd.DataFrame(erros, columns=["linha", "coluna", "valor", "problema"]).sort_values(["linha", "coluna"])
    validas = d[~d["linha"].isin(erros["linha"])].copy()
    for c in ["raca_cor", "tem_deficiencia", "deseja_informar_os", "orientacao_sexual",
              "deseja_informar_ig", "identidade_genero", "tipo_deficiencia"]:
        validas[c] = validas[c].replace("", None)
    validas["idade"] = validas["idade"].astype(int)
    validas["id_ficha"] = validas["id_ficha"].astype("Int64")
    return validas, erros


# ---------------------------------------------------------------------------
# Gravação: SQL explícito, numa transação só
# ---------------------------------------------------------------------------

SQL_STAGE = """
CREATE TEMP TABLE stage_ficha (
    linha INTEGER, id_ficha BIGINT, data_envio DATE, tipo_ficha VARCHAR(11), situacao VARCHAR(8),
    idade SMALLINT, sexo CHAR(1), usa_nome_social BOOLEAN, raca_cor VARCHAR(8), tem_deficiencia VARCHAR(3),
    deseja_informar_os VARCHAR(3), orientacao_sexual VARCHAR(13), deseja_informar_ig VARCHAR(3),
    identidade_genero VARCHAR(12), ine CHAR(10), cod_cidadao VARCHAR(10), tipo_deficiencia TEXT
) ON COMMIT DROP"""

SQL_IDS = "UPDATE stage_ficha SET id_ficha = nextval('seq_ficha_cadastro') WHERE id_ficha IS NULL"

SQL_CIDADAOS = """
INSERT INTO cidadao (cod_cidadao)
SELECT DISTINCT cod_cidadao FROM stage_ficha
ON CONFLICT (cod_cidadao) DO NOTHING"""

SQL_FICHAS = """
CREATE TEMP TABLE fichas_inseridas ON COMMIT DROP AS
WITH ins AS (
    INSERT INTO ficha_cadastro (id_ficha, data_envio, tipo_ficha, situacao, idade, sexo, usa_nome_social,
                                raca_cor, tem_deficiencia, deseja_informar_os, orientacao_sexual,
                                deseja_informar_ig, identidade_genero, ine, cod_cidadao)
    SELECT id_ficha, data_envio, tipo_ficha, situacao, idade, sexo, usa_nome_social,
           raca_cor, tem_deficiencia, deseja_informar_os, orientacao_sexual,
           deseja_informar_ig, identidade_genero, ine, cod_cidadao
    FROM stage_ficha
    ON CONFLICT (id_ficha) DO NOTHING
    RETURNING id_ficha, data_envio
)
SELECT * FROM ins"""

SQL_SEQUENCIA = "SELECT setval('seq_ficha_cadastro', GREATEST((SELECT MAX(id_ficha) FROM ficha_cadastro), 1))"

# A ficha e-SUS informa só a categoria; o tipo detalhado é sorteado dentro dela,
# a mesma regra da carga inicial da base sintética (db/carregar_banco.py).
SQL_DEFICIENCIAS = """
INSERT INTO ficha_deficiencia (id_ficha, id_tipo_deficiencia)
SELECT DISTINCT s.id_ficha, t.id_tipo_deficiencia
FROM stage_ficha s
JOIN fichas_inseridas i ON i.id_ficha = s.id_ficha
CROSS JOIN LATERAL unnest(string_to_array(s.tipo_deficiencia, ';')) AS c(categoria)
CROSS JOIN LATERAL (
    SELECT id_tipo_deficiencia FROM tipo_deficiencia
    WHERE categoria = c.categoria
    ORDER BY random() LIMIT 1
) t
WHERE s.tipo_deficiencia IS NOT NULL"""

SQL_QUADS = """
SELECT DISTINCT q.id_quadrimestre, q.ano || '.' || q.numero AS quadrimestre
FROM fichas_inseridas i
JOIN quadrimestre q ON i.data_envio BETWEEN q.data_inicio AND q.data_fim
ORDER BY 1"""

# Mesma fórmula de src/indicadores.py: OS e IG pesam 2 (só entre maiores de 10 anos), raça e deficiência pesam 1;
# crítica = índice até o percentil 25 do próprio quadrimestre. NULL nos marcadores conta como não preenchido (N/I).
SQL_INDICADORES = """
WITH base AS (
    SELECT f.ine, q.id_quadrimestre, COUNT(*) AS qtd,
           AVG(CASE WHEN f.raca_cor IS NOT NULL THEN 1 ELSE 0 END)                                AS raca,
           AVG(CASE WHEN f.tem_deficiencia IS NOT NULL THEN 1 ELSE 0 END)                         AS def,
           AVG(CASE WHEN f.deseja_informar_os = 'sim' THEN 1 ELSE 0 END) FILTER (WHERE f.idade > 10) AS os,
           AVG(CASE WHEN f.deseja_informar_ig = 'sim' THEN 1 ELSE 0 END) FILTER (WHERE f.idade > 10) AS ig
    FROM ficha_cadastro f
    JOIN quadrimestre q ON f.data_envio BETWEEN q.data_inicio AND q.data_fim
    WHERE q.id_quadrimestre = ANY(%(quads)s) AND f.ine IS NOT NULL
    GROUP BY f.ine, q.id_quadrimestre
),
indice AS (
    SELECT *, 100 * (2 * COALESCE(os, 0) + 2 * COALESCE(ig, 0) + raca + def) / 6 AS indice FROM base
),
limite AS (
    SELECT id_quadrimestre, PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY indice) AS lim
    FROM indice GROUP BY id_quadrimestre
)
INSERT INTO indicador_equipe (ine, id_quadrimestre, qtd_fichas, indice_completude, critica, risco_previsto)
SELECT x.ine, x.id_quadrimestre, x.qtd, ROUND(x.indice, 2), x.indice <= l.lim,
       -- risco provisório (equipe nova no período): fração dos quadrimestres anteriores em que foi crítica
       (SELECT ROUND(AVG(CASE WHEN a.critica THEN 1 ELSE 0 END), 4)
        FROM indicador_equipe a JOIN quadrimestre qa ON qa.id_quadrimestre = a.id_quadrimestre
        JOIN quadrimestre qx ON qx.id_quadrimestre = x.id_quadrimestre
        WHERE a.ine = x.ine AND qa.data_inicio < qx.data_inicio)
FROM indice x JOIN limite l USING (id_quadrimestre)
ON CONFLICT (ine, id_quadrimestre) DO UPDATE
    SET qtd_fichas = EXCLUDED.qtd_fichas,
        indice_completude = EXCLUDED.indice_completude,
        critica = EXCLUDED.critica"""

COLUNAS_STAGE = ["linha", "id_ficha", "data_envio", "tipo_ficha", "situacao", "idade", "sexo", "usa_nome_social",
                 "raca_cor", "tem_deficiencia", "deseja_informar_os", "orientacao_sexual", "deseja_informar_ig",
                 "identidade_genero", "ine", "cod_cidadao", "tipo_deficiencia"]


def _python(v):
    """NaN/NA viram NULL; tipos do numpy viram tipos do Python (o COPY do psycopg pede isso)."""
    if v is None or v is pd.NA or (isinstance(v, float) and pd.isna(v)):
        return None
    return v.item() if hasattr(v, "item") else v


def gravar(url, validas):
    """Grava as linhas válidas numa transação só (ou tudo grava, ou nada grava).
    Abre a própria conexão para a transação ser de verdade. Devolve um resumo e o SQL executado."""
    import psycopg

    executados = []
    con = psycopg.connect(url, autocommit=True)

    def rodar(cur, comando, params=None):
        cur.execute(comando, params)
        executados.append(psycopg.ClientCursor(con).mogrify(comando, params).strip()
                          if params else comando.strip())
        return cur

    with con.transaction(), con.cursor() as cur:
        # now() é a hora da transação: a mesma que o DEFAULT grava em data_entrada de todas as fichas
        entrada = rodar(cur, "SELECT now()").fetchone()[0]
        rodar(cur, SQL_STAGE)
        with cur.copy(f"COPY stage_ficha ({', '.join(COLUNAS_STAGE)}) FROM STDIN") as copia:
            for linha in validas[COLUNAS_STAGE].itertuples(index=False):
                copia.write_row([_python(v) for v in linha])
        executados.append(f"COPY stage_ficha ({', '.join(COLUNAS_STAGE)}) FROM STDIN  -- {len(validas)} linhas do arquivo")
        rodar(cur, SQL_IDS)
        cidadaos_novos = rodar(cur, SQL_CIDADAOS).rowcount
        rodar(cur, SQL_FICHAS)
        fichas_novas = rodar(cur, "SELECT COUNT(*) FROM fichas_inseridas").fetchone()[0]
        rodar(cur, SQL_SEQUENCIA)
        deficiencias = rodar(cur, SQL_DEFICIENCIAS).rowcount
        quads = rodar(cur, SQL_QUADS).fetchall()
        indicadores = rodar(cur, SQL_INDICADORES, {"quads": [q[0] for q in quads]}).rowcount if quads else 0
    con.close()

    return {
        "data_entrada": entrada,
        "linhas_validas": len(validas),
        "fichas_inseridas": fichas_novas,
        "ja_existiam": len(validas) - fichas_novas,
        "cidadaos_novos": cidadaos_novos,
        "deficiencias": deficiencias,
        "quadrimestres": [q[1] for q in quads],
        "indicadores": indicadores,
    }, executados


def ines_cadastrados(url):
    import psycopg

    with psycopg.connect(url) as con, con.cursor() as cur:
        cur.execute("SELECT ine FROM equipe")
        return {r[0] for r in cur.fetchall()}


def erros_csv(erros):
    return erros.to_csv(index=False).encode("utf-8-sig")


def modelo_csv():
    return MODELO.to_csv(index=False).encode("utf-8-sig")


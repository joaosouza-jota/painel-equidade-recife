"""
Carrega a base do projeto no PostgreSQL (esquema db/schema.sql).

Lê o que o pipeline já produz (data/raw e app/dados) e grava nas 9 tabelas do modelo lógico.
Todo comando é SQL explícito: INSERT para as tabelas pequenas e COPY (carga em lote do PostgreSQL)
para as grandes (cidadão, ficha e ficha_deficiencia).

Conexão só pela variável de ambiente DATABASE_URL (PostgreSQL local ou Neon). Exemplo local:
    export DATABASE_URL="postgresql:///painel_equidade"

Ao final cria a camada do painel (db/painel.sql) e roda a pipeline (src/pipeline.py).

Uso (na raiz do projeto, depois de src/gerar_sintetico.py e do pipeline):
    python db/carregar_banco.py
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
from gerar_sintetico import RAW, distrito_sanitario, normalizar  # noqa: E402

rng = np.random.default_rng(42)

# Detalhamento legal de cada categoria da ficha e-SUS (Decreto 5.296/2004, art. 5º;
# Lei 14.126/2021 visão monocular; Lei 14.768/2023 auditiva unilateral; Lei 12.764/2012 TEA)
TIPOS_DEFICIENCIA = {
    "fisica": ["Paraplegia", "Paraparesia", "Monoplegia", "Monoparesia", "Tetraplegia",
               "Tetraparesia", "Triplegia", "Triparesia", "Hemiplegia", "Hemiparesia",
               "Ostomia", "Amputação ou ausência de membro", "Paralisia cerebral",
               "Nanismo", "Membro com deformidade congênita ou adquirida"],
    "auditiva": ["Perda auditiva bilateral parcial", "Surdez bilateral total",
                 "Perda auditiva unilateral"],
    "visual": ["Cegueira", "Baixa visão", "Visão monocular", "Campo visual reduzido"],
    "intelectual": ["Deficiência intelectual leve", "Deficiência intelectual moderada",
                    "Deficiência intelectual grave", "Deficiência intelectual profunda"],
    "tea": ["Transtorno do espectro autista"],
    "outra": ["Deficiência múltipla", "Surdocegueira", "Deficiência psicossocial"],
}


def chave(nome):
    # "Sítio dos Pintos - São Brás" (IBGE/CNES) é "Sítio dos Pintos" no mapa oficial
    return normalizar(str(nome).split(" - ")[0])


def nulo(v):
    """'' e NaN do pandas viram NULL; tipos do numpy viram tipos do Python."""
    if v is None or v is pd.NA or (isinstance(v, float) and np.isnan(v)) or v == "":
        return None
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def copiar(cur, tabela, colunas, linhas):
    with cur.copy(f"COPY {tabela} ({', '.join(colunas)}) FROM STDIN") as copia:
        for linha in linhas:
            copia.write_row([nulo(v) for v in linha])


def main():
    terr = pd.read_csv(RAW / "territorio_equipes.csv", dtype=str)
    fichas = pd.read_parquet(RAW / "fichas_cadastro.parquet")
    resumo = pd.read_parquet(RAIZ / "app" / "dados" / "resumo_equipes.parquet")

    geo = json.load(open(RAW / "bairros_recife_2023.geojson"))
    censo = json.load(open(RAW / "ibge" / "populacao_bairro_recife_2022.json"))[0]["resultados"][0]["series"]
    pop = {chave(s["localidade"]["nome"].split(" - Recife")[0]): int(s["serie"]["2022"]) for s in censo}

    with psycopg.connect(os.environ["DATABASE_URL"]) as con, con.cursor() as cur:
        cur.execute((RAIZ / "db" / "schema.sql").read_text())

        # BAIRRO: os 94 bairros oficiais, com distrito e população do Censo 2022
        for f in sorted(geo["features"], key=lambda f: f["properties"]["EBAIRRNOMEOF"]):
            p = f["properties"]
            cur.execute(
                "INSERT INTO bairro (nome, nr_distrito, populacao_2022) VALUES (%s, %s, %s)",
                (p["EBAIRRNOMEOF"], distrito_sanitario(p["CRPAAACODI"], p["CMICROCODI"]), pop[chave(p["EBAIRRNOME"])]))
        cur.execute("SELECT id_bairro, nome FROM bairro")
        id_bairro = {chave(nome): i for i, nome in cur.fetchall()}

        # UNIDADE_SAUDE e EQUIPE
        for u in terr.drop_duplicates("cnes").itertuples():
            cur.execute(
                "INSERT INTO unidade_saude (cnes, nome, latitude, longitude, id_bairro) VALUES (%s, %s, %s, %s, %s)",
                (u.cnes, u.nome_unidade, round(float(u.latitude), 6), round(float(u.longitude), 6), id_bairro[chave(u.bairro)]))
        for e in terr.itertuples():
            cur.execute("INSERT INTO equipe (ine, nome, cnes) VALUES (%s, %s, %s)", (e.ine, e.nome_equipe, e.cnes))

        # CIDADAO e FICHA_CADASTRO (COPY: ~325 mil cidadãos e ~770 mil fichas)
        copiar(cur, "cidadao", ["cod_cidadao"], ((c,) for c in fichas["id_cidadao"].unique()))
        colunas = ["id_ficha", "data_envio", "tipo_ficha", "situacao", "idade", "sexo", "usa_nome_social",
                   "raca_cor", "tem_deficiencia", "deseja_informar_os", "orientacao_sexual",
                   "deseja_informar_ig", "identidade_genero", "ine", "cod_cidadao"]
        f = fichas.rename(columns={"data_ficha": "data_envio", "nome_social": "usa_nome_social", "id_cidadao": "cod_cidadao"})
        f["data_envio"] = f["data_envio"].dt.date
        copiar(cur, "ficha_cadastro", colunas, f[colunas].itertuples(index=False))
        cur.execute("SELECT setval('seq_ficha_cadastro', (SELECT MAX(id_ficha) FROM ficha_cadastro))")

        # TIPO_DEFICIENCIA e FICHA_DEFICIENCIA (cada categoria da ficha vira um tipo detalhado)
        for categoria, descricoes in TIPOS_DEFICIENCIA.items():
            for d in descricoes:
                cur.execute("INSERT INTO tipo_deficiencia (descricao, categoria) VALUES (%s, %s)", (d, categoria))
        cur.execute("SELECT id_tipo_deficiencia, descricao FROM tipo_deficiencia")
        id_tipo = {d: i for i, d in cur.fetchall()}
        com_def = fichas.loc[fichas["tipo_deficiencia"].fillna("") != "", ["id_ficha", "tipo_deficiencia"]]
        pares = {(int(r.id_ficha), id_tipo[rng.choice(TIPOS_DEFICIENCIA[c])])
                 for r in com_def.itertuples() for c in r.tipo_deficiencia.split(";")}
        copiar(cur, "ficha_deficiencia", ["id_ficha", "id_tipo_deficiencia"], sorted(pares))

        # QUADRIMESTRE (2017 a 2026) e INDICADOR_EQUIPE
        inicio, fim = {1: "01-01", 2: "05-01", 3: "09-01"}, {1: "04-30", 2: "08-31", 3: "12-31"}
        for ano in range(2017, 2027):
            for n in (1, 2, 3):
                cur.execute("INSERT INTO quadrimestre (ano, numero, data_inicio, data_fim) VALUES (%s, %s, %s, %s)",
                            (ano, n, f"{ano}-{inicio[n]}", f"{ano}-{fim[n]}"))
        resumo = resumo.sort_values(["ine", "quadrimestre"])
        # risco previsto provisório: fração dos quadrimestres anteriores em que a equipe foi crítica
        # (nulo no 1º quadrimestre). O modelo de ML substitui esta coluna nas próximas sprints.
        resumo["risco_previsto"] = resumo.groupby("ine")["critica"].transform(lambda s: s.shift().expanding().mean())
        for r in resumo.itertuples():
            ano, n = r.quadrimestre.split(".")
            cur.execute(
                "INSERT INTO indicador_equipe (ine, id_quadrimestre, qtd_fichas, indice_completude, critica, risco_previsto) "
                "VALUES (%s, (SELECT id_quadrimestre FROM quadrimestre WHERE ano = %s AND numero = %s), %s, %s, %s, %s)",
                (r.ine, int(ano), int(n), int(r.n_fichas), round(float(r.indice_completude), 2), bool(r.critica),
                 None if pd.isna(r.risco_previsto) else round(float(r.risco_previsto), 4)))

        # Camada do painel (visões materializadas) e registro de execuções da pipeline
        cur.execute((RAIZ / "db" / "painel.sql").read_text())
        cur.execute("ANALYZE")
        for t in ["bairro", "unidade_saude", "equipe", "cidadao", "ficha_cadastro", "tipo_deficiencia",
                  "ficha_deficiencia", "quadrimestre", "indicador_equipe"]:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(f"{t:18} {cur.fetchone()[0]:>9,}")


if __name__ == "__main__":
    main()
    # Pipeline: agregados do painel + modelo de ML gravando o risco (src/pipeline.py)
    sys.path.insert(0, str(RAIZ / "src"))
    from pipeline import rodar
    rodar(os.environ["DATABASE_URL"], gatilho="carga_inicial")

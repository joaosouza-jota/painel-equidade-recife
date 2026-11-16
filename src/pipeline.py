"""
Pipeline automatizada do Painel de Equidade, rodando sobre o PostgreSQL (local ou Neon).

    fichas no banco ─► 1. agregados do painel ─► 2. modelo de ML ─► 3. risco gravado ─► painel
                        (visões materializadas)   (treina e avalia)   (indicador_equipe)

Gatilhos:
  - importação de arquivo na página Banco de Dados (roda sozinha depois de gravar as fichas)
  - botão "Rodar pipeline agora" na aba Pipeline da mesma página
  - linha de comando:  python src/pipeline.py   (ex.: agendado, ou depois de db/carregar_banco.py)

Passos:
  1. REFRESH das visões materializadas de db/painel.sql (o que o painel lê)
  2. Modelo: base de variáveis (src/features.py) a partir de mv_resumo_equipe; avaliação TEMPORAL
     (treino no passado, teste nos 2 quadrimestres rotulados mais recentes) contra a baseline de
     persistência; depois treina com todo o histórico rotulado
  3. Grava indicador_equipe.risco_previsto = P(equipe crítica no quadrimestre SEGUINTE)
  4. Registra a execução em execucao_pipeline (tempos, F1 do modelo e da persistência, equipes em risco)

Conexão só por DATABASE_URL (variável de ambiente ou .streamlit/secrets.toml), nunca no código.
"""

import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
from features import ALVO, VARIAVEIS, base_do_resumo  # noqa: E402

MODELO = "regressão logística"
LIMIAR = 0.5                 # risco >= 0,5 = equipe em risco no próximo quadrimestre
QUADS_TESTE = 2              # avaliação: os 2 quadrimestres rotulados mais recentes ficam de fora do treino
VISOES = ["mv_resumo_equipe", "mv_estados_distrito", "mv_populacao_usf"]


def url_banco():
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    segredos = RAIZ / ".streamlit" / "secrets.toml"
    if segredos.exists():
        achado = re.search(r'^DATABASE_URL\s*=\s*"(.+)"\s*$', segredos.read_text(), re.M)
        if achado:
            return achado.group(1)
    raise SystemExit("Defina DATABASE_URL (variável de ambiente ou .streamlit/secrets.toml)")


def novo_modelo():
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000))


def treinar_e_prever(resumo):
    """Devolve (previsões por ine x quadrimestre, métricas da avaliação temporal)."""
    from sklearn.metrics import f1_score

    base = base_do_resumo(resumo)
    X = base[VARIAVEIS].fillna(0)
    rotulada = base[base[ALVO].notna()]
    quads = sorted(rotulada["quadrimestre"].unique())

    metricas = {"f1_modelo": None, "f1_persistencia": None}
    if len(quads) > QUADS_TESTE:
        teste = rotulada["quadrimestre"].isin(quads[-QUADS_TESTE:])
        treino = rotulada[~teste]
        teste = rotulada[teste]
        m = novo_modelo().fit(X.loc[treino.index], treino[ALVO].astype(int))
        y = teste[ALVO].astype(int)
        metricas["f1_modelo"] = f1_score(y, m.predict_proba(X.loc[teste.index])[:, 1] >= LIMIAR)
        metricas["f1_persistencia"] = f1_score(y, teste["critica"])

    final = novo_modelo().fit(X.loc[rotulada.index], rotulada[ALVO].astype(int))
    previsoes = base[["ine", "quadrimestre"]].assign(risco=final.predict_proba(X)[:, 1].round(4))
    ultimo = base["quadrimestre"].max()
    metricas["ultimo_quadrimestre"] = ultimo
    metricas["equipes_em_risco"] = int((previsoes.loc[previsoes["quadrimestre"] == ultimo, "risco"] >= LIMIAR).sum())
    return previsoes, metricas


def rodar(url=None, gatilho="linha_de_comando", log=print):
    """Roda a pipeline inteira. Devolve um dicionário com o resumo da execução."""
    import psycopg

    url = url or url_banco()
    inicio = time.time()
    with psycopg.connect(url, autocommit=True) as con:
        id_exec = con.execute("INSERT INTO execucao_pipeline (gatilho) VALUES (%s) RETURNING id_execucao",
                              (gatilho,)).fetchone()[0]
        try:
            tempos = {}
            # 1. agregados do painel
            t = time.time()
            for visao in VISOES:
                con.execute(f"REFRESH MATERIALIZED VIEW {visao}")
            tempos["agregados"] = time.time() - t
            log(f"1/3 Agregados do painel atualizados ({tempos['agregados']:.1f} s)")

            # 2. modelo
            t = time.time()
            cur = con.execute("SELECT * FROM mv_resumo_equipe")
            resumo = pd.DataFrame(cur.fetchall(), columns=[c.name for c in cur.description])
            previsoes, metricas = treinar_e_prever(resumo)
            tempos["modelo"] = time.time() - t
            log(f"2/3 Modelo treinado ({tempos['modelo']:.1f} s) · F1 {metricas['f1_modelo']:.3f} "
                f"contra {metricas['f1_persistencia']:.3f} da persistência" if metricas["f1_modelo"] is not None
                else f"2/3 Modelo treinado ({tempos['modelo']:.1f} s) · histórico curto, sem avaliação")

            # 3. risco gravado no banco (uma transação: ou tudo, ou nada)
            t = time.time()
            with con.transaction(), con.cursor() as c:
                c.execute("CREATE TEMP TABLE risco_novo (ine CHAR(10), quadrimestre TEXT, risco NUMERIC(5,4)) ON COMMIT DROP")
                with c.copy("COPY risco_novo (ine, quadrimestre, risco) FROM STDIN") as copia:
                    for linha in previsoes.itertuples(index=False):
                        copia.write_row((linha.ine, linha.quadrimestre, float(linha.risco)))
                c.execute("""
                    UPDATE indicador_equipe i
                       SET risco_previsto = r.risco
                      FROM risco_novo r
                      JOIN quadrimestre q ON q.ano || '.' || q.numero = r.quadrimestre
                     WHERE i.ine = r.ine AND i.id_quadrimestre = q.id_quadrimestre""")
                atualizados = c.rowcount
            tempos["risco"] = time.time() - t
            log(f"3/3 Risco gravado em {atualizados} indicadores ({tempos['risco']:.1f} s) · "
                f"{metricas['equipes_em_risco']} equipes em risco após {metricas['ultimo_quadrimestre']}")

            fichas = con.execute("SELECT COUNT(*) FROM ficha_cadastro").fetchone()[0]
            con.execute("""
                UPDATE execucao_pipeline
                   SET fim = now(), situacao = 'ok', fichas_no_banco = %s, ultimo_quadrimestre = %s, modelo = %s,
                       f1_modelo = %s, f1_persistencia = %s, equipes_em_risco = %s
                 WHERE id_execucao = %s""",
                        (fichas, metricas["ultimo_quadrimestre"], MODELO,
                         None if metricas["f1_modelo"] is None else round(metricas["f1_modelo"], 3),
                         None if metricas["f1_persistencia"] is None else round(metricas["f1_persistencia"], 3),
                         metricas["equipes_em_risco"], id_exec))
        except Exception as e:
            con.execute("UPDATE execucao_pipeline SET fim = now(), situacao = 'erro', erro = %s WHERE id_execucao = %s",
                        (str(e)[:1000], id_exec))
            raise
    return {"id_execucao": id_exec, "segundos": time.time() - inicio, "indicadores": atualizados, **metricas, **tempos}


if __name__ == "__main__":
    r = rodar(gatilho=sys.argv[1] if len(sys.argv) > 1 else "linha_de_comando")
    print(f"Pipeline ok em {r['segundos']:.1f} s (execução nº {r['id_execucao']})")

"""
Resultado do modelo (Estação 4, segunda parte): o modelo da pipeline contra a persistência e contra
alternativas, mais as justificativas do limiar e do alvo.

Responde ao feedback do SR1 (ponto 1):
  1. F1 e recall do modelo frente à persistência
  2. Comparação com alternativas: árvore de decisão e random forest
  3. Justificativa do limiar de 0,5
  4. Alvo relativo (25% piores) x meta absoluta de completude
  5. Quanto da persistência alta vem da regra do gerador sintético

Usa exatamente o que a pipeline usa (src/pipeline.py): o mesmo resumo por equipe x quadrimestre,
as mesmas variáveis (src/features.py), o mesmo modelo, o mesmo limiar e a mesma divisão temporal.
Por isso o F1 daqui é o mesmo que aparece na aba Pipeline do app.

Candidatos: os modelos previstos em docs/arquitetura.md (KNN, árvore, regressão) mais a Random Forest
sugerida no feedback. Hiperparâmetros por GridSearchCV com validação cruzada temporal.

Cada execução fica registrada no MLflow (Sprint 4 de docs/arquitetura.md): um run por modelo, com
hiperparâmetros, métricas e um run filho para cada combinação do GridSearch. A decisão também fica lá
(tag "decisao"). O MLflow é só do experimento: a pipeline do app não depende dele.

Uso:
  pip install -r requirements-ml.txt
  python src/modelos.py                   # registra em ./mlflow.db
  mlflow ui --backend-store-uri sqlite:///mlflow.db --host 127.0.0.1 --port 5001
  (ou com Docker: docker compose up -d  e  MLFLOW_TRACKING_URI=http://127.0.0.1:5001 python src/modelos.py)
Saída: notebooks/resultados/modelos.csv, limiar.csv, alvo.csv, persistencia.csv, coeficientes.csv
       e mlflow_runs.csv (todos os runs da execução, para o rastro ficar também no repositório)
"""

import os
import sys
import time
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import GridSearchCV
from sklearn.neighbors import KNeighborsClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier

try:
    import mlflow
except ImportError:          # sem MLflow o script roda igual, só não registra
    mlflow = None

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))
from features import ALVO, VARIAVEIS, base_do_resumo  # noqa: E402
from pipeline import LIMIAR, QUADS_TESTE, novo_modelo  # noqa: E402

RESUMO = RAIZ / "app" / "dados" / "resumo_equipes.parquet"   # cópia do mv_resumo_equipe do banco
RESULTADOS = RAIZ / "notebooks" / "resultados"
SEMENTE = 42
META_ABSOLUTA = 50   # alternativa ao alvo relativo: "crítica = índice abaixo de 50"
EXPERIMENTO = "risco-equipe-critica"

# Complexidade para desempate (quanto menor, mais fácil de explicar à Secretaria e mais estável)
COMPLEXIDADE = {"Regressão logística (pipeline)": 1, "Árvore de decisão": 2, "KNN": 2, "Random Forest": 3}

# Alternativas e os hiperparâmetros testados no GridSearch (grades pequenas de propósito)
ALTERNATIVAS = {
    "KNN": (
        make_pipeline(StandardScaler(), KNeighborsClassifier()),   # KNN usa distância: precisa de escala
        {"kneighborsclassifier__n_neighbors": [15, 31, 51], "kneighborsclassifier__weights": ["uniform", "distance"]},
    ),
    "Árvore de decisão": (
        DecisionTreeClassifier(random_state=SEMENTE),
        {"max_depth": [3, 5, 8], "min_samples_leaf": [1, 20, 50]},
    ),
    "Random Forest": (
        RandomForestClassifier(n_estimators=200, random_state=SEMENTE, n_jobs=-1),
        {"max_depth": [5, 10, None], "min_samples_leaf": [1, 20]},
    ),
}


# ---------------------------------------------------------------------------
# Dados e divisão (iguais aos da pipeline)
# ---------------------------------------------------------------------------

def carregar_base():
    base = base_do_resumo(pd.read_parquet(RESUMO))
    base[VARIAVEIS] = base[VARIAVEIS].fillna(0)          # a pipeline faz o mesmo
    rotulada = base[base[ALVO].notna()].copy()
    rotulada[ALVO] = rotulada[ALVO].astype(int)
    return rotulada


def dividir(rotulada):
    """Teste = os QUADS_TESTE quadrimestres rotulados mais recentes; treino = todo o resto (o passado)."""
    quads = sorted(rotulada["quadrimestre"].unique())
    teste = rotulada["quadrimestre"].isin(quads[-QUADS_TESTE:])
    return rotulada[~teste], rotulada[teste]


def folds_temporais(treino, n=2):
    """Validação cruzada no tempo, só dentro do treino: para cada um dos n últimos quadrimestres do treino,
    treina com os anteriores e valida nele. O cv=5 comum sortearia linhas e misturaria passado e futuro."""
    quads = sorted(treino["quadrimestre"].unique())
    q = treino["quadrimestre"].values
    return [(np.where(q < v)[0], np.where(q == v)[0]) for v in quads[-n:]]


# ---------------------------------------------------------------------------
# Comparação
# ---------------------------------------------------------------------------

def linha(nome, y, alerta, prob=None):
    return {
        "modelo": nome,
        "f1": f1_score(y, alerta),
        "recall": recall_score(y, alerta),
        "precisao": precision_score(y, alerta),
        "roc_auc": None if prob is None else roc_auc_score(y, prob),
        "equipes_alertadas": int(np.sum(alerta)),
        "criticas_no_teste": int(np.sum(y)),
    }


def janela_movel(rotulada, criar, minimo=3):
    """F1 médio em várias rodadas: para cada quadrimestre a partir do 'minimo'-ésimo, treina com todos os
    anteriores e testa nele. Mostra se o resultado se sustenta fora dos 2 quadrimestres do teste."""
    quads = sorted(rotulada["quadrimestre"].unique())
    f1s = []
    for q in quads[minimo:]:
        tr, te = rotulada[rotulada["quadrimestre"] < q], rotulada[rotulada["quadrimestre"] == q]
        if criar is None:                                 # persistência
            f1s.append(f1_score(te[ALVO], te["critica"]))
        else:
            m = criar().fit(tr[VARIAVEIS], tr[ALVO])
            f1s.append(f1_score(te[ALVO], m.predict_proba(te[VARIAVEIS])[:, 1] >= LIMIAR))
    return float(np.mean(f1s)), float(np.std(f1s))


def registrar(nome, metricas, params=None, busca=None, modelo=None):
    """Um run do MLflow por modelo (filho do run da comparação). Sem MLflow, não faz nada."""
    if mlflow is None:
        return
    with mlflow.start_run(run_name=nome, nested=True):
        mlflow.set_tag("tipo", "baseline" if nome.startswith("Persist") else "modelo")
        mlflow.log_params({"limiar": LIMIAR, "quads_teste": QUADS_TESTE, **(params or {})})
        mlflow.log_metrics({k: v for k, v in metricas.items()
                            if isinstance(v, (int, float)) and v is not None and not np.isnan(v)})
        if busca is not None:                     # cada combinação do GridSearch vira um run filho
            cv = pd.DataFrame(busca.cv_results_)
            for _, c in cv.iterrows():
                params = {k.split("__")[-1]: v for k, v in c["params"].items()}   # tira o prefixo do Pipeline
                with mlflow.start_run(run_name=f"{nome} · {params}", nested=True):
                    mlflow.set_tag("tipo", "combinacao")
                    mlflow.log_params(params)
                    mlflow.log_metrics({"f1_validacao_media": c["mean_test_score"],
                                        "f1_validacao_desvio": c["std_test_score"]})
        if modelo is not None:
            mlflow.sklearn.log_model(modelo, name="modelo", serialization_format="cloudpickle")


def comparar(rotulada):
    treino, teste = dividir(rotulada)
    X_tr, y_tr, X_te, y_te = treino[VARIAVEIS], treino[ALVO], teste[VARIAVEIS], teste[ALVO]
    linhas = []

    r = linha("Persistência (baseline)", y_te, teste["critica"])
    r["janela_f1"], r["janela_f1_desvio"] = janela_movel(rotulada, None)
    linhas.append(r)
    registrar(r["modelo"], r, {"regra": "crítica agora = crítica no próximo"})

    m = novo_modelo().fit(X_tr, y_tr)
    p = m.predict_proba(X_te)[:, 1]
    r = linha("Regressão logística (pipeline)", y_te, p >= LIMIAR, p)
    r["janela_f1"], r["janela_f1_desvio"] = janela_movel(rotulada, novo_modelo)
    linhas.append(r)
    registrar(r["modelo"], r, {"modelo": "StandardScaler + LogisticRegression(max_iter=2000)"}, modelo=m)

    for nome, (estimador, grade) in ALTERNATIVAS.items():
        busca = GridSearchCV(estimador, grade, scoring="f1", cv=folds_temporais(treino)).fit(X_tr, y_tr)
        melhor = busca.best_estimator_
        p = melhor.predict_proba(X_te)[:, 1]
        r = linha(nome, y_te, p >= LIMIAR, p)
        r["hiperparametros"] = str({k.split("__")[-1]: v for k, v in busca.best_params_.items()})
        r["f1_validacao"] = busca.best_score_
        r["janela_f1"], r["janela_f1_desvio"] = janela_movel(rotulada, lambda: clone(melhor))
        linhas.append(r)
        registrar(nome, r, {k.split("__")[-1]: v for k, v in busca.best_params_.items()}, busca=busca, modelo=melhor)

    return pd.DataFrame(linhas).set_index("modelo")


def escolher(tabela):
    """Regra de escolha: entre os modelos que superam a persistência na janela móvel, ficam os que estão
    a menos de 1 desvio padrão do melhor (empate técnico); desses, o mais simples (COMPLEXIDADE)."""
    modelos = tabela.drop(index="Persistência (baseline)")
    modelos = modelos[modelos["janela_f1"] > tabela.loc["Persistência (baseline)", "janela_f1"]]
    melhor = modelos["janela_f1"].idxmax()
    corte = modelos.loc[melhor, "janela_f1"] - modelos.loc[melhor, "janela_f1_desvio"]
    empatados = modelos[modelos["janela_f1"] >= corte].index
    return min(empatados, key=lambda n: COMPLEXIDADE[n]), list(empatados)


# ---------------------------------------------------------------------------
# Limiar, alvo e persistência
# ---------------------------------------------------------------------------

def varrer_limiar(rotulada, limiares=np.arange(0.20, 0.81, 0.05)):
    """F1, recall e precisão da regressão logística para cada limiar.
    'validacao' = média dos folds temporais do treino (é onde o limiar deve ser escolhido);
    'teste' = só para conferir, sem usar na escolha."""
    treino, teste = dividir(rotulada)
    prob_val = []
    for i_tr, i_val in folds_temporais(treino):
        tr, val = treino.iloc[i_tr], treino.iloc[i_val]
        m = novo_modelo().fit(tr[VARIAVEIS], tr[ALVO])
        prob_val.append((val[ALVO].values, m.predict_proba(val[VARIAVEIS])[:, 1]))
    m = novo_modelo().fit(treino[VARIAVEIS], treino[ALVO])
    y_te, p_te = teste[ALVO].values, m.predict_proba(teste[VARIAVEIS])[:, 1]

    linhas = []
    for t in limiares:
        linhas.append({
            "limiar": round(float(t), 2),
            "f1_validacao": np.mean([f1_score(y, p >= t) for y, p in prob_val]),
            "recall_validacao": np.mean([recall_score(y, p >= t) for y, p in prob_val]),
            "precisao_validacao": np.mean([precision_score(y, p >= t) for y, p in prob_val]),
            "f1_teste": f1_score(y_te, p_te >= t),
            "alertadas_teste": int((p_te >= t).sum()),
        })
    return pd.DataFrame(linhas).set_index("limiar")


def alvo_relativo_x_absoluto():
    """Por quadrimestre: quantas equipes seriam críticas com a meta absoluta (índice < 50) e com a regra
    relativa (as 25% piores)."""
    resumo = pd.read_parquet(RESUMO)
    g = resumo.groupby("quadrimestre")
    return pd.DataFrame({
        "equipes": g.size(),
        "indice_mediano": g["indice_completude"].median(),
        "pct_abaixo_da_meta": g["indice_completude"].apply(lambda s: (s < META_ABSOLUTA).mean() * 100),
        "pct_criticas_relativo": g["critica"].mean() * 100,
    })


def persistencia_no_tempo(rotulada):
    """F1 da persistência em cada quadrimestre: 'crítica em t' acerta 'crítica em t+1'?"""
    return (rotulada.groupby("quadrimestre")
            .apply(lambda d: f1_score(d[ALVO], d["critica"]), include_groups=False)
            .rename("f1_persistencia").to_frame())


def coeficientes(rotulada):
    """Pesos da regressão logística treinada como na pipeline (todo o histórico rotulado).
    As variáveis passam pelo StandardScaler, então os pesos são comparáveis entre si: peso positivo
    aumenta o risco, negativo diminui; quanto maior em módulo, mais a variável pesa."""
    m = novo_modelo().fit(rotulada[VARIAVEIS], rotulada[ALVO])
    pesos = pd.Series(m[-1].coef_[0], index=VARIAVEIS, name="peso")
    return pesos.reindex(pesos.abs().sort_values(ascending=False).index).to_frame()


def exportar_runs(inicio):
    """Copia os runs desta execução do MLflow para um CSV versionado no git."""
    runs = mlflow.search_runs(experiment_names=[EXPERIMENTO])
    runs = runs[runs["start_time"] >= pd.Timestamp(inicio, unit="s", tz="UTC") - pd.Timedelta(seconds=5)]
    colunas = (["tags.mlflow.runName", "tags.tipo", "tags.decisao", "run_id", "tags.mlflow.parentRunId"]
               + sorted(c for c in runs.columns if c.startswith(("params.", "metrics."))))
    tabela = runs.reindex(columns=colunas).rename(columns=lambda c: c.split(".")[-1])
    tabela.round(4).to_csv(RESULTADOS / "mlflow_runs.csv", index=False)
    return len(tabela)


def main():
    rotulada = carregar_base()
    treino, teste = dividir(rotulada)
    print(f"Treino: {len(treino):,} linhas ({treino['quadrimestre'].min()} a {treino['quadrimestre'].max()}) · "
          f"Teste: {len(teste):,} linhas ({', '.join(sorted(teste['quadrimestre'].unique()))})")

    if mlflow is not None:
        mlflow.set_tracking_uri(os.environ.get("MLFLOW_TRACKING_URI", f"sqlite:///{RAIZ / 'mlflow.db'}"))
        mlflow.set_experiment(EXPERIMENTO)
    else:
        print("MLflow não instalado (pip install -r requirements-ml.txt): resultados só em CSV")

    inicio = time.time()
    with (mlflow.start_run(run_name="comparacao") if mlflow else nullcontext()):
        modelos = comparar(rotulada)
        escolhido, empatados = escolher(modelos)
        modelos["empate_tecnico"] = modelos.index.isin(empatados)
        modelos["escolhido"] = modelos.index == escolhido
        resultados = {
            "modelos": modelos,
            "limiar": varrer_limiar(rotulada),
            "alvo": alvo_relativo_x_absoluto(),
            "persistencia": persistencia_no_tempo(rotulada),
            "coeficientes": coeficientes(rotulada),
        }
        RESULTADOS.mkdir(parents=True, exist_ok=True)
        for nome, df in resultados.items():
            df.round(3).to_csv(RESULTADOS / f"{nome}.csv")
        if mlflow:
            mlflow.set_tags({"decisao": escolhido, "empate_tecnico": ", ".join(empatados)})
            for nome in resultados:
                mlflow.log_artifact(str(RESULTADOS / f"{nome}.csv"))

    with pd.option_context("display.width", 240, "display.max_columns", 20):
        for nome, df in resultados.items():
            print(f"\n== {nome}\n{df.round(3)}")
    print(f"\nEmpate técnico (até 1 desvio do melhor na janela móvel): {', '.join(empatados)}")
    print(f"Escolhido (o mais simples do empate): {escolhido}")
    if mlflow:
        n = exportar_runs(inicio)
        print(f"MLflow: {n} runs no experimento '{EXPERIMENTO}' (cópia em notebooks/resultados/mlflow_runs.csv)")


if __name__ == "__main__":
    main()

"""
Divisão treino/teste e baselines (Estação 4, primeira versão).

Baseline = a régua mínima. Qualquer modelo das próximas sprints (KNN, árvore, regressão logística)
só se justifica se for melhor que estas regras simples.

  1. Sempre "não crítica"   (DummyClassifier most_frequent): o piso, acerta 75% sem prever nada
  2. Sorteio de 25%          (DummyClassifier stratified): chutar na proporção certa
  3. Persistência            "quem é crítica agora continua crítica": a régua de verdade
  4. Média histórica         "as 25% piores na média de todo o histórico serão as críticas"

Divisão TEMPORAL, não aleatória: treino com o passado, teste com os quadrimestres mais recentes.
Sortear linhas deixaria o modelo aprender com o futuro de uma equipe para prever o passado dela.

Uso:  python src/baseline.py
Saída: notebooks/resultados/baseline.csv
"""

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score

from features import ALVO, VARIAVEIS

RAIZ = Path(__file__).resolve().parents[1]
PROCESSED = RAIZ / "data" / "processed"
RESULTADOS = RAIZ / "notebooks" / "resultados"

# Quadrimestre t da linha (as variáveis); o alvo é sempre o quadrimestre seguinte
TREINO = ["2024.2", "2024.3", "2025.1", "2025.2"]   # alvos de 2024.3 a 2025.3
TESTE = ["2025.3", "2026.1"]                         # alvos de 2026.1 e 2026.2
SEMENTE = 42


def dividir(base):
    rotulada = base[base[ALVO].notna()].copy()
    rotulada[ALVO] = rotulada[ALVO].astype(int)
    treino = rotulada[rotulada["quadrimestre"].isin(TREINO)]
    teste = rotulada[rotulada["quadrimestre"].isin(TESTE)]
    return treino, teste


def regra_media_historica(df):
    """Marca como crítica as 25% piores equipes na média histórica, dentro de cada quadrimestre."""
    limite = df.groupby("quadrimestre")["media_historica"].transform(lambda s: s.quantile(0.25))
    return (df["media_historica"] <= limite).astype(int).values


def metricas(nome, y_real, y_prev):
    return {
        "baseline": nome,
        "recall (críticas encontradas)": recall_score(y_real, y_prev, zero_division=0),
        "precisão (alertas certos)": precision_score(y_real, y_prev, zero_division=0),
        "F1": f1_score(y_real, y_prev, zero_division=0),
        "acurácia": accuracy_score(y_real, y_prev),
        "equipes alertadas": int(np.sum(y_prev)),
        "críticas encontradas": int(np.sum((y_prev == 1) & (y_real == 1))),
        "críticas no teste": int(np.sum(y_real)),
    }


def avaliar(treino, teste):
    X_tr, y_tr = treino[VARIAVEIS], treino[ALVO]
    X_te, y_te = teste[VARIAVEIS], teste[ALVO].values
    linhas = []
    for nome, estrategia in [("1. Sempre 'não crítica'", "most_frequent"), ("2. Sorteio de 25%", "stratified")]:
        dummy = DummyClassifier(strategy=estrategia, random_state=SEMENTE).fit(X_tr, y_tr)
        linhas.append(metricas(nome, y_te, dummy.predict(X_te)))
    linhas.append(metricas("3. Persistência", y_te, teste["critica"].values))
    linhas.append(metricas("4. Média histórica", y_te, regra_media_historica(teste)))
    return pd.DataFrame(linhas).set_index("baseline")


def main():
    base = pd.read_parquet(PROCESSED / "base_modelo.parquet")
    treino, teste = dividir(base)
    resultado = avaliar(treino, teste)

    RESULTADOS.mkdir(parents=True, exist_ok=True)
    resultado.round(3).to_csv(RESULTADOS / "baseline.csv")

    print(f"Treino: {len(treino):,} linhas ({TREINO[0]} a {TREINO[-1]}) · Teste: {len(teste):,} linhas ({', '.join(TESTE)})")
    with pd.option_context("display.width", 200, "display.max_columns", 20):
        print(resultado.round(3))


if __name__ == "__main__":
    main()

# Handoff · Modelo de ML (SR2)

Vinicius → João · 27/11/2026

## O que foi feito

Dois PRs, independentes entre si. Nenhum muda o modelo que está no ar (regressão logística, limiar 0,5).

| PR | O que é | Muda o app? |
|---|---|---|
| #1 `fix/quadrimestre-aberto` | Correção: quadrimestre em andamento não entra no modelo nem vira o padrão do painel | Sim, só o aviso e o "—" quando o quadrimestre está aberto. Números iguais ao `main` |
| #2 `docs/resultado-modelo` | Resposta ao ponto 1 do feedback do SR1: comparação de modelos, limiar, alvo, dados sintéticos e registro no MLflow | Não. Só arquivos novos, README e `docs/arquitetura.md` |

## PR #2 em uma tabela

| Pedido do professor | Onde está a resposta |
|---|---|
| F1 e recall do modelo frente à persistência | README "Resultado atual do modelo" e notebook 04, seção 1: 0,852 / 0,885 contra 0,833 / 0,833 |
| Comparar ao menos uma alternativa | KNN, árvore e random forest com `GridSearchCV` e validação cruzada temporal. Random forest empata, as outras não superam a persistência |
| Justificar o limiar de 0,5 | Notebook 04, seção 2: F1 estável entre 0,35 e 0,50 na validação |
| Alvo relativo x meta absoluta | Notebook 04, seção 3: com "índice < 50" a fila iria de 16% a 26% das equipes |
| Persistência alta e dados sintéticos | Notebook 04, seção 4: a regra do gerador (0,6 × desvio anterior) explica boa parte |

## Como reproduzir

```bash
pip install -r requirements-ml.txt
python src/modelos.py          # ~25 s: grava notebooks/resultados/ e registra no MLflow (./mlflow.db)
jupyter nbconvert --execute --inplace notebooks/04_modelos.ipynb
mlflow ui --backend-store-uri sqlite:///mlflow.db --host 127.0.0.1 --port 5001
```

Os números saem iguais aos da aba *Pipeline* do app porque `src/modelos.py` importa `novo_modelo`, `LIMIAR` e `QUADS_TESTE` de `src/pipeline.py` e usa `app/dados/resumo_equipes.parquet` (cópia do `mv_resumo_equipe` do Neon). Se alguém mudar o modelo ou o limiar na pipeline, a comparação acompanha.

## Rastro dos experimentos

- **MLflow**, experimento `risco-equipe-critica`: um run `comparacao` com a decisão na tag `decisao`, um run por modelo (parâmetros, métricas, modelo salvo) e um run por combinação do GridSearch.
- O `mlflow.db` não vai para o git (regra do `.gitignore`). Por isso cada execução exporta os runs para `notebooks/resultados/mlflow_runs.csv`, que vai.
- A pipeline do app **não** usa MLflow (o Streamlit Cloud não alcança um servidor MLflow). Ela continua registrando cada execução em `execucao_pipeline`.

## Decisões

1. **Regressão logística continua.** A regra de escolha está no código (`escolher` em `src/modelos.py`): entre os modelos que superam a persistência na janela móvel, os que ficam a até 1 desvio padrão do melhor são empate técnico, e no empate fica o mais simples.
2. **Validação cruzada temporal**, nunca `cv=5` aleatório: cada fold treina no passado e valida no quadrimestre seguinte.
3. **Limiar 0,5 mantido.** 0,35 é a alternativa se a Secretaria preferir não perder nenhuma equipe (mesmo F1, mais alertas).
4. **Regressão (prever a nota do índice) ficou de fora.** Testamos: nenhum regressor superou a regra "a nota se mantém" no MAE. O produto responde com a classificação.

## Pendências

- [ ] Revisar e mergear o PR #1 (de preferência depois da apresentação) e conferir a página Painel no app publicado.
- [ ] Revisar e mergear o PR #2.
- [ ] `docker-compose.yml` não foi testado com Docker (o mesmo comando do `mlflow server` foi testado sem Docker). Se a imagem der problema, o caminho `mlflow ui` faz o mesmo.
- [ ] MinIO (previsto em `docs/arquitetura.md`) não foi feito: só faz falta se os artefatos do MLflow precisarem ficar num servidor compartilhado.
- [ ] Bug antigo, fora dos PRs: a tela "Equipe de Saúde" dá `KeyError` quando o distrito não tem equipes.
- [ ] Quando houver dados reais do PEC: rodar `python src/modelos.py` de novo. Os números atuais valem para a base sintética.

# Painel de Equidade em Saúde do Recife

Pipeline de dados e Machine Learning para transformar os cadastros do PEC/e-SUS APS em indicadores de equidade (raça/cor, deficiência, orientação sexual e identidade de gênero) e prever quais Equipes de Saúde da Família vão precisar de apoio para qualificar o registro.

Projeto 3 (Dados) + Machine Learning I · CESAR School · 2026.2 · Cliente: Secretaria de Saúde do Recife

> **Base de dados sintética.** A Secretaria não liberou os dados reais do PEC. O projeto usa uma base gerada por código, no formato do PEC (ver `docs/contrato_dados.md`). Quando a extração real existir nesse formato, o pipeline roda sem mudanças.

## Estrutura

```
docs/        contrato de dados e arquitetura
src/         código do pipeline
notebooks/   análise exploratória e experimentos
app/         protótipo navegável
data/        dados gerados (fora do git)
```

## Como rodar

Requer Python 3.12. Instale as dependências uma vez:

```bash
pip install -r requirements.txt
```

Rode o pipeline em ordem (a base inteira é recriada em menos de 1 minuto):

```bash
python src/gerar_sintetico.py                                 # 1. gera território + fichas sintéticas
python src/tratamento.py                                      # 2. padroniza e valida
cd src && python features.py && python baseline.py && cd ..   # 3 e 4. base do modelo e baselines
cd src && python preparar_painel.py && cd ..                  # agrega os dados do painel (app/dados)
streamlit run app/app.py                                      # 5. abre o painel no navegador
```

Para só abrir o painel, basta o último comando: os dados agregados que ele usa (`app/dados/`) já estão no repositório. O painel não lê nenhuma ficha individual, apenas contagens por equipe, USF e distrito.

Os notebooks (`notebooks/01_eda.ipynb` e `02_baseline.ipynb`) já estão salvos com as saídas e podem ser reexecutados depois do passo 3.

## Documentação

| Documento | Conteúdo |
|---|---|
| `docs/contrato_dados.md` | Formato dos dados, regras de negócio e a fonte de cada parâmetro da base sintética |
| `docs/arquitetura.md` | As 5 estações do pipeline, decisões de arquitetura e tecnologias |
| `notebooks/01_eda.ipynb` | Análise exploratória: 7 perguntas, 7 gráficos |
| `notebooks/02_baseline.ipynb` | Problema supervisionado, divisão temporal treino/teste e baselines |

## Resultado atual (S06 · 26/09/2026)

| Baseline | Recall (críticas encontradas) | F1 |
|---|---|---|
| Sempre "não crítica" | 0,00 | 0,00 |
| Sorteio de 25% | 0,29 | 0,29 |
| **Persistência** (quem é crítica continua crítica) | **0,83** | **0,83** |
| Média histórica | 0,79 | 0,79 |

A persistência é a régua que os modelos da Sprint 1 precisam superar.

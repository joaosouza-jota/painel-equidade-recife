# Painel de Equidade em Saúde do Recife

Pipeline de dados e Machine Learning para transformar os cadastros do PEC/e-SUS APS em indicadores de equidade (raça/cor, deficiência, orientação sexual e identidade de gênero) e prever quais Equipes de Saúde da Família vão precisar de apoio para qualificar o registro.

Projeto 3 (Dados) + Machine Learning I · CESAR School · 2026.2 · Cliente: Secretaria de Saúde do Recife

> **Base de dados sintética.** A Secretaria não liberou os dados reais do PEC. O projeto usa uma base gerada por código, no formato do PEC (ver `docs/contrato_dados.md`). Quando a extração real existir nesse formato, o pipeline roda sem mudanças.

## Estrutura

```
docs/        contrato de dados e arquitetura
src/         código do pipeline
db/          banco PostgreSQL: esquema, carga e consultas
notebooks/   análise exploratória, experimentos e base proxy (Inferência)
app/         app Streamlit: Painel + Banco de Dados
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

### Banco de dados (PostgreSQL)

Um banco só para o projeto: as 9 tabelas do modelo lógico (Banco de Dados), a tabela `respostas_sinteticas` (Inferência Estatística) e o risco previsto por equipe (Machine Learning). Funciona com PostgreSQL local ou Neon: a conexão vem **só** da variável `DATABASE_URL`, nunca do código.

```bash
createdb painel_equidade                                   # PostgreSQL local (ou crie um projeto no Neon)
export DATABASE_URL="postgresql:///painel_equidade"        # Neon: postgresql://usuario:senha@host/neondb?sslmode=require
python db/carregar_banco.py                                # cria o esquema (db/schema.sql) e carrega a base (~15 s)
jupyter nbconvert --execute --inplace notebooks/03_base_proxy_distritos.ipynb   # grava respostas_sinteticas
streamlit run app/app.py                                   # página "Banco de Dados" no menu lateral
```

| Arquivo | Conteúdo |
|---|---|
| `db/schema.sql` | Esquema (tabelas, restrições, sequências, índices) |
| `db/carregar_banco.py` | Carga da base do pipeline no banco (INSERT e COPY explícitos) |
| `db/consultas.py` | As 7 consultas da interface (fonte única do SQL) |
| `db/consultas.sql` | As mesmas consultas com valores de exemplo, prontas para o psql (gerado por `db/gerar_consultas_sql.py`) |
| `db/ingestao.py` | Importação de fichas por CSV/planilha: validação, gravação e recálculo dos indicadores |
| `db/gerar_exemplos_ingestao.py` | Arquivos de teste da importação em `data/exemplos/` (a partir da base sintética) |
| `db/painel.sql` | Camada do painel: visões materializadas (agregados) e o registro `execucao_pipeline` |
| `src/pipeline.py` | Pipeline: atualiza os agregados, treina e avalia o modelo, grava o risco |
| `app/dados_painel.py` | De onde o Painel e as Estatísticas leem (banco ou cópia estática) |
| `db/migrar_para_neon.sh` | Copia o banco local inteiro para o Neon e confere tabela por tabela |
| `db/migracoes/` | Alterações para bancos criados antes de cada mudança (ex.: `data_entrada`) |
| `app/paginas/banco_de_dados.py` | Interface: consultas com gráficos, tabelas, cadastro de equipes e fichas, importação de arquivo |

`ficha_cadastro.data_envio` é quando a equipe enviou a ficha; `data_entrada` é quando ela entrou no banco (preenchida pelo próprio banco). A aba "Importar arquivo" mostra o histórico de entradas.

#### Versão final da interface (Banco de Dados · Etapa 06)

Tudo roda no mesmo banco e no mesmo app. Mapa do enunciado:

| Requisito | Onde está no app |
|---|---|
| CRUD em pelo menos 4 tabelas | Página **Banco de Dados**, abas **Equipes** (`equipe`), **Unidades de saúde** (`unidade_saude`), **Tipos de deficiência** (`tipo_deficiencia`) e **Fichas de cadastro** (`ficha_cadastro`, que grava também `cidadao` e `ficha_deficiencia` na mesma transação). Inserir, alterar e excluir; as recusas do banco (CHECK, UNIQUE, ON DELETE RESTRICT) aparecem na tela |
| Funções, procedimentos e triggers (Etapa 05) | Aba **Funções, procedimentos e triggers**: `fn_estado_marcador` (testar valores, inclusive o erro de marcador inválido, e ver a função aplicada às fichas), `fn_indice_completude` (função × valor gravado, por quadrimestre), `CALL pr_recalcular_indicadores` (antes/depois + RAISE NOTICE), `CALL pr_agendar_apoio` (agenda do apoiador em gráfico), triggers `trg_ficha_log` e `trg_ficha_sem_deficiencia` (demonstração em transação desfeita + log real das alterações feitas na aba Fichas) |
| Consultas e visões (Etapas 03 e 04) com filtros e gráficos | Aba **Consultas e gráficos**, grupos *Etapa 03* (7 consultas), *Etapa 04* (anti join, full outer join, 2 com subconsultas) e *Visões* (`vw_indicador_territorio`, `vw_ficha_marcadores`). Filtros: quadrimestre e distrito na barra lateral, mais grupo, tipos de deficiência e limite em pp conforme a consulta. Cada uma mostra gráfico, tabela e o SQL executado. As visões também aparecem na aba **Tabelas e visões** |
| Dashboard estatístico sobre os dados do banco | Página **Dashboard** (`app/paginas/dashboard.py`): 8 indicadores resumidos com variação para o quadrimestre anterior; média, mediana, moda, variância, desvio padrão, coeficiente de variação e quartis de 4 variáveis, **calculados pelo PostgreSQL** (AVG, PERCENTILE_CONT, MODE, VAR_SAMP, STDDEV_SAMP); 8 gráficos: tendência temporal (linha), histograma com média/mediana/moda, dispersão por distrito (boxplot), frequência do estado do registro (barras empilhadas), composição por raça/cor (rosca), correlação fichas × índice com reta de regressão (CORR, REGR_SLOPE), série mensal com média móvel (janela) e pirâmide etária. Filtros de período e distritos valem para a página inteira; legendas clicáveis e zoom nos gráficos |
| Extra: formulário para as equipes, conectado ao banco | Página **Formulário da equipe** (`app/paginas/formulario.py`): a equipe escolhe distrito → unidade → equipe e preenche a ficha (identificação + marcadores de equidade). Campos aparecem conforme as respostas (criança não vê orientação/identidade; tipos de deficiência só com "sim"); raça/cor, deficiência e "deseja informar?" são obrigatórios (o formulário não gera N/I); confere tudo antes de enviar; grava cidadão, ficha e tipos numa transação e devolve o número da ficha. Mostra o índice da equipe no quadrimestre atual calculado na hora por `fn_indice_completude` e as últimas fichas com `fn_estado_marcador` |

Consultas novas da Etapa 04 ficaram em `db/consultas.py` (fonte única), parametrizadas pelo quadrimestre e distrito da tela.

#### Pipeline automatizada

```
arquivo (CSV/Excel) ─► validação ─► fichas no banco (data_entrada) ─► indicadores das equipes
   ─► agregados do painel (visões materializadas, db/painel.sql) ─► modelo de ML (src/pipeline.py)
   ─► risco de cada equipe no próximo quadrimestre ─► Painel e Estatísticas
```

Roda sozinha depois de cada importação na aba "Importar arquivo"; também pelo botão da aba "Pipeline" ou por `python src/pipeline.py`. Cada execução fica registrada em `execucao_pipeline` (tempo, F1 do modelo contra a persistência, equipes em risco). O Painel e as Estatísticas leem do banco; sem banco configurado, leem a cópia estática de `app/dados/` (e o risco vira a baseline de persistência).

#### Banco na nuvem (Neon)

1. Crie um projeto no [Neon](https://neon.tech) (PostgreSQL 17, região São Paulo) e copie a string de conexão **direta** (sem `-pooler`).
2. Grave em `.streamlit/secrets.toml` (fica fora do GitHub): `DATABASE_URL = "postgresql://...neon.tech/neondb?sslmode=require"`
3. `bash db/migrar_para_neon.sh`: copia o banco local e confere as contagens.
4. No Streamlit Cloud: *Settings → Secrets*, a mesma linha do passo 2. A página Banco de Dados passa a funcionar no app publicado.

A página Banco de Dados usa a variável `DATABASE_URL` ou o segredo `DATABASE_URL` do Streamlit. Sem nenhum dos dois, mostra um aviso e não toca em banco nenhum.

## Documentação

| Documento | Conteúdo |
|---|---|
| `docs/contrato_dados.md` | Formato dos dados, regras de negócio e a fonte de cada parâmetro da base sintética |
| `docs/arquitetura.md` | As 5 estações do pipeline, decisões de arquitetura e tecnologias |
| `notebooks/01_eda.ipynb` | Análise exploratória: 7 perguntas, 7 gráficos |
| `notebooks/02_baseline.ipynb` | Problema supervisionado, divisão temporal treino/teste e baselines |
| `notebooks/03_base_proxy_distritos.ipynb` | Inferência Estatística: base proxy de orientação sexual e identidade de gênero por distrito, validada com testes |

## Resultado atual (S06 · 26/09/2026)

| Baseline | Recall (críticas encontradas) | F1 |
|---|---|---|
| Sempre "não crítica" | 0,00 | 0,00 |
| Sorteio de 25% | 0,29 | 0,29 |
| **Persistência** (quem é crítica continua crítica) | **0,83** | **0,83** |
| Média histórica | 0,79 | 0,79 |

A persistência é a régua que os modelos da Sprint 1 precisam superar.

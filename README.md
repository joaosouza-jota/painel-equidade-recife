# Painel de Equidade em Saúde do Recife

Pipeline de dados e Machine Learning para transformar os cadastros do PEC/e-SUS APS em indicadores de equidade (raça/cor, deficiência, orientação sexual e identidade de gênero) e prever quais Equipes de Saúde da Família vão precisar de apoio para qualificar o registro.

Projeto 3 (Dados) + Machine Learning I · CESAR School · 2026.2 · Cliente: Secretaria de Saúde do Recife

## 🔗 [Abrir o app publicado (Painel, Dashboard, Banco de Dados e Formulário)](https://painel-equidade-recife-wk2ayj4vdi6qsjuuxxkc4e.streamlit.app/)

**https://painel-equidade-recife-wk2ayj4vdi6qsjuuxxkc4e.streamlit.app/**

> **Base de dados sintética.** A Secretaria não liberou os dados reais do PEC. O projeto usa uma base gerada por código, no formato do PEC (ver `docs/contrato_dados.md`). Quando a extração real existir nesse formato, o pipeline roda sem mudanças.

## Projeto de Banco de Dados (Parte 02): onde está cada requisito

Mapa dos itens do enunciado "BD Projeto - Parte 02" (Etapas 04, 05 e 06) até o lugar exato no projeto, com o que cada um faz aqui. Todo o SQL do banco está em [`db/schema.sql`](db/schema.sql); as consultas da interface, em [`db/consultas.py`](db/consultas.py). No app, a página **Banco de Dados** tem uma aba para cada parte, e todo resultado vem acompanhado do **SQL executado**.

**Contexto do domínio:** as equipes de Saúde da Família do Recife preenchem a Ficha de Cadastro Individual do e-SUS. A Secretaria de Saúde precisa saber quais equipes deixam de registrar os marcadores de equidade (raça/cor, deficiência, orientação sexual, identidade de gênero). Cada marcador fica em um de três estados: **Preenchido**, **Recusou** (a pessoa não quis informar) ou **N/I** (a equipe não registrou). O N/I é a falha que o sistema mede.

### Etapa 04 · Consultas avançadas, visões e índices

**Índices** (2 novos, usados pelas consultas abaixo)

| Requisito | Onde | O que faz no projeto |
|---|---|---|
| Índice 1 | [`ix_ficha_genero_diverso`](db/schema.sql#L265) | Índice **parcial** em `ficha_cadastro (ine, data_envio)`, só com as fichas de pessoas trans, travestis e não binárias (~0,6% da tabela). Faz a consulta anti join (8) achar, equipe por equipe, se existe algum registro do grupo sem varrer as 770 mil fichas. |
| Índice 2 | [`ix_fd_tipo`](db/schema.sql#L271) | Índice em `ficha_deficiencia (id_tipo_deficiencia)`: o caminho "quais fichas têm este tipo de deficiência". Usado pela consulta 10 (onde vivem as pessoas surdas) e pela checagem da chave estrangeira ao excluir um tipo. |

**Consultas** (4 novas, todas parametrizadas na interface: aba *Consultas e gráficos* → grupo *Etapa 04*)

| Requisito | Onde | O que faz no projeto |
|---|---|---|
| Anti join | [`anti_join`](db/consultas.py#L244) · consulta 8 | `LEFT JOIN ... WHERE f.id_ficha IS NULL`: lista as equipes que mandaram centenas de fichas em 12 meses e **nenhuma** registra pessoa trans, travesti ou não binária. É sinal de que a pergunta não está sendo feita: candidata a oficina. |
| Full outer join | [`full_outer`](db/consultas.py#L273) · consulta 9 | Compara a identidade de gênero **esperada** no distrito (base proxy da Inferência Estatística, `respostas_sinteticas`) com a **registrada** nas fichas. O FULL OUTER JOIN mantém as categorias que só aparecem de um lado, que um INNER JOIN esconderia. |
| Subconsulta 1 | [`libras`](db/consultas.py#L320) · consulta 10 | `IN` aninhado em 2 níveis (nome do tipo → id → fichas) + subconsulta escalar correlacionada (ficha mais recente do cidadão). Mostra as unidades com mais pessoas ativas do tipo de deficiência escolhido, por exemplo surdez, para decidir onde ter intérprete de Libras. |
| Subconsulta 2 | [`persistentes`](db/consultas.py#L350) · consulta 11 | `IN` com `GROUP BY / HAVING BOOL_AND` + 2 subconsultas escalares correlacionadas: equipes críticas nos 3 últimos quadrimestres seguidos (problema estrutural), com quantas vezes cada uma foi crítica no histórico. |

**Visões** (2, com 4 joins cada)

| Requisito | Onde | Justificativa semântica |
|---|---|---|
| Visão 1 | [`vw_indicador_territorio`](db/schema.sql#L274) | Junta `indicador_equipe`, `quadrimestre`, `equipe`, `unidade_saude` e `bairro`: o indicador de cada equipe já situado no território (distrito → unidade → equipe), na linguagem da gestão. É a base do ranking, do dashboard e das consultas 8 e 11. |
| Visão 2 | [`vw_ficha_marcadores`](db/schema.sql#L296) | Cada ficha com o estado de cada marcador (Preenchido / Recusou / N/I) e a exclusão das crianças de 0 a 10 anos das perguntas de orientação e identidade. Fixa num lugar só uma regra que, se errada, muda quem aparece como equipe crítica. |

### Etapa 05 · Funções, procedimentos e triggers

| Requisito | Onde | O que faz no projeto |
|---|---|---|
| Função 1 (com estrutura condicional) | [`fn_estado_marcador(marcador, resposta, idade)`](db/schema.sql#L367) | Devolve Preenchido, Recusou, N/I ou NULL (criança fora do marcador). Usa `IF / ELSIF / ELSE` em dois níveis, porque a regra muda conforme o marcador: em raça/cor e deficiência não existe recusa. Marcador desconhecido gera `RAISE EXCEPTION`. |
| Função 2 | [`fn_indice_completude(ine, id_quadrimestre)`](db/schema.sql#L428) | Calcula na hora, direto das fichas, o índice de completude (0 a 100) de uma equipe num quadrimestre. Serve para conferir o valor gravado e para mostrar à equipe o índice atualizado no momento em que ela envia uma ficha. |
| Procedimento de atualização | [`pr_recalcular_indicadores(ano, numero)`](db/schema.sql#L475) | `UPDATE` da quantidade de fichas e do índice de cada equipe, `INSERT` das equipes que passaram a ter fichas no período e `UPDATE` de quem é crítica (25% piores do quadrimestre). |
| Procedimento com cursor | [`pr_agendar_apoio(ano, numero, horas_semana)`](db/schema.sql#L588) | Monta a agenda semanal do apoiador de cada distrito para as equipes em risco (tabela [`agenda_apoio`](db/schema.sql#L568)). O cursor percorre as equipes da mais urgente para a menos urgente e encaixa cada uma na primeira semana com horas livres (*first-fit*). **Por que precisa de cursor:** a semana de cada equipe depende das horas já ocupadas pelas anteriores. Um `UPDATE` ou `INSERT ... SELECT` só enxerga a tabela como ela estava antes do comando, então não vê as próprias colocações. |
| Trigger 1 (atualiza tabela de log) | [`trg_ficha_log`](db/schema.sql#L726) + [`fn_trg_ficha_log`](db/schema.sql#L699) | Depois de cada alteração ou exclusão de ficha, grava em [`log_ficha_cadastro`](db/schema.sql#L684) quem fez, quando, quais campos mudaram e a ficha antes e depois. É auditoria de dado sensível (LGPD). |
| Trigger 2 | [`trg_ficha_sem_deficiencia`](db/schema.sql#L769) + [`fn_trg_ficha_sem_deficiencia`](db/schema.sql#L753) | Se a ficha deixa de ter `tem_deficiencia = 'sim'`, remove os tipos de deficiência ligados a ela. Mantém a ficha coerente sem depender de quem edita lembrar disso. |

### Etapa 06 · Interface funcional com dashboard (versão final)

| Requisito | Onde | O que faz no projeto |
|---|---|---|
| CRUD em pelo menos 4 tabelas | Página **Banco de Dados** ([`banco_de_dados.py`](app/paginas/banco_de_dados.py)), abas **Equipes** (`equipe`), **Unidades de saúde** (`unidade_saude`), **Tipos de deficiência** (`tipo_deficiencia`) e **Fichas de cadastro** (`ficha_cadastro`) | Inserir, consultar, alterar e excluir. A ficha grava também `cidadao` e `ficha_deficiencia` na mesma transação. Quando o banco recusa (CHECK, UNIQUE, `ON DELETE RESTRICT`), o motivo aparece na tela. |
| Executar/ver efeitos das funções, procedimentos e triggers | Aba **Funções, procedimentos e triggers** | `fn_estado_marcador`: testar valores (inclusive o erro de marcador inválido) e ver a função aplicada às fichas do distrito. `fn_indice_completude`: valor da função ao lado do valor gravado, por quadrimestre. `pr_recalcular_indicadores` e `pr_agendar_apoio`: botão `CALL`, com o antes/depois, os avisos do banco (`RAISE NOTICE`) e a agenda em gráfico. Triggers: demonstração numa transação desfeita no fim (mostra os tipos de deficiência removidos e a linha do log) e o log real das alterações feitas na aba Fichas. |
| Consultas e visões das Etapas 03 e 04 na interface, com filtros e parâmetros | Aba **Consultas e gráficos**, grupos *Etapa 03*, *Etapa 04* e *Visões*; as visões também estão na aba **Tabelas e visões** | 7 consultas da Etapa 03 (ranking das equipes críticas, estado do registro por distrito, evolução do índice, concentração da população por bairro, equipes que entraram na lista crítica, possível erro de raça/cor, esperado × registrado), as 4 da Etapa 04 e as 2 visões. Filtros: quadrimestre e distrito na barra lateral, mais grupo populacional, tipos de deficiência e limite em pontos percentuais, conforme a consulta. |
| Apresentação visual clara de cada consulta/visão | Mesma aba | Cada consulta tem a pergunta que responde, as técnicas SQL usadas, um gráfico próprio (barras, linhas, pontos), a tabela do resultado e o SQL executado. |
| Dashboard sobre os dados do banco | Página **Dashboard** ([`dashboard.py`](app/paginas/dashboard.py)) | Toda a página é SQL executado na hora no PostgreSQL. As estatísticas são calculadas **pelo banco** (`AVG`, `PERCENTILE_CONT`, `MODE`, `VAR_SAMP`, `STDDEV_SAMP`, `CORR`, `REGR_SLOPE`); o Python só desenha. Cada bloco tem o SQL executado. |
| Indicadores resumidos | Dashboard, topo | Total de fichas, pessoas cadastradas, equipes e unidades, idade média, índice de completude médio e % de equipes críticas (com a variação para o quadrimestre anterior), % de N/I em orientação sexual, % de pessoas com deficiência. |
| Média, mediana, moda, variância e desvio padrão | Dashboard, bloco "Medidas de posição e dispersão" | Para 4 variáveis à escolha (índice das equipes, fichas por equipe, risco previsto, idade das pessoas): média, mediana, moda, variância, desvio padrão, coeficiente de variação, mínimo, quartis e máximo. |
| Pelo menos 6 gráficos dinâmicos | Dashboard, 8 gráficos | 1 **linha**: tendência do índice por distrito ao longo dos quadrimestres (média ou mediana). 2 **histograma**: distribuição do índice, com média, mediana e moda marcadas. 3 **boxplot**: dispersão do índice dentro de cada distrito (quartis, média, desvio). 4 **barras empilhadas**: frequência de Preenchido / Recusou / N/I por marcador. 5 **pizza (rosca)**: composição por raça/cor, com a fatia de N/I. 6 **dispersão**: correlação de Pearson entre volume de fichas e índice, com a reta de regressão. 7 **barras + linha**: fichas por mês com média móvel de 3 meses (tendência temporal). 8 **pirâmide etária**: distribuição por faixa etária e sexo. |
| Visualizações interativas (períodos, categorias, filtros) | Dashboard, barra lateral e gráficos | Intervalo de quadrimestres e distritos (valem para a página inteira), escolha da variável e da medida, legenda clicável para destacar um distrito, zoom no gráfico de dispersão, tooltip em todos os gráficos. |
| Extra: formulário para as equipes | Página **Formulário da equipe** ([`formulario.py`](app/paginas/formulario.py)) | A equipe escolhe distrito → unidade → equipe e preenche a ficha. Os campos aparecem conforme as respostas, e o formulário não deixa enviar com marcador em branco (N/I). Grava cidadão, ficha e tipos de deficiência numa transação e devolve o número da ficha. Mostra na hora o índice da equipe (`fn_indice_completude`) e as últimas fichas com o estado de cada marcador (`fn_estado_marcador`). |

### Interface e regras de integração

| Requisito | Como o projeto atende |
|---|---|
| Aplicação web integrada ao banco | App web em Streamlit, publicado (link no topo), ligado ao PostgreSQL (banco local ou na nuvem). |
| Comandos explícitos no backend | Todo comando é SQL escrito à mão e enviado pelo **psycopg**, o driver do PostgreSQL para Python (papel equivalente ao JDBC). As telas mostram o SQL exato que o banco recebeu. |
| Proibido ORM ou camada de abstração do banco | Nenhum ORM (SQLAlchemy, Django ORM etc.). INSERT, UPDATE, DELETE e SELECT são strings SQL com parâmetros. Os parâmetros evitam SQL injection; nomes de tabela, que não podem ser parâmetros, entram como identificadores seguros vindos de uma lista fixa. |

### Requisitos não funcionais

| Requisito | Como o projeto atende |
|---|---|
| Identificadores significativos | Tabelas, colunas e objetos com nomes do domínio (`ficha_cadastro`, `indice_completude`, `deseja_informar_os`, `fn_estado_marcador`, `pr_agendar_apoio`, `trg_ficha_log`); restrições nomeadas pelo tipo (`pk_`, `fk_`, `ck_`, `uq_`, `ix_`). |
| Código organizado, documentado e explicado | Cada arquivo começa com um cabeçalho dizendo o que faz. Cada objeto do `schema.sql` tem comentário com a justificativa semântica. Cada consulta tem a pergunta que responde e as técnicas usadas, mostradas também na tela. |

## Estrutura

```
docs/        contrato de dados e arquitetura
src/         código do pipeline
db/          banco PostgreSQL: esquema, carga e consultas
notebooks/   análise exploratória, experimentos e base proxy (Inferência)
docker-compose.yml   servidor do MLflow para os experimentos (opcional)
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

#### Pipeline automatizada

```
arquivo (CSV/Excel) ─► validação ─► fichas no banco (data_entrada) ─► indicadores das equipes
   ─► agregados do painel (visões materializadas, db/painel.sql) ─► modelo de ML (src/pipeline.py)
   ─► risco de cada equipe no próximo quadrimestre ─► Painel e Estatísticas
```

Roda sozinha depois de cada importação na aba "Importar arquivo"; também pelo botão da aba "Pipeline" ou por `python src/pipeline.py`. Cada execução fica registrada em `execucao_pipeline` (tempo, F1 do modelo contra a persistência, equipes em risco). O Painel e as Estatísticas leem do banco; sem banco configurado, leem a cópia estática de `app/dados/` (e o risco vira a baseline de persistência).

## Documentação

| Documento | Conteúdo |
|---|---|
| `docs/contrato_dados.md` | Formato dos dados, regras de negócio e a fonte de cada parâmetro da base sintética |
| `docs/arquitetura.md` | As 5 estações do pipeline, decisões de arquitetura e tecnologias |
| `notebooks/01_eda.ipynb` | Análise exploratória: 7 perguntas, 7 gráficos |
| `notebooks/02_baseline.ipynb` | Problema supervisionado, divisão temporal treino/teste e baselines |
| `notebooks/03_base_proxy_distritos.ipynb` | Inferência Estatística: base proxy de orientação sexual e identidade de gênero por distrito, validada com testes |
| `notebooks/04_modelos.ipynb` | Resultado do modelo: comparação com a persistência e alternativas, limiar, alvo relativo e limites dos dados sintéticos |
| `docs/handoff_ml.md` | O que foi feito no modelo para o SR2, como reproduzir, decisões e pendências |

## Resultado atual do modelo (SR2 · 27/11/2026)

Detalhes em [`notebooks/04_modelos.ipynb`](notebooks/04_modelos.ipynb); números gerados por `python src/modelos.py` com **os mesmos dados, variáveis, limiar e divisão temporal da pipeline**, por isso o F1 é o mesmo da aba *Pipeline* do app. Teste: alvos de 2026.1 e 2026.2 (768 equipes x quadrimestre, 192 críticas).

| Modelo | F1 | Recall | Precisão | F1 na janela móvel |
|---|---|---|---|---|
| Persistência (quem é crítica continua crítica) | 0,833 | 0,833 | 0,833 | 0,830 |
| **Regressão logística (modelo da pipeline)** | **0,852** | **0,885** | 0,821 | **0,844** |
| Random Forest (GridSearch) | 0,851 | 0,891 | 0,814 | 0,838 |
| KNN (GridSearch) | 0,830 | 0,828 | 0,832 | 0,832 |
| Árvore de decisão (GridSearch) | 0,830 | 0,839 | 0,821 | 0,807 |

- **Modelo x persistência:** a regressão logística encontra 170 das 192 equipes que ficaram críticas (a persistência, 160), com 15 alertas a mais. O ganho é pequeno; o valor está em antecipar equipes que ainda não são críticas, o que a persistência nunca faz.
- **Alternativas:** hiperparâmetros por `GridSearchCV` com validação cruzada **temporal** (treina no passado, valida no quadrimestre seguinte). A árvore fica abaixo da persistência; KNN fica no nível dela; a random forest empata com a regressão logística (dentro de 1 desvio padrão na janela móvel). No empate fica o modelo mais simples: **a regressão logística continua na pipeline**.
- **Limiar de 0,5:** na validação temporal, o F1 fica entre 0,81 e 0,82 em todo o intervalo de 0,35 a 0,50, então o resultado não depende de ajuste fino. 0,5 quer dizer "mais provável ficar crítica do que não" e mantém os alertas perto do número real de críticas (207 para 192). Abaixo de 0,35 os alertas crescem rápido (282 em 0,20); acima de 0,55 o recall cai.
- **Alvo relativo (25% piores) x meta absoluta:** com uma meta absoluta (índice abaixo de 50), a fila de críticas iria de 16% para 26% das equipes no período. O painel serve para priorizar um apoio de capacidade fixa por distrito, por isso o alvo é uma ordenação. Limitação assumida: sempre haverá 25% de críticas, mesmo se a rede melhorar; a evolução da rede é medida pelo índice de completude, que é absoluto.
- **Dados sintéticos:** o gerador cria cada equipe com um nível próprio que muda devagar (média da equipe + 0,6 × desvio anterior). A persistência alta (F1 de 0,73 a 0,84, subindo no tempo) vem em boa parte dessa regra. Os números valem para esta base; o que se leva para os dados reais é o método.
- **MLflow:** cada execução de `src/modelos.py` fica registrada no experimento `risco-equipe-critica` (um run por modelo, um por combinação do GridSearch, a decisão na tag `decisao`), com cópia versionada em `notebooks/resultados/mlflow_runs.csv`. A pipeline do app não depende do MLflow: ela registra o F1 de cada execução em `execucao_pipeline`.

```bash
pip install -r requirements-ml.txt
python src/modelos.py                    # compara, grava notebooks/resultados/ e registra no MLflow (./mlflow.db)
mlflow ui --backend-store-uri sqlite:///mlflow.db --host 127.0.0.1 --port 5001
# ou com Docker: docker compose up -d  e  MLFLOW_TRACKING_URI=http://127.0.0.1:5001 python src/modelos.py
```

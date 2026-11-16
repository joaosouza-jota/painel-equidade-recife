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
| `db/migrar_para_neon.sh` | Copia o banco local inteiro para o Neon e confere tabela por tabela |
| `db/migracoes/` | Alterações para bancos criados antes de cada mudança (ex.: `data_entrada`) |
| `app/paginas/banco_de_dados.py` | Interface: consultas com gráficos, tabelas, cadastro de equipes e fichas, importação de arquivo |

`ficha_cadastro.data_envio` é quando a equipe enviou a ficha; `data_entrada` é quando ela entrou no banco (preenchida pelo próprio banco). A aba "Importar arquivo" mostra o histórico de entradas.

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

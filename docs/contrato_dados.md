# Contrato de dados · Painel de Equidade em Saúde do Recife

> **O que é:** a lista exata de tabelas e colunas que o pipeline espera receber.
> **Por que existe:** a Secretaria não liberou os dados reais do PEC. Tudo que vem depois da Estação 1 (limpeza, resumo, modelo, painel) lê **este formato**. Hoje quem o produz é o gerador sintético. No dia em que a Secretaria fizer a extração real neste formato, só a Estação 1 muda.
> **Base de referência:** campos da Ficha de Cadastro Individual do e-SUS APS e a reunião com a Secretaria (01/09/2026). Os nomes das colunas são nossos (padrão `snake_case`), não os nomes internos do PEC.

---

## Visão geral

| Tabela | Uma linha por | Papel |
|---|---|---|
| `territorio_equipes` | equipe de Saúde da Família | O "mapa" do Recife: distrito → unidade → equipe |
| `fichas_cadastro` | ficha de cadastro enviada pelo ACS | A matéria-prima: cada cadastro novo ou atualização |

**Por que "fichas" e não "pessoas":** no PEC, o ACS envia uma ficha a cada cadastro ou atualização. A qualidade de uma equipe num período se mede **pelas fichas que ela preencheu naquele período**, não pelo estoque acumulado de anos. Isso separa "como a equipe trabalha hoje" de "o que ficou do passado". Para a visão de concentração populacional, usa-se a **ficha mais recente de cada cidadão ativo**.

---

## Tabela 1 · `territorio_equipes`

| Coluna | Tipo | Exemplo | Descrição |
|---|---|---|---|
| `ine` | texto (10 dígitos) | `0001234567` | Identificador Nacional de Equipe. Chave da tabela |
| `nome_equipe` | texto | `ESF Ibura 03` | Nome da equipe |
| `cnes` | texto (7 dígitos) | `0001234` | Código da unidade de saúde no CNES |
| `nome_unidade` | texto | `USF Ibura de Baixo` | Nome da unidade |
| `distrito_sanitario` | inteiro 1 a 8 | `8` | Distrito Sanitário do Recife |
| `bairro` | texto | `Ibura` | Bairro da unidade |
| `latitude`, `longitude` | decimal | `-8.1234`, `-34.9456` | Localização da unidade (CNES). Usada no mapa de concentração |
| `coordenada_origem` | texto | `cnes`, `centro_do_bairro` | O CNES tem coordenadas erradas: USF no mar, fora do Recife e ~20 USF com a mesma coordenada padrão no centro da cidade. A coordenada é aceita se cai no bairro declarado ou em outro bairro do mesmo distrito (divisa); se não, usa-se o centro do bairro, com as USF espalhadas ~250 m para não se sobreporem no mapa |
| `origem` | texto | `cnes` | A **unidade** é real (CNES). As **equipes** são sintéticas, porque a API aberta do CNES não as traz |

## Tabela 2 · `fichas_cadastro`

### Identificação e tempo
| Coluna | Tipo | Valores | Descrição |
|---|---|---|---|
| `id_ficha` | inteiro | | Chave da tabela |
| `id_cidadao` | texto | `c0000001` | **Pseudônimo.** Nunca nome, CPF ou CNS |
| `ine` | texto | | Equipe que enviou a ficha (liga com a Tabela 1) |
| `data_ficha` | data | `2026-03-14` | Data de envio da ficha |
| `tipo_ficha` | texto | `novo`, `atualizacao` | Primeiro cadastro ou atualização |
| `situacao` | texto | `ativo`, `mudou_se`, `obito` | Situação do cadastro após esta ficha |

### Perfil
| Coluna | Tipo | Valores | Descrição |
|---|---|---|---|
| `idade` | inteiro | 0 a 110 | Idade na data da ficha (a extração real traria a data de nascimento; guardamos só a idade) |
| `sexo` | texto | `F`, `M` | Sexo informado no cadastro |
| `nome_social` | booleano | | Se o campo nome social foi preenchido (o nome em si **não** é guardado) |

### Marcadores de equidade

Cada marcador pode estar em um de **três estados**, e a diferença entre eles é o centro do projeto:

| Estado | Significa | Responsabilidade |
|---|---|---|
| **preenchido** | A pergunta foi feita e respondida | |
| **recusou** | A pessoa disse que **não deseja informar** | Escolha da pessoa |
| **não perguntado** | Campo vazio | **Falha da equipe** |

| Coluna | Tipo | Valores | Observação |
|---|---|---|---|
| `raca_cor` | texto | `branca`, `preta`, `parda`, `amarela`, `indigena`, vazio | Padrão IBGE. Obrigatório no PEC, então o problema principal é **inconsistência** (valor errado), não campo vazio |
| `tem_deficiencia` | texto | `sim`, `nao`, vazio | Obrigatório no PEC |
| `tipo_deficiencia` | texto | `auditiva`, `visual`, `intelectual`, `fisica`, `outra`, vazio | Só quando `tem_deficiencia = sim`. Se houver mais de uma, separadas por `;` |
| `deseja_informar_os` | texto | `sim`, `nao`, vazio | **"Deseja informar orientação sexual?"** `nao` = recusou · vazio = não perguntado |
| `orientacao_sexual` | texto | `heterossexual`, `gay`, `lesbica`, `bissexual`, `assexual`, `pansexual`, `outra`, vazio | Só quando `deseja_informar_os = sim` |
| `deseja_informar_ig` | texto | `sim`, `nao`, vazio | **"Deseja informar identidade de gênero?"** Mesma lógica |
| `identidade_genero` | texto | `mulher_cis`, `homem_cis`, `mulher_trans`, `homem_trans`, `travesti`, `nao_binario`, `outra`, vazio | Só quando `deseja_informar_ig = sim` |

---

## Regras de negócio (vêm da reunião de 01/09)

1. **Crianças de 0 a 10 anos** ficam fora da análise de orientação sexual e identidade de gênero (decisão de gestão da Secretaria).
2. **Escopo:** só Atenção Básica. Serviço de Atenção Domiciliar e ambulatórios ficam fora.
3. **Nenhum dado individual aparece no painel.** Tudo é agregado por equipe, unidade ou distrito.

## Como a qualidade vira número (usado nas Estações 3 e 4)

**Índice de completude da equipe no período (0 a 100):** média ponderada da % de fichas com cada marcador **preenchido**.

| Marcador | Peso | Por quê |
|---|---|---|
| Raça/cor | 1 | Obrigatório, costuma estar preenchido |
| Deficiência | 1 | Obrigatório, costuma estar preenchido |
| Orientação sexual | 2 | Onde está o problema, segundo a cliente |
| Identidade de gênero | 2 | Idem |

**Equipe crítica:** índice entre os **25% piores** do quadrimestre. **Alvo do modelo:** a equipe vai estar crítica **no quadrimestre seguinte**?

**Período:** quadrimestre (jan-abr, mai-ago, set-dez). A cliente disse que acompanhamento a cada 4 meses basta.

---

## Parâmetros da base sintética

> Gerada por `src/gerar_sintetico.py` (semente fixa 42: rodar de novo gera exatamente a mesma base).
> **[real]** = fonte pública ou reunião com a cliente · **[hipótese]** = decisão nossa, a validar com dado real.

### Território
| Parâmetro | Valor | Fonte |
|---|---|---|
| Unidades de Saúde da Família | **142** USF ativas, gestão municipal | [real] API de dados abertos do CNES (Ministério da Saúde). Bate com as 141 do briefing |
| Bairro de cada USF | endereço no CNES | [real] CNES |
| Distrito Sanitário | 8, pelo mapa oficial de bairros (RPA + microrregião) | [real] Dados Abertos do Recife, "Limites dos Bairros 2023". A divisão RPA 3 → DS 3/7 e RPA 6 → DS 6/8 é [inferência], coerente com a fala da cliente (DS 8 = Ibura e Jordão) |
| Equipes | **384**, de 2 a 8 por USF | [real] total do briefing · [hipótese] distribuição entre as USF (a CNES aberta não traz as equipes) |

### População
| Parâmetro | Valor | Fonte |
|---|---|---|
| Pessoas por equipe | 2.000 a 3.800 (média 2.900), simuladas a 25% (`ESCALA`) | [hipótese] faixa da PNAB 2017 |
| Idade | distribuição ano a ano do Recife | [real] IBGE, Censo 2022, tabela 9514 |
| Raça/cor | parda 48,5% · branca 38,8% · preta 12,3% · amarela 0,2% · indígena 0,2% | [real] IBGE, Censo 2022, tabela 9605 |
| Variação de raça/cor por distrito | DS 2, 5, 7 e 8 mais negros; DS 3 e 6 mais brancos | [hipótese] coerente com a fala da cliente sobre os morros da zona norte |
| Deficiência | 8,4% das pessoas com 2 anos ou mais, taxa crescente com a idade | [real] IBGE, Censo 2022, tabela 10131 |
| Tipo de deficiência | visual 58% · física ~45% · intelectual 19% · auditiva 17% (entre pessoas com deficiência, pode haver mais de um) | [real] IBGE, Censo 2022, tabela 10127 |
| Orientação sexual | 1,2% homossexual · 0,7% bissexual · 0,2% outras | [real] IBGE, Pesquisa Nacional de Saúde 2019 |
| Identidade de gênero | 0,69% trans · 1,19% não binário | [real] Spizzirri et al., *Scientific Reports*, 2021 |

### Comportamento das equipes (o que o modelo tenta prever)
| Parâmetro | Valor | Fonte |
|---|---|---|
| % que deseja informar orientação sexual | **~38%** (≈ 58% das pessoas são perguntadas × 65% aceitam) | [real] reunião 01/09 · [hipótese] a divisão entre "perguntou" e "aceitou" |
| Evolução da equipe | nível próprio + tendência + memória de 60% do período anterior + ruído | [hipótese] |
| Erro de raça/cor | ~6% das fichas, trocando por categoria vizinha (preta ↔ parda ↔ branca) | [hipótese] |
| Equipes com erro sistemático de raça/cor | ~5%, com 30 a 50% das fichas marcadas como branca (ou amarela) | [hipótese] os dois exemplos da cliente |
| Deficiência não identificada | ~10% das pessoas com deficiência registradas como "não" | [hipótese] |
| Fichas por quadrimestre | 30% das pessoas ativas + todas as saídas | [hipótese] |
| Saídas por quadrimestre | 2,5% mudança de território · 0,25% óbito, repostas por novos moradores | [hipótese] |

### Arquivos gerados em `data/raw/`
| Arquivo | Conteúdo |
|---|---|
| `territorio_equipes.csv` | Tabela 1 |
| `fichas_cadastro.parquet` | Tabela 2 (~770 mil fichas) |
| `_verdade_equipes.parquet` | **Gabarito escondido**: o comportamento real de cada equipe. Não entra no modelo, serve só para conferir o gerador |
| `_verdade_populacao.parquet` | **Gabarito escondido**: o perfil real de cada pessoa, antes dos erros de registro |

## Pontos a conferir quando houver dado real
- Os valores exatos das listas de orientação sexual e identidade de gênero na versão do PEC em uso no Recife.
- Se registros antigos/migrados trazem raça/cor e deficiência vazios apesar de serem obrigatórios hoje. `[inferência]`
- ~~141 USF (briefing) × "mais de 200 unidades" (fala da cliente)~~ O CNES confirma 142 USF. As "mais de 200" provavelmente incluem outros tipos de unidade.

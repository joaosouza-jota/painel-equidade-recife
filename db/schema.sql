-- =====================================================================
-- Painel de Equidade em Saúde do Recife
-- Esquema do banco (SGBD: PostgreSQL · local ou Neon)
-- Banco de Dados · Etapa 03 · versão ajustada do esquema das Etapas 01 e 02
-- =====================================================================
--
-- Um banco só para o projeto inteiro:
--   - Banco de Dados: as 9 tabelas do modelo lógico + consultas da interface
--   - Inferência Estatística: tabela respostas_sinteticas (notebook 03)
--   - Machine Learning: indicador_equipe.risco_previsto recebe a previsão
--
-- Ajustes em relação à Etapa 02 (a Secretaria enviou o modelo da Ficha de
-- Cadastro Individual do e-SUS APS, versão 5.3):
--
-- 1. SEXO aceita 'I' (Indeterminado), opção que existe na ficha.
-- 2. TEA virou categoria própria de deficiência (na ficha é uma opção ao
--    lado de auditiva, visual, intelectual/cognitiva, física e outra).
-- 3. BAIRRO ganhou populacao_2022 (IBGE, Censo 2022, tabela 9923), para
--    as consultas de concentração por habitante. Agora entram os 94
--    bairros do Recife, não só os que têm USF.
-- 4. N/I (não informado): nos marcadores de equidade, NULL quer dizer que
--    a equipe não registrou a resposta. 'nao' em deseja_informar quer
--    dizer que a pessoa recusou. Só o primeiro é falha da equipe.
-- 5. Nova tabela RESPOSTAS_SINTETICAS (Inferência Estatística).
-- 6. Correção: identidade_genero era VARCHAR(11) e não cabia "mulher_trans"
--    (12 letras). A amostra da Etapa 02 não tinha nenhuma; a base completa tem.
-- 7. Índices em ficha_cadastro (equipe, data, cidadão): a base completa tem
--    ~770 mil fichas e as consultas filtram e juntam por essas colunas.
-- 8. ficha_cadastro.data_entrada: quando a ficha ENTROU no banco (carga,
--    importação de arquivo ou cadastro na tela). Diferente de data_envio,
--    que é quando a equipe enviou a ficha. Preenchida pelo próprio banco
--    (DEFAULT now()); todas as fichas de uma importação têm o mesmo valor.
-- =====================================================================

DROP TABLE IF EXISTS log_ficha_cadastro, agenda_apoio, indicador_equipe, quadrimestre,
    ficha_deficiencia, tipo_deficiencia, ficha_cadastro, cidadao, equipe,
    unidade_saude, bairro CASCADE;
DROP SEQUENCE IF EXISTS seq_bairro, seq_tipo_deficiencia,
    seq_ficha_cadastro, seq_quadrimestre;

-- ---------------------------------------------------------------------
-- Sequências (geram as chaves das tabelas sem código natural)
-- ---------------------------------------------------------------------
CREATE SEQUENCE seq_bairro           START 1 INCREMENT 1;
CREATE SEQUENCE seq_tipo_deficiencia START 1 INCREMENT 1;
CREATE SEQUENCE seq_ficha_cadastro   START 1 INCREMENT 1;
CREATE SEQUENCE seq_quadrimestre     START 1 INCREMENT 1;

-- ---------------------------------------------------------------------
-- BAIRRO · bairros do Recife, Distrito Sanitário e população (Censo 2022)
-- ---------------------------------------------------------------------
CREATE TABLE bairro (
    id_bairro       INTEGER      NOT NULL DEFAULT nextval('seq_bairro'),
    nome            VARCHAR(60)  NOT NULL,
    nr_distrito     SMALLINT     NOT NULL,
    populacao_2022  INTEGER,
    CONSTRAINT pk_bairro          PRIMARY KEY (id_bairro),
    CONSTRAINT uq_bairro_nome     UNIQUE (nome),
    CONSTRAINT ck_bairro_distrito CHECK (nr_distrito BETWEEN 1 AND 8),
    CONSTRAINT ck_bairro_pop      CHECK (populacao_2022 >= 0)
);

-- ---------------------------------------------------------------------
-- UNIDADE_SAUDE · Unidades de Saúde da Família (USF)
-- ---------------------------------------------------------------------
CREATE TABLE unidade_saude (
    cnes       CHAR(7)       NOT NULL,
    nome       VARCHAR(100)  NOT NULL,
    latitude   NUMERIC(9,6),
    longitude  NUMERIC(9,6),
    id_bairro  INTEGER       NOT NULL,
    CONSTRAINT pk_unidade_saude PRIMARY KEY (cnes),
    CONSTRAINT ck_unidade_cnes  CHECK (cnes ~ '^[0-9]{7}$'),
    CONSTRAINT ck_unidade_lat   CHECK (latitude  BETWEEN -90  AND 90),
    CONSTRAINT ck_unidade_lon   CHECK (longitude BETWEEN -180 AND 180),
    CONSTRAINT fk_unidade_bairro FOREIGN KEY (id_bairro)
        REFERENCES bairro (id_bairro)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ---------------------------------------------------------------------
-- EQUIPE · Equipes de Saúde da Família
-- ON UPDATE CASCADE: se o CNES da unidade for recodificado, as equipes
-- acompanham a mudança automaticamente.
-- ---------------------------------------------------------------------
CREATE TABLE equipe (
    ine   CHAR(10)      NOT NULL,
    nome  VARCHAR(100)  NOT NULL,
    cnes  CHAR(7)       NOT NULL,
    CONSTRAINT pk_equipe      PRIMARY KEY (ine),
    CONSTRAINT uq_equipe_nome UNIQUE (nome),
    CONSTRAINT ck_equipe_ine  CHECK (ine ~ '^[0-9]{10}$'),
    CONSTRAINT fk_equipe_unidade FOREIGN KEY (cnes)
        REFERENCES unidade_saude (cnes)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ---------------------------------------------------------------------
-- CIDADAO · pessoas cadastradas, só por código pseudônimo
-- (nome, CPF e CNS nunca são guardados)
-- ---------------------------------------------------------------------
CREATE TABLE cidadao (
    cod_cidadao  VARCHAR(10)  NOT NULL,
    CONSTRAINT pk_cidadao     PRIMARY KEY (cod_cidadao),
    CONSTRAINT ck_cidadao_cod CHECK (cod_cidadao ~ '^c[0-9]{7}$')
);

-- ---------------------------------------------------------------------
-- FICHA_CADASTRO · fichas enviadas pelas equipes
-- ON DELETE SET NULL: excluir a equipe não apaga as fichas dela.
-- Marcadores de equidade: NULL = N/I (a equipe não registrou);
-- deseja_informar = 'nao' = a pessoa recusou.
-- ---------------------------------------------------------------------
CREATE TABLE ficha_cadastro (
    id_ficha            BIGINT       NOT NULL DEFAULT nextval('seq_ficha_cadastro'),
    data_envio          DATE         NOT NULL DEFAULT CURRENT_DATE,
    tipo_ficha          VARCHAR(11)  NOT NULL DEFAULT 'novo',
    situacao            VARCHAR(8)   NOT NULL DEFAULT 'ativo',
    idade               SMALLINT     NOT NULL,
    sexo                CHAR(1)      NOT NULL,
    usa_nome_social     BOOLEAN      NOT NULL DEFAULT FALSE,
    raca_cor            VARCHAR(8),
    tem_deficiencia     VARCHAR(3),
    deseja_informar_os  VARCHAR(3),
    orientacao_sexual   VARCHAR(13),
    deseja_informar_ig  VARCHAR(3),
    identidade_genero   VARCHAR(12),
    ine                 CHAR(10),
    cod_cidadao         VARCHAR(10)  NOT NULL,
    data_entrada        TIMESTAMPTZ  NOT NULL DEFAULT now(),
    CONSTRAINT pk_ficha_cadastro PRIMARY KEY (id_ficha),
    CONSTRAINT ck_ficha_tipo     CHECK (tipo_ficha IN ('novo', 'atualizacao')),
    CONSTRAINT ck_ficha_situacao CHECK (situacao IN ('ativo', 'mudou_se', 'obito')),
    CONSTRAINT ck_ficha_idade    CHECK (idade BETWEEN 0 AND 110),
    CONSTRAINT ck_ficha_sexo     CHECK (sexo IN ('F', 'M', 'I')),
    CONSTRAINT ck_ficha_raca     CHECK (raca_cor IN ('branca', 'preta', 'parda', 'amarela', 'indigena')),
    CONSTRAINT ck_ficha_def      CHECK (tem_deficiencia IN ('sim', 'nao')),
    CONSTRAINT ck_ficha_des_os   CHECK (deseja_informar_os IN ('sim', 'nao')),
    CONSTRAINT ck_ficha_des_ig   CHECK (deseja_informar_ig IN ('sim', 'nao')),
    CONSTRAINT ck_ficha_os       CHECK (orientacao_sexual IN ('heterossexual', 'gay', 'lesbica',
                                        'bissexual', 'assexual', 'pansexual', 'outra')),
    CONSTRAINT ck_ficha_ig       CHECK (identidade_genero IN ('mulher_cis', 'homem_cis', 'mulher_trans',
                                        'homem_trans', 'travesti', 'nao_binario', 'outra')),
    -- orientação/identidade só existem se a pessoa quis informar
    CONSTRAINT ck_ficha_os_resp  CHECK ((COALESCE(deseja_informar_os, 'nao') = 'sim') = (orientacao_sexual IS NOT NULL)),
    CONSTRAINT ck_ficha_ig_resp  CHECK ((COALESCE(deseja_informar_ig, 'nao') = 'sim') = (identidade_genero IS NOT NULL)),
    -- crianças de 0 a 10 anos ficam fora de orientação sexual e identidade de gênero
    CONSTRAINT ck_ficha_crianca  CHECK (idade > 10 OR (deseja_informar_os IS NULL
                                        AND deseja_informar_ig IS NULL)),
    CONSTRAINT fk_ficha_equipe FOREIGN KEY (ine)
        REFERENCES equipe (ine)
        ON UPDATE CASCADE ON DELETE SET NULL,
    CONSTRAINT fk_ficha_cidadao FOREIGN KEY (cod_cidadao)
        REFERENCES cidadao (cod_cidadao)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- Índices: ficha_cadastro tem ~770 mil linhas e as consultas filtram e
-- juntam por equipe, data de envio e cidadão.
CREATE INDEX ix_ficha_ine     ON ficha_cadastro (ine);
CREATE INDEX ix_ficha_data    ON ficha_cadastro (data_envio);
CREATE INDEX ix_ficha_cidadao ON ficha_cadastro (cod_cidadao, data_envio DESC);

-- ---------------------------------------------------------------------
-- TIPO_DEFICIENCIA · tipos de deficiência e a categoria da ficha e-SUS
-- ---------------------------------------------------------------------
CREATE TABLE tipo_deficiencia (
    id_tipo_deficiencia  SMALLINT     NOT NULL DEFAULT nextval('seq_tipo_deficiencia'),
    descricao            VARCHAR(60)  NOT NULL,
    categoria            VARCHAR(11)  NOT NULL,
    CONSTRAINT pk_tipo_deficiencia PRIMARY KEY (id_tipo_deficiencia),
    CONSTRAINT uq_tipo_def_desc    UNIQUE (descricao),
    CONSTRAINT ck_tipo_def_cat     CHECK (categoria IN ('auditiva', 'visual', 'intelectual',
                                          'fisica', 'tea', 'outra'))
);

-- ---------------------------------------------------------------------
-- FICHA_DEFICIENCIA · tipos de deficiência indicados em cada ficha (N:N)
-- Apagar a ficha apaga as indicações dela (ON DELETE CASCADE).
-- ---------------------------------------------------------------------
CREATE TABLE ficha_deficiencia (
    id_ficha             BIGINT    NOT NULL,
    id_tipo_deficiencia  SMALLINT  NOT NULL,
    CONSTRAINT pk_ficha_deficiencia PRIMARY KEY (id_ficha, id_tipo_deficiencia),
    CONSTRAINT fk_fd_ficha FOREIGN KEY (id_ficha)
        REFERENCES ficha_cadastro (id_ficha)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_fd_tipo FOREIGN KEY (id_tipo_deficiencia)
        REFERENCES tipo_deficiencia (id_tipo_deficiencia)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ---------------------------------------------------------------------
-- QUADRIMESTRE · períodos de avaliação
-- ---------------------------------------------------------------------
CREATE TABLE quadrimestre (
    id_quadrimestre  INTEGER   NOT NULL DEFAULT nextval('seq_quadrimestre'),
    ano              SMALLINT  NOT NULL,
    numero           SMALLINT  NOT NULL,
    data_inicio      DATE      NOT NULL,
    data_fim         DATE      NOT NULL,
    CONSTRAINT pk_quadrimestre     PRIMARY KEY (id_quadrimestre),
    CONSTRAINT uq_quadrimestre     UNIQUE (ano, numero),
    CONSTRAINT ck_quad_numero      CHECK (numero BETWEEN 1 AND 3),
    CONSTRAINT ck_quad_datas       CHECK (data_fim > data_inicio),
    CONSTRAINT ck_quad_ano         CHECK (EXTRACT(YEAR FROM data_inicio) = ano)
);

-- ---------------------------------------------------------------------
-- INDICADOR_EQUIPE · indicador de cada equipe por quadrimestre
-- ON UPDATE CASCADE: acompanha a recodificação do INE da equipe.
-- ---------------------------------------------------------------------
CREATE TABLE indicador_equipe (
    ine                CHAR(10)      NOT NULL,
    id_quadrimestre    INTEGER       NOT NULL,
    qtd_fichas         INTEGER       NOT NULL DEFAULT 0,
    indice_completude  NUMERIC(5,2)  NOT NULL,
    critica            BOOLEAN       NOT NULL DEFAULT FALSE,
    risco_previsto     NUMERIC(5,4),
    CONSTRAINT pk_indicador_equipe PRIMARY KEY (ine, id_quadrimestre),
    CONSTRAINT ck_ind_qtd          CHECK (qtd_fichas >= 0),
    CONSTRAINT ck_ind_completude   CHECK (indice_completude BETWEEN 0 AND 100),
    CONSTRAINT ck_ind_risco        CHECK (risco_previsto BETWEEN 0 AND 1),
    CONSTRAINT fk_ind_equipe FOREIGN KEY (ine)
        REFERENCES equipe (ine)
        ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_ind_quadrimestre FOREIGN KEY (id_quadrimestre)
        REFERENCES quadrimestre (id_quadrimestre)
        ON UPDATE CASCADE ON DELETE RESTRICT
);

-- ---------------------------------------------------------------------
-- RESPOSTAS_SINTETICAS · base proxy da Inferência Estatística
-- Respostas fictícias de orientação sexual e identidade de gênero,
-- sorteadas por Distrito Sanitário (notebooks/03_base_proxy_distritos).
-- SINTÉTICA: serve para testar sistema e painel, nunca para afirmar
-- algo sobre a população do Recife. IF NOT EXISTS: recarregar o banco
-- não apaga o que o notebook gravou.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS respostas_sinteticas (
    id_resposta                BIGSERIAL     NOT NULL,
    nr_distrito                SMALLINT      NOT NULL,
    semente                    INTEGER       NOT NULL,
    informa_orientacao_sexual  VARCHAR(3)    NOT NULL,
    orientacao_sexual          VARCHAR(13),
    informa_identidade_genero  VARCHAR(3)    NOT NULL,
    identidade_genero          VARCHAR(20),
    CONSTRAINT pk_respostas_sinteticas PRIMARY KEY (id_resposta),
    CONSTRAINT ck_resp_distrito  CHECK (nr_distrito BETWEEN 1 AND 8),
    CONSTRAINT ck_resp_inf_os    CHECK (informa_orientacao_sexual IN ('Sim', 'Não')),
    CONSTRAINT ck_resp_inf_ig    CHECK (informa_identidade_genero IN ('Sim', 'Não')),
    -- regra do formulário: Sim <=> campo preenchido
    CONSTRAINT ck_resp_os_regra  CHECK ((informa_orientacao_sexual = 'Sim') = (orientacao_sexual IS NOT NULL)),
    CONSTRAINT ck_resp_ig_regra  CHECK ((informa_identidade_genero = 'Sim') = (identidade_genero IS NOT NULL))
);

-- =====================================================================
-- Etapa 04 · índices e visões
-- (o comentário completo de cada um está em
--  entregas/extra_minimundo-banco-de-dados/etapa-04/)
-- =====================================================================

-- Índice parcial: só fichas de pessoas trans, travestis e não binárias
-- (~0,6% da tabela). Consulta de equipes que nunca registram esse grupo.
CREATE INDEX ix_ficha_genero_diverso
    ON ficha_cadastro (ine, data_envio)
    WHERE identidade_genero IN ('mulher_trans', 'homem_trans', 'travesti', 'nao_binario');

-- Caminho inverso da PK de ficha_deficiencia ("quais fichas têm este tipo")
-- e checagem da FK ao excluir um tipo.
CREATE INDEX ix_fd_tipo ON ficha_deficiencia (id_tipo_deficiencia);

-- Visão 1: indicador da equipe já situado no território
CREATE OR REPLACE VIEW vw_indicador_territorio AS
SELECT i.ine,
       e.nome                    AS equipe,
       u.cnes,
       u.nome                    AS unidade,
       b.nome                    AS bairro,
       b.nr_distrito             AS distrito,
       q.id_quadrimestre,
       q.ano,
       q.numero,
       q.ano || '.' || q.numero  AS quadrimestre,
       i.qtd_fichas,
       i.indice_completude,
       i.critica,
       i.risco_previsto
FROM indicador_equipe i
JOIN quadrimestre  q ON q.id_quadrimestre = i.id_quadrimestre
JOIN equipe        e ON e.ine = i.ine
JOIN unidade_saude u ON u.cnes = e.cnes
JOIN bairro        b ON b.id_bairro = u.id_bairro;

-- Visão 2: cada ficha com o estado de cada marcador (Preenchido / Recusou / N/I)
CREATE OR REPLACE VIEW vw_ficha_marcadores AS
SELECT f.id_ficha,
       f.cod_cidadao,
       f.data_envio,
       q.ano,
       q.numero,
       q.ano || '.' || q.numero  AS quadrimestre,
       f.tipo_ficha,
       f.situacao,
       f.idade,
       f.sexo,
       f.raca_cor,
       f.orientacao_sexual,
       f.identidade_genero,
       f.tem_deficiencia,
       CASE WHEN f.idade <= 10                   THEN NULL
            WHEN f.deseja_informar_os = 'sim'    THEN 'Preenchido'
            WHEN f.deseja_informar_os = 'nao'    THEN 'Recusou'
            ELSE 'N/I' END                       AS estado_orientacao,
       CASE WHEN f.idade <= 10                   THEN NULL
            WHEN f.deseja_informar_ig = 'sim'    THEN 'Preenchido'
            WHEN f.deseja_informar_ig = 'nao'    THEN 'Recusou'
            ELSE 'N/I' END                       AS estado_identidade,
       CASE WHEN f.raca_cor IS NULL              THEN 'N/I'
            ELSE 'Preenchido' END                AS estado_raca,
       CASE WHEN f.tem_deficiencia IS NULL       THEN 'N/I'
            ELSE 'Preenchido' END                AS estado_deficiencia,
       f.ine,
       e.nome                    AS equipe,
       u.cnes,
       u.nome                    AS unidade,
       b.nome                    AS bairro,
       b.nr_distrito             AS distrito,
       f.data_entrada
FROM ficha_cadastro f
JOIN quadrimestre  q ON f.data_envio BETWEEN q.data_inicio AND q.data_fim
JOIN equipe        e ON e.ine = f.ine
JOIN unidade_saude u ON u.cnes = e.cnes
JOIN bairro        b ON b.id_bairro = u.id_bairro;


-- =====================================================================
-- Etapa 05 · funções, procedimentos e triggers
-- (justificativas completas em entregas/extra_minimundo-banco-de-dados/etapa-05/)
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1 · fn_estado_marcador · estado do registro de um marcador de equidade
-- ---------------------------------------------------------------------
-- Justificativa semântica: o projeto inteiro gira em torno de uma regra
-- de três estados para cada marcador da ficha:
--   Preenchido = a equipe perguntou e registrou a resposta;
--   Recusou    = a equipe perguntou e a pessoa não quis informar;
--   N/I        = a equipe não registrou (falha da equipe, o que o painel mede).
-- Crianças de 0 a 10 anos ficam FORA de orientação sexual e identidade
-- de gênero (a ficha e-SUS não faz essas perguntas para elas): NULL.
-- E a regra muda conforme o marcador: em orientação e identidade a
-- recusa existe (campo deseja_informar = 'nao'); em raça/cor e
-- deficiência não existe recusa, e tem_deficiencia = 'nao' é uma
-- resposta preenchida ("não tem deficiência"), não uma recusa.
-- Errar essa regra num lugar e acertar noutro muda quem aparece como
-- equipe crítica. A função fixa a regra num ponto só do banco.
--
-- Estrutura condicional: IF / ELSIF / ELSE em dois níveis (o marcador e,
-- dentro dele, a idade e a resposta). Marcador desconhecido gera erro,
-- em vez de devolver um estado errado em silêncio.
--
-- IMMUTABLE: a resposta depende só dos parâmetros (mesma entrada, mesma
-- saída), o que deixa o PostgreSQL reaproveitar o resultado.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_estado_marcador(
    p_marcador  TEXT,       -- 'orientacao', 'identidade', 'raca' ou 'deficiencia'
    p_resposta  TEXT,       -- orientação/identidade: deseja_informar ('sim'/'nao'/NULL)
                            -- raça/deficiência: o próprio campo (raca_cor, tem_deficiencia)
    p_idade     INTEGER
)
RETURNS VARCHAR(10)
LANGUAGE plpgsql
IMMUTABLE
AS $$
BEGIN
    IF p_marcador IN ('orientacao', 'identidade') THEN
        IF p_idade <= 10 THEN
            RETURN NULL;                      -- criança: fora do marcador
        ELSIF p_resposta = 'sim' THEN
            RETURN 'Preenchido';
        ELSIF p_resposta = 'nao' THEN
            RETURN 'Recusou';
        ELSE
            RETURN 'N/I';                     -- a equipe não registrou
        END IF;

    ELSIF p_marcador IN ('raca', 'deficiencia') THEN
        IF p_resposta IS NULL THEN
            RETURN 'N/I';
        ELSE
            RETURN 'Preenchido';              -- inclui tem_deficiencia = 'nao'
        END IF;

    ELSE
        RAISE EXCEPTION 'Marcador desconhecido: % (use orientacao, identidade, raca ou deficiencia)', p_marcador;
    END IF;
END;
$$;


-- ---------------------------------------------------------------------
-- 2 · fn_indice_completude · índice de completude de UMA equipe em UM
--     quadrimestre, calculado na hora a partir das fichas
-- ---------------------------------------------------------------------
-- Justificativa semântica: o índice de completude é o número central do
-- painel (0 a 100; quanto maior, mais a equipe registra os marcadores).
-- Ele fica gravado em indicador_equipe.indice_completude, mas o valor
-- gravado é uma FOTO: se uma ficha for corrigida na tela Banco de Dados,
-- a foto fica velha. Esta função responde "quanto a equipe X tem HOJE no
-- quadrimestre Y", direto das fichas, e é usada pelo procedimento que
-- atualiza os indicadores (02_procedimentos.sql).
--
-- Fórmula (a mesma do projeto desde a Etapa 03):
--   índice = 100 × (2·OS + 2·IG + Raça + Deficiência) / 6
--   OS, IG     = fração "Preenchido" entre as pessoas com mais de 10 anos
--                (peso 2: são os marcadores que o projeto quer melhorar)
--   Raça, Def. = fração "Preenchido" entre todas as fichas
-- O estado de cada ficha vem de fn_estado_marcador (função 1): a regra
-- de Preenchido / Recusou / N/I não é reescrita aqui.
--
-- Equipe sem nenhuma pessoa acima de 10 anos no período: OS e IG valem 0
-- (COALESCE). Equipe sem nenhuma ficha no período: devolve NULL.
-- STABLE: lê tabelas, então o resultado só é garantido dentro do mesmo
-- comando.
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_indice_completude(
    p_ine              CHAR(10),
    p_id_quadrimestre  INTEGER
)
RETURNS NUMERIC(5,2)
LANGUAGE sql
STABLE
AS $$
    SELECT ROUND(100 * (
              2 * COALESCE(AVG(CASE WHEN fn_estado_marcador('orientacao', f.deseja_informar_os, f.idade) = 'Preenchido'
                                    THEN 1 ELSE 0 END) FILTER (WHERE f.idade > 10), 0)
            + 2 * COALESCE(AVG(CASE WHEN fn_estado_marcador('identidade', f.deseja_informar_ig, f.idade) = 'Preenchido'
                                    THEN 1 ELSE 0 END) FILTER (WHERE f.idade > 10), 0)
            +     AVG(CASE WHEN fn_estado_marcador('raca', f.raca_cor, f.idade) = 'Preenchido'
                           THEN 1 ELSE 0 END)
            +     AVG(CASE WHEN fn_estado_marcador('deficiencia', f.tem_deficiencia, f.idade) = 'Preenchido'
                           THEN 1 ELSE 0 END)
           ) / 6, 2)
    FROM ficha_cadastro f
    JOIN quadrimestre   q ON f.data_envio BETWEEN q.data_inicio AND q.data_fim
    WHERE f.ine = p_ine
      AND q.id_quadrimestre = p_id_quadrimestre;
$$;


-- ---------------------------------------------------------------------
-- 1 · pr_recalcular_indicadores · ATUALIZAÇÃO de dados
-- ---------------------------------------------------------------------
-- Justificativa semântica: indicador_equipe guarda, por equipe e
-- quadrimestre, a quantidade de fichas, o índice de completude e se a
-- equipe está crítica. Esses valores são calculados das fichas, então
-- ficam desatualizados quando uma ficha do período é corrigida ou
-- excluída na tela Banco de Dados, ou quando chegam fichas atrasadas.
-- O procedimento recalcula um quadrimestre inteiro:
--   1. UPDATE de qtd_fichas e indice_completude das equipes que já têm
--      indicador (índice vindo de fn_indice_completude, função 2);
--   2. INSERT das equipes que passaram a ter fichas no período;
--   3. UPDATE de "critica": a equipe é crítica quando o índice fica no
--      quartil inferior do quadrimestre (≤ percentil 25). Como o P25
--      depende de TODAS as equipes, corrigir uma ficha de uma equipe
--      pode mudar quem é crítica nas outras: por isso o recálculo é do
--      quadrimestre inteiro, e não de uma equipe só.
-- risco_previsto não é tocado: quem grava o risco é o modelo de ML
-- (pipeline do projeto).
--
-- Uso:  CALL pr_recalcular_indicadores(2026, 2);
-- ---------------------------------------------------------------------
CREATE OR REPLACE PROCEDURE pr_recalcular_indicadores(p_ano INTEGER, p_numero INTEGER)
LANGUAGE plpgsql
AS $$
DECLARE
    v_quad         quadrimestre%ROWTYPE;
    v_atualizadas  INTEGER;
    v_novas        INTEGER;
    v_criticas     INTEGER;
BEGIN
    SELECT * INTO v_quad FROM quadrimestre WHERE ano = p_ano AND numero = p_numero;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Quadrimestre %.% não está cadastrado', p_ano, p_numero;
    END IF;

    -- 1. equipes que já tinham indicador no quadrimestre
    UPDATE indicador_equipe i
       SET qtd_fichas        = c.qtd,
           indice_completude = fn_indice_completude(i.ine, v_quad.id_quadrimestre)
      FROM (SELECT f.ine, COUNT(*) AS qtd
              FROM ficha_cadastro f
             WHERE f.data_envio BETWEEN v_quad.data_inicio AND v_quad.data_fim
               AND f.ine IS NOT NULL
             GROUP BY f.ine) c
     WHERE i.ine = c.ine
       AND i.id_quadrimestre = v_quad.id_quadrimestre;
    GET DIAGNOSTICS v_atualizadas = ROW_COUNT;

    -- 2. equipes que passaram a ter fichas no período
    INSERT INTO indicador_equipe (ine, id_quadrimestre, qtd_fichas, indice_completude)
    SELECT c.ine, v_quad.id_quadrimestre, c.qtd, fn_indice_completude(c.ine, v_quad.id_quadrimestre)
      FROM (SELECT f.ine, COUNT(*) AS qtd
              FROM ficha_cadastro f
             WHERE f.data_envio BETWEEN v_quad.data_inicio AND v_quad.data_fim
               AND f.ine IS NOT NULL
             GROUP BY f.ine) c
     WHERE NOT EXISTS (SELECT 1 FROM indicador_equipe i
                        WHERE i.ine = c.ine AND i.id_quadrimestre = v_quad.id_quadrimestre);
    GET DIAGNOSTICS v_novas = ROW_COUNT;

    -- 3. quem está crítica (quartil inferior do quadrimestre)
    UPDATE indicador_equipe i
       SET critica = (i.indice_completude <= l.limite)
      FROM (SELECT PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY indice_completude) AS limite
              FROM indicador_equipe
             WHERE id_quadrimestre = v_quad.id_quadrimestre) l
     WHERE i.id_quadrimestre = v_quad.id_quadrimestre;

    SELECT COUNT(*) FILTER (WHERE critica) INTO v_criticas
      FROM indicador_equipe WHERE id_quadrimestre = v_quad.id_quadrimestre;

    RAISE NOTICE 'Quadrimestre %.%: % indicadores atualizados, % novos, % equipes críticas',
                 p_ano, p_numero, v_atualizadas, v_novas, v_criticas;
END;
$$;


-- ---------------------------------------------------------------------
-- 2 · pr_agendar_apoio · procedimento com CURSOR
-- ---------------------------------------------------------------------
-- Justificativa semântica: o painel aponta as equipes com risco de ficar
-- críticas no próximo quadrimestre (risco_previsto ≥ 0,5, gravado pelo
-- modelo de ML). A ação da gestão sobre elas é o APOIO INSTITUCIONAL:
-- o apoiador do Distrito Sanitário senta com a equipe para rever como
-- ela pergunta e registra os marcadores. Cada apoiador tem um número
-- fixo de horas por semana (padrão: 20 h). O procedimento monta a agenda
-- do próximo quadrimestre:
--   - equipes em ordem de prioridade (maior risco primeiro);
--   - horas de apoio conforme a gravidade (índice < 40 → 8 h;
--     < 45 → 6 h; o resto → 4 h);
--   - cada equipe vai para a PRIMEIRA semana do seu distrito que ainda
--     tem horas livres suficientes (first-fit). Uma equipe de 4 h pode
--     ocupar a sobra de uma semana anterior que não coube uma de 8 h.
--
-- Por que precisa de cursor (e não dá para fazer com um UPDATE ou um
-- INSERT ... SELECT):
--   A semana de cada equipe depende das horas JÁ OCUPADAS pelas equipes
--   que vieram antes dela, e essa ocupação só existe depois que as
--   equipes anteriores foram colocadas. É um processo sequencial: a
--   decisão da linha N depende do resultado das linhas 1 a N-1.
--   Um único UPDATE/INSERT enxerga a tabela como ela estava ANTES do
--   comando (o PostgreSQL lê de uma "foto" do início do comando), então
--   não consegue ver as próprias colocações. Contar a posição com
--   ROW_NUMBER também não resolve, porque as equipes têm tamanhos
--   diferentes (4, 6 ou 8 h) e a ordem de chegada muda o encaixe.
--   O cursor percorre as equipes uma a uma, na ordem de prioridade, e a
--   cada FETCH consulta a agenda já montada.
--
-- Rodar de novo para o mesmo quadrimestre refaz a agenda do zero (o
-- risco pode ter mudado depois de uma nova execução da pipeline).
--
-- Uso:  CALL pr_agendar_apoio(2026, 2);        -- 20 h por semana
--       CALL pr_agendar_apoio(2026, 2, 16);    -- 16 h por semana
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agenda_apoio (
    id_agenda        SERIAL        NOT NULL,
    id_quadrimestre  INTEGER       NOT NULL,       -- quadrimestre cujo risco gerou a agenda
    ine              CHAR(10)      NOT NULL,
    nr_distrito      SMALLINT      NOT NULL,
    semana           SMALLINT      NOT NULL,       -- 1 = primeira semana do quadrimestre seguinte
    inicio_semana    DATE          NOT NULL,
    horas            SMALLINT      NOT NULL,
    risco_previsto   NUMERIC(5,4)  NOT NULL,
    criado_em        TIMESTAMPTZ   NOT NULL DEFAULT now(),
    CONSTRAINT pk_agenda_apoio    PRIMARY KEY (id_agenda),
    CONSTRAINT uq_agenda_equipe   UNIQUE (id_quadrimestre, ine),
    CONSTRAINT ck_agenda_semana   CHECK (semana >= 1),
    CONSTRAINT ck_agenda_horas    CHECK (horas IN (4, 6, 8)),
    CONSTRAINT fk_agenda_quad     FOREIGN KEY (id_quadrimestre)
        REFERENCES quadrimestre (id_quadrimestre) ON UPDATE CASCADE ON DELETE CASCADE,
    CONSTRAINT fk_agenda_equipe   FOREIGN KEY (ine)
        REFERENCES equipe (ine) ON UPDATE CASCADE ON DELETE CASCADE
);

CREATE OR REPLACE PROCEDURE pr_agendar_apoio(p_ano INTEGER, p_numero INTEGER, p_horas_semana INTEGER DEFAULT 20)
LANGUAGE plpgsql
AS $$
DECLARE
    v_quad      quadrimestre%ROWTYPE;
    v_inicio    DATE;            -- primeira segunda-feira do quadrimestre seguinte
    v_horas     SMALLINT;
    v_semana    INTEGER;
    v_total     INTEGER := 0;
    r           RECORD;

    -- equipes em risco, da mais urgente para a menos urgente
    c_equipes CURSOR (p_id INTEGER) FOR
        SELECT i.ine, b.nr_distrito, i.indice_completude, i.risco_previsto
          FROM indicador_equipe i
          JOIN equipe        e ON e.ine = i.ine
          JOIN unidade_saude u ON u.cnes = e.cnes
          JOIN bairro        b ON b.id_bairro = u.id_bairro
         WHERE i.id_quadrimestre = p_id
           AND i.risco_previsto >= 0.5
         ORDER BY i.risco_previsto DESC, i.indice_completude, i.ine;
BEGIN
    IF p_horas_semana < 8 THEN
        RAISE EXCEPTION 'O apoiador precisa de pelo menos 8 h por semana (a maior carga de uma equipe)';
    END IF;

    SELECT * INTO v_quad FROM quadrimestre WHERE ano = p_ano AND numero = p_numero;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Quadrimestre %.% não está cadastrado', p_ano, p_numero;
    END IF;
    v_inicio := date_trunc('week', v_quad.data_fim + 7)::date;   -- 1ª segunda-feira depois do fim

    DELETE FROM agenda_apoio WHERE id_quadrimestre = v_quad.id_quadrimestre;   -- refaz do zero

    OPEN c_equipes(v_quad.id_quadrimestre);
    LOOP
        FETCH c_equipes INTO r;
        EXIT WHEN NOT FOUND;

        v_horas := CASE WHEN r.indice_completude < 40 THEN 8
                        WHEN r.indice_completude < 45 THEN 6
                        ELSE 4 END;

        -- first-fit: primeira semana do distrito em que a equipe ainda cabe,
        -- olhando a agenda que as equipes anteriores do cursor já ocuparam
        SELECT MIN(s.semana) INTO v_semana
          FROM generate_series(1, (SELECT COALESCE(MAX(a.semana), 0) + 1
                                     FROM agenda_apoio a
                                    WHERE a.id_quadrimestre = v_quad.id_quadrimestre
                                      AND a.nr_distrito = r.nr_distrito)) AS s(semana)
         WHERE (SELECT COALESCE(SUM(a.horas), 0)
                  FROM agenda_apoio a
                 WHERE a.id_quadrimestre = v_quad.id_quadrimestre
                   AND a.nr_distrito = r.nr_distrito
                   AND a.semana = s.semana) + v_horas <= p_horas_semana;

        INSERT INTO agenda_apoio (id_quadrimestre, ine, nr_distrito, semana, inicio_semana, horas, risco_previsto)
        VALUES (v_quad.id_quadrimestre, r.ine, r.nr_distrito, v_semana,
                v_inicio + 7 * (v_semana - 1), v_horas, r.risco_previsto);
        v_total := v_total + 1;
    END LOOP;
    CLOSE c_equipes;

    RAISE NOTICE 'Agenda de apoio após %.%: % equipes, até a semana %',
                 p_ano, p_numero, v_total,
                 (SELECT MAX(semana) FROM agenda_apoio WHERE id_quadrimestre = v_quad.id_quadrimestre);
END;
$$;
--
-- Os dois triggers ficam em ficha_cadastro porque a tela Banco de Dados
-- do painel deixa ALTERAR os marcadores de uma ficha e EXCLUIR uma ficha
-- (app/paginas/banco_de_dados.py). São as duas operações que precisam
-- de controle.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1 · trg_ficha_log · tabela de LOG das alterações e exclusões de fichas
-- ---------------------------------------------------------------------
-- Justificativa semântica: a ficha guarda dado pessoal SENSÍVEL
-- (orientação sexual, identidade de gênero, raça/cor, deficiência). A
-- LGPD (art. 37) pede registro das operações de tratamento desse dado,
-- e a Secretaria precisa saber quem mudou o quê e quando: uma correção
-- muda o índice da equipe e pode tirá-la (ou colocá-la) na lista de
-- críticas. O trigger grava em log_ficha_cadastro, para cada UPDATE ou
-- DELETE de ficha:
--   - quando e qual usuário do banco fez a operação;
--   - quais campos mudaram (só os que mudaram de fato);
--   - a ficha antes e depois, em JSON. Numa exclusão, o "antes" é o
--     que permite reconstruir a ficha apagada.
-- UPDATE que não muda nada (mesmos valores) não gera linha de log.
-- INSERT não entra: a ficha nova já registra a entrada em data_entrada,
-- e uma importação de milhares de fichas encheria o log sem informação.
-- AFTER: só registra o que de fato foi gravado (se a operação falhar
-- numa restrição, não sobra log de algo que não aconteceu).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS log_ficha_cadastro (
    id_log            BIGSERIAL     NOT NULL,
    momento           TIMESTAMPTZ   NOT NULL DEFAULT now(),
    usuario           TEXT          NOT NULL DEFAULT current_user,
    operacao          VARCHAR(6)    NOT NULL,
    id_ficha          BIGINT        NOT NULL,      -- sem FK: a ficha pode ter sido excluída
    ine               CHAR(10),
    campos_alterados  TEXT[],
    antes             JSONB         NOT NULL,
    depois            JSONB,
    CONSTRAINT pk_log_ficha     PRIMARY KEY (id_log),
    CONSTRAINT ck_log_operacao  CHECK (operacao IN ('UPDATE', 'DELETE'))
);
CREATE INDEX IF NOT EXISTS ix_log_ficha ON log_ficha_cadastro (id_ficha, momento);

CREATE OR REPLACE FUNCTION fn_trg_ficha_log()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_campos TEXT[];
BEGIN
    IF TG_OP = 'UPDATE' THEN
        SELECT array_agg(n.key ORDER BY n.key) INTO v_campos
          FROM jsonb_each(to_jsonb(NEW)) AS n
         WHERE n.value IS DISTINCT FROM to_jsonb(OLD) -> n.key;

        IF v_campos IS NULL THEN
            RETURN NULL;                     -- nada mudou de fato
        END IF;

        INSERT INTO log_ficha_cadastro (operacao, id_ficha, ine, campos_alterados, antes, depois)
        VALUES ('UPDATE', OLD.id_ficha, OLD.ine, v_campos, to_jsonb(OLD), to_jsonb(NEW));
    ELSE
        INSERT INTO log_ficha_cadastro (operacao, id_ficha, ine, antes)
        VALUES ('DELETE', OLD.id_ficha, OLD.ine, to_jsonb(OLD));
    END IF;
    RETURN NULL;                             -- AFTER: o retorno é ignorado
END;
$$;

DROP TRIGGER IF EXISTS trg_ficha_log ON ficha_cadastro;
CREATE TRIGGER trg_ficha_log
    AFTER UPDATE OR DELETE ON ficha_cadastro
    FOR EACH ROW
    EXECUTE FUNCTION fn_trg_ficha_log();


-- ---------------------------------------------------------------------
-- 2 · trg_ficha_sem_deficiencia · coerência entre a ficha e os tipos
--     de deficiência
-- ---------------------------------------------------------------------
-- Justificativa semântica: os tipos de deficiência de uma ficha (surdez,
-- baixa visão, TEA...) ficam em ficha_deficiencia, e só fazem sentido se
-- a ficha diz tem_deficiencia = 'sim'. Na tela Banco de Dados, a equipe
-- pode corrigir uma ficha de 'sim' para 'nao' (marcou errado) ou para
-- vazio. Sem o trigger, os tipos antigos continuariam lá, e a pessoa
-- continuaria sendo contada como surda ou com deficiência física na
-- consulta de demanda de Libras (Etapa 04) e no painel de populações.
--
-- Por que trigger e não CHECK: a regra cruza duas tabelas (o CHECK só
-- enxerga a própria linha) e a FK só garante que a ficha existe, não o
-- que ela diz.
--
-- O trigger dispara só quando tem_deficiencia muda de 'sim' para outra
-- coisa (cláusula WHEN), apaga os tipos que ficaram sem sentido e avisa
-- quantos apagou. A mudança da ficha em si fica registrada pelo
-- trigger 1 (log).
-- ---------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_trg_ficha_sem_deficiencia()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_apagados INTEGER;
BEGIN
    DELETE FROM ficha_deficiencia WHERE id_ficha = NEW.id_ficha;
    GET DIAGNOSTICS v_apagados = ROW_COUNT;
    RAISE NOTICE 'Ficha %: tem_deficiencia deixou de ser "sim"; % tipo(s) de deficiência removido(s)',
                 NEW.id_ficha, v_apagados;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS trg_ficha_sem_deficiencia ON ficha_cadastro;
CREATE TRIGGER trg_ficha_sem_deficiencia
    AFTER UPDATE OF tem_deficiencia ON ficha_cadastro
    FOR EACH ROW
    WHEN (OLD.tem_deficiencia = 'sim' AND NEW.tem_deficiencia IS DISTINCT FROM 'sim')
    EXECUTE FUNCTION fn_trg_ficha_sem_deficiencia();

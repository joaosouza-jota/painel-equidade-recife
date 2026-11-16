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

DROP TABLE IF EXISTS indicador_equipe, quadrimestre,
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

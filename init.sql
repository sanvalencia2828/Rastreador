-- init.sql: Database initialization script for Londrina business data
-- This script creates the necessary tables and indexes for storing CNPJ data

-- Create the main table for establishment data
CREATE TABLE IF NOT EXISTS estabelecimentos (
    id SERIAL PRIMARY KEY,
    cnpj_basico VARCHAR(8),
    cnpj_ordem VARCHAR(4),
    cnpj_dv VARCHAR(2),
    cnpj_completo VARCHAR(14) UNIQUE,
    identificador_matriz_filial INTEGER,
    nome_fantasia VARCHAR(255),
    situacao_cadastral INTEGER,
    data_situacao_cadastral DATE,
    motivo_situacao_cadastral INTEGER,
    nome_cidade_exterior VARCHAR(255),
    codigo_pais INTEGER,
    data_inicio_atividade DATE,
    cnae_fiscal INTEGER,
    cnae_fiscal_descricao TEXT,
    descricao_tipo_logradouro VARCHAR(50),
    logradouro VARCHAR(255),
    numero VARCHAR(20),
    complemento VARCHAR(255),
    bairro VARCHAR(100),
    cep VARCHAR(8),
    uf VARCHAR(2),
    codigo_municipio INTEGER,
    municipio VARCHAR(100),
    ddd_1 VARCHAR(2),
    telefone_1 VARCHAR(15),
    ddd_2 VARCHAR(2),
    telefone_2 VARCHAR(15),
    ddd_fax VARCHAR(2),
    fax VARCHAR(15),
    correio_eletronico VARCHAR(255),
    situacao_especial VARCHAR(100),
    data_situacao_especial DATE,
    latitude DECIMAL(10, 8),
    longitude DECIMAL(11, 8),
    geocoded BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for better query performance
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_cnpj_completo ON estabelecimentos(cnpj_completo);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_municipio ON estabelecimentos(municipio);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_uf ON estabelecimentos(uf);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_cnae_fiscal ON estabelecimentos(cnae_fiscal);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_situacao_cadastral ON estabelecimentos(situacao_cadastral);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_data_inicio_atividade ON estabelecimentos(data_inicio_atividade);
CREATE INDEX IF NOT EXISTS idx_estabelecimentos_geolocation ON estabelecimentos(latitude, longitude);

-- Create a table for storing enriched data about commercial clusters
CREATE TABLE IF NOT EXISTS clusters (
    cluster_id SERIAL PRIMARY KEY,
    center_geom GEOMETRY(POINT, 4326),
    total_lojas INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create a table for heatmap data
CREATE TABLE IF NOT EXISTS heatmap_data (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(POINT, 4326),
    weight INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Create indexes for cluster and heatmap tables
CREATE INDEX IF NOT EXISTS idx_clusters_center_geom ON clusters USING GIST(center_geom);
CREATE INDEX IF NOT EXISTS idx_heatmap_data_geom ON heatmap_data USING GIST(geom);

-- Create a function to update the updated_at timestamp
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Create a trigger to automatically update the updated_at column
CREATE TRIGGER update_estabelecimentos_updated_at
    BEFORE UPDATE ON estabelecimentos
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Insert sample data placeholder (this will be replaced with real data)
-- INSERT INTO estabelecimentos (cnpj_basico, cnpj_ordem, cnpj_dv, cnpj_completo, identificador_matriz_filial, nome_fantasia, situacao_cadastral, data_situacao_cadastral, motivo_situacao_cadastral, nome_cidade_exterior, codigo_pais, data_inicio_atividade, cnae_fiscal, cnae_fiscal_descricao, descricao_tipo_logradouro, logradouro, numero, complemento, bairro, cep, uf, codigo_municipio, municipio, ddd_1, telefone_1, ddd_2, telefone_2, ddd_fax, fax, correio_eletronico, situacao_especial, data_situacao_especial, latitude, longitude)
-- VALUES ('00000000', '0000', '00', '00000000000000', 1, 'Sample Business', 2, '2020-01-01', 0, '', 105, '2020-01-01', 5611800, 'Hotéis e similares', 'Rua', 'Sample Street', '123', '', 'Centro', '86000000', 'PR', 4115706, 'LONDRINA', '43', '30290000', '', '', '', '', '', 'sample@business.com', '', NULL, -23.30000000, -51.15000000);

-- Grant necessary permissions
GRANT ALL PRIVILEGES ON TABLE estabelecimentos TO postgres;
GRANT ALL PRIVILEGES ON TABLE clusters TO postgres;
GRANT ALL PRIVILEGES ON TABLE heatmap_data TO postgres;
GRANT ALL PRIVILEGES ON SEQUENCE estabelecimentos_id_seq TO postgres;
GRANT ALL PRIVILEGES ON SEQUENCE clusters_cluster_id_seq TO postgres;
GRANT ALL PRIVILEGES ON SEQUENCE heatmap_data_id_seq TO postgres;

-- Enable PostGIS extension (should be enabled by the postgis image, but just in case)
CREATE EXTENSION IF NOT EXISTS postgis;

-- Output success message
SELECT 'Database initialization completed successfully' as message;
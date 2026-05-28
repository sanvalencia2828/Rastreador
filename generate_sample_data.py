#!/usr/bin/env python3
"""
Generate sample CNPJ data for testing the ETL scripts
"""

import pandas as pd
import random
from datetime import datetime

# Sample data for testing
SAMPLE_CNAE_CODES = [
    # Retail
    '4711301', '4712100', '4721101', '4722901', '4751201', '4761001', '4771701', '4781400',
    # Gastronomy
    '5611201', '5612100', '5620101',
    # Others (should be filtered out)
    '6201501', '6411100', '8511101'
]

SAMPLE_MUNICIPALITIES = [
    (4113700, 'Londrina'),  # Target city
    (3550308, 'São Paulo'),
    (3304557, 'Rio de Janeiro'),
    (4106902, 'Curitiba')
]

SAMPLE_BUSINESS_NAMES = [
    'Supermercado Central Ltda',
    'Restaurante Sabores do Brasil',
    'Padaria Pão Quente Ltda',
    'Hotéis e Turismo S/A',
    'Consultoria Empresarial ME',
    'Tecnologia da Informação Ltda',
    'Academia Fitness Center',
    'Oficina Mecânica Auto Peças',
    'Clínica Médica Saúde Total',
    'Escola Infantil Sonho Meu'
]

def generate_sample_data(num_records=1000):
    """Generate sample CNPJ data for testing"""

    data = []

    for i in range(num_records):
        # Randomly select municipality (mostly Londrina to ensure we have matches)
        if random.random() < 0.7:  # 70% chance of being Londrina
            cod_municipio, municipio = SAMPLE_MUNICIPALITIES[0]
        else:
            cod_municipio, municipio = random.choice(SAMPLE_MUNICIPALITIES)

        # Randomly select CNAE code
        cnae_code = random.choice(SAMPLE_CNAE_CODES)

        # Randomly select business situation (mostly active)
        if random.random() < 0.8:  # 80% chance of being active
            situacao_cadastral = 2  # Active
        else:
            situacao_cadastral = random.choice([1, 3, 4, 8])  # Other statuses

        # Generate record
        record = {
            'cnpj_basico': f'{random.randint(10000000, 99999999):08d}',
            'cnpj_ordem': f'{random.randint(0, 9999):04d}',
            'cnpj_dv': f'{random.randint(0, 99):02d}',
            'identificador_matriz_filial': random.choice([1, 2]),  # 1=Matriz, 2=Filial
            'nome_fantasia': random.choice(SAMPLE_BUSINESS_NAMES),
            'situacao_cadastral': situacao_cadastral,
            'data_situacao_cadastral': datetime.now().strftime('%Y%m%d'),
            'motivo_situacao_cadastral': '00',
            'nome_cidade_exterior': '',
            'pais': '1058',  # Brazil
            'data_inicio_atividade': '20100101',
            'cnae_fiscal_principal': cnae_code,
            'cnae_fiscal_secundaria': '',
            'tipo_logradouro': 'RUA',
            'logradouro': 'Principal',
            'numero': str(random.randint(1, 2000)),
            'complemento': random.choice(['', 'SALA 101', 'LOJA A', 'BL A']),
            'bairro': 'Centro',
            'cep': f'{random.randint(80000000, 89999999):08d}',
            'uf': 'PR' if cod_municipio == 4113700 else random.choice(['SP', 'RJ', 'RS']),
            'codigo_municipio': cod_municipio,
            'municipio': municipio,
            'ddd_1': '43' if cod_municipio == 4113700 else str(random.randint(11, 99)),
            'telefone_1': f'{random.randint(30000000, 39999999):08d}',
            'ddd_2': '',
            'telefone_2': '',
            'ddd_fax': '',
            'fax': '',
            'correio_eletronico': f'contato{random.randint(1, 1000)}@empresa.com.br',
            'situacao_especial': '',
            'data_situacao_especial': '',
            'porte_empresa': random.choice(['01', '01', '01', '01', '03', '03', '05'])  # ~57% Micro, ~29% Small, ~14% Other
        }

        data.append(record)

    return pd.DataFrame(data)

def main():
    """Generate sample data files"""
    print("Generating sample CNPJ data...")

    # Generate sample data
    df = generate_sample_data(5000)

    # Save as CSV (semicolon separated like the real CNPJ data)
    output_file = 'sample_estabelecimentos.csv'
    df.to_csv(output_file, sep=';', index=False, header=False)

    print(f"Sample data saved to {output_file}")
    print(f"Total records: {len(df)}")

    # Show some statistics
    londrina_count = len(df[df['codigo_municipio'] == 4113700])
    active_count = len(df[df['situacao_cadastral'] == 2])
    retail_gastronomy_count = len(df[df['cnae_fiscal_principal'].isin(SAMPLE_CNAE_CODES[:11])])

    print(f"\nStatistics:")
    print(f"- Londrina businesses: {londrina_count}")
    print(f"- Active businesses: {active_count}")
    print(f"- Retail/Gastronomy businesses: {retail_gastronomy_count}")

if __name__ == "__main__":
    main()
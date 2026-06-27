#!/usr/bin/env python3
"""
Script to clean and validate test CNPJ data
"""

import json


def clean_and_validate_data(records):
    """
    Clean and validate the CNPJ data:
    1. Remove duplicates based on cnpj_basico, cnpj_ordem, cnpj_dv
    2. Handle null values in nome_fantasia
    3. Normalize text fields
    4. Ensure key fields are not empty
    """
    if not records:
        return records, 0

    # 1. Remove duplicates
    seen = set()
    unique_records = []
    duplicates_removed = 0

    for record in records:
        # Create a unique key from the CNPJ components
        key = (
            str(record["cnpj_basico"]).strip(),
            str(record["cnpj_ordem"]).strip(),
            str(record["cnpj_dv"]).strip(),
        )
        if key in seen:
            duplicates_removed += 1
            continue
        seen.add(key)
        unique_records.append(record)

    # 2. Handle null values and normalize text
    cleaned_records = []
    for record in unique_records:
        # Handle nome_fantasia
        if not record["nome_fantasia"] or str(record["nome_fantasia"]).strip() == "":
            record["nome_fantasia"] = "Sin nombre fantasía"
        else:
            # Normalize nome_fantasia
            record["nome_fantasia"] = str(record["nome_fantasia"]).strip()

        # Normalize text fields (strip whitespace)
        text_fields = ["logradouro", "bairro"]
        for field in text_fields:
            if field in record and record[field]:
                record[field] = str(record[field]).strip()

        # Ensure key fields are not empty
        if (
            record.get("municipio")
            and str(record.get("municipio")).strip() != ""
            and record.get("cnae_fiscal_principal")
            and str(record.get("cnae_fiscal_principal")).strip() != ""
        ):
            cleaned_records.append(record)

    return cleaned_records, duplicates_removed


def main():
    # Load test data
    with open("test_data.json", "r", encoding="utf-8") as f:
        all_records = json.load(f)

    print(f"Total registros originales: {len(all_records)}")

    # Data cleaning and validation
    print("Limpiando y validando datos...")
    cleaned_records, duplicates_removed = clean_and_validate_data(all_records)

    # Save cleaned data
    with open("test_data_cleaned.json", "w", encoding="utf-8") as f:
        json.dump(cleaned_records, f, ensure_ascii=False, indent=2)

    print("Registros limpios guardados en test_data_cleaned.json")

    # Print quality report
    print("\n" + "=" * 60)
    print("  REPORTE DE CALIDAD DE DATOS")
    print("=" * 60)
    print(f"  Registros originales:     {len(all_records)}")
    print(f"  Registros duplicados:     {duplicates_removed}")
    print(f"  Registros limpios:        {len(cleaned_records)}")
    print(
        f"  Porcentaje de limpieza:   {((len(all_records) - len(cleaned_records)) / len(all_records) * 100):.2f}%"
        if len(all_records) > 0
        else "  Porcentaje de limpieza:   0%"
    )
    print("=" * 60)

    # Show some examples
    print("\nEjemplos de registros limpios:")
    for i, record in enumerate(cleaned_records[:3]):
        print(f"  {i+1}. nome_fantasia: '{record['nome_fantasia']}'")
        print(f"     logradouro: '{record['logradouro']}'")
        print(f"     bairro: '{record['bairro']}'")
        print()


if __name__ == "__main__":
    main()

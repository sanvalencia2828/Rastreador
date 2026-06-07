import duckdb

REMOTE_GDRIVE_URL = "https://drive.usercontent.google.com/download?id=1SgMhyuMWgBWrrBc5H-Raj_-hJlK8k1y8&confirm=t"

try:
    conn = duckdb.connect()
    conn.execute("INSTALL httpfs;")
    conn.execute("LOAD httpfs;")
    conn.execute(f"ATTACH '{REMOTE_GDRIVE_URL}' AS remote_db (TYPE DUCKDB, READ_ONLY);")
    conn.execute("USE remote_db;")
    
    # Query municipios
    muns = conn.execute("SELECT codigo, descricao FROM municipios WHERE upper(trim(descricao)) IN ('LONDRINA', 'CAMBE', 'IBIPORA', 'APUCARANA', 'JANDAIA DO SUL');").fetchall()
    print("Municipios:", muns)
    
except Exception as e:
    print("Error:", e)



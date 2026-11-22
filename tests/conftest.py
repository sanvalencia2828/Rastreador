import os

# Solo para tests; este valor de desarrollo nunca debe copiarse al código de la app.
if not os.environ.get("JWT_SECRET_KEY"):
    os.environ.setdefault("APP_ENV", "development")

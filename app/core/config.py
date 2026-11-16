"""Environment loading and app-level settings."""

import os


# ==============================================================================
# ENVIRONMENT VARIABLE LOADER (ZERO-DEPENDENCY)
# ==============================================================================
def load_env_file(dotenv_path: str = ".env") -> None:
    """Loads environment variables from a .env file if it exists."""
    if os.path.exists(dotenv_path):
        try:
            with open(dotenv_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        key = key.strip()
                        val = val.strip().strip("'\"")
                        if key not in os.environ:
                            os.environ[key] = val
            print(f"Loaded environment variables from {dotenv_path}")
        except Exception as e:
            print(f"Warning: Could not read {dotenv_path}: {e}")


def load_environment_files() -> None:
    """Loads environment files in a predictable precedence order."""
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    env_files = [".env"]
    if app_env:
        env_files.append(f".env.{app_env}")
    env_files.append(".env.local")

    for env_file in env_files:
        load_env_file(env_file)


load_environment_files()

cors_origins_raw = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3000,http://localhost:3001,http://localhost:8000",
)
cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]

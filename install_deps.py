#!/usr/bin/env python3
"""
Installation script for CNPJ ETL dependencies
"""

import subprocess
import sys


def install_package(package):
    """Install a Python package using pip"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"[INSTALLED] {package}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Failed to install {package}: {e}")
        return False


def main():
    """Main function to install all required dependencies"""
    print("Installing CNPJ ETL dependencies...")

    # List of packages to install
    packages = [
        "pandas>=1.5.0",
        "polars>=0.19.0",
        "sqlalchemy>=1.4.0",
        "psycopg2-binary>=2.9.0",
    ]

    installed = 0
    failed = 0

    for package in packages:
        if install_package(package):
            installed += 1
        else:
            failed += 1

    print("\nInstallation summary:")
    print(f"  Successfully installed: {installed}")
    print(f"  Failed to install: {failed}")

    if failed == 0:
        print("\nAll dependencies installed successfully!")
        print("You can now run the CNPJ ETL scripts.")
    else:
        print(f"\nWarning: {failed} packages failed to install.")
        print(
            "You may need to install them manually or check your internet connection."
        )


if __name__ == "__main__":
    main()

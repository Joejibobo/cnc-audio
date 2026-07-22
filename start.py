"""CNC Audio -- development server launcher.
Run this from the project root: python start.py
"""
import subprocess
import sys
import os

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("\n=== CNC Audio ===")
    print("Server starting at http://127.0.0.1:8000\n")
    subprocess.run([
        sys.executable, "-m", "uvicorn",
        "packages.api.main:app",
        "--host", "127.0.0.1",
        "--port", "8000",
    ])

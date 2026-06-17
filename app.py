# app.py — Lanzador de la aplicación de escritorio (Flet)
#
# Uso:
#   python app.py
#
# Empaquetar a .exe (Windows):
#   flet build windows
from src.desktop.app import run

if __name__ == "__main__":
    run()

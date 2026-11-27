"""Deixa os módulos de src/ importáveis nos testes. Rodar na raiz do projeto: pytest"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

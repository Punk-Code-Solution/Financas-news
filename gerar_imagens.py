"""Gera capas (Pexels stock + IA) para artigos sem imagem.

Prioriza noticias mais novas (id DESC). Padrao: 1 por execucao.
Com Pexels, lotes maiores sao viaveis (ex.: python gerar_imagens.py 10).
"""
import sys

from dotenv import load_dotenv

load_dotenv()

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import core

if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    limit = max(1, min(limit, 50))
    resultado = core.backfill_missing_images(limit=limit)
    print(f"Processados: {resultado['processed']}")
    print(f"Atualizados: {resultado['updated']}")
    print(f"Falhas: {resultado['failed']}")
    for item in resultado["items"]:
        print(f"  #{item['id']} -> {item['imagem_url']}")

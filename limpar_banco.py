import os
from dotenv import load_dotenv

from db import ensure_schema, get_db

load_dotenv()

try:
    print("Conectando ao banco...")
    client = get_db()
    ensure_schema(client)
    client.execute("DELETE FROM news")
    print("✅ Banco de dados limpo com sucesso!")
    print("Todas as notícias antigas/curtas foram removidas. Pronto para a nova IA.")
    client.close()
except Exception as e:
    print(f"Erro ao limpar o banco: {e}")

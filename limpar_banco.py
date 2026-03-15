import os
import libsql_client
from dotenv import load_dotenv

# Carrega as variáveis e aplica a correção da trava de segurança (wss:// para libsql://)
load_dotenv()
url = os.environ.get("TURSO_DATABASE_URL", "libsql://")
if url.startswith("wss://"):
    url = url.replace("wss://", "libsql://")
token = os.environ.get("TURSO_AUTH_TOKEN")

try:
    print("Conectando ao Turso...")
    client = libsql_client.create_client_sync(url=url, auth_token=token)
    
    # Apaga todas as notícias
    client.execute("DELETE FROM news")
    
    print("✅ Banco de dados limpo com sucesso!")
    print("Todas as notícias antigas/curtas foram removidas. Pronto para a nova IA.")
    client.close()
except Exception as e:
    print(f"Erro ao limpar o banco: {e}")
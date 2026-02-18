from google import genai
import os
from dotenv import load_dotenv

load_dotenv()
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

print("--- MODELOS DISPONÍVEIS ---")
try:
    for model in client.models.list():
        # Vamos imprimir apenas o nome para evitar erro de atributo
        print(f"👉 {model.name}")
except Exception as e:
    print(f"❌ Erro fatal: {e}")
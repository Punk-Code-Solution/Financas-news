import sqlite3

c = sqlite3.connect("news.db")
print(
    "com_capa",
    c.execute(
        "SELECT COUNT(*) FROM news WHERE imagem_url IS NOT NULL AND TRIM(imagem_url) != ''"
    ).fetchone()[0],
)
print(
    "sem_capa",
    c.execute(
        "SELECT COUNT(*) FROM news WHERE imagem_url IS NULL OR TRIM(COALESCE(imagem_url,'')) = ''"
    ).fetchone()[0],
)
for row in c.execute(
    "SELECT id, substr(imagem_url,1,70), LENGTH(COALESCE(resumo,'')) FROM news ORDER BY id"
):
    print(row)

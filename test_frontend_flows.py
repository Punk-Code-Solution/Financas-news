"""Smoke do front: páginas públicas + cadastro/login + comentários + colunista.

Usa SQLite isolado (não toca o Turso de produção).
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import patch

os.environ.setdefault("ROBO_TOKEN", "test-robo-token-local")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-frontend")
os.environ.setdefault("IP_HASH_SALT", "test-ip-salt-frontend")
os.environ.setdefault("COLUMNIST_ADMIN_EMAILS", "admin-qa@clareza.test")
os.environ.setdefault("COLUMNIST_SHARE_RATE", "0.35")
os.environ.setdefault("COLUMNIST_SITE_RPM_BRL", "10")
os.environ.setdefault("COLUMNIST_PAYOUT_MIN_BRL", "1")

from fastapi.testclient import TestClient

import core
import db as dbmod
import main

FAKE_MARKET = {
    "coletado_em": "09/08/2026 20:00",
    "Dólar (USD/BRL)": {"cotacao": "R$ 5,10", "variacao_24h": "-0.25%"},
}
FAKE_BCB = {
    "Selic meta (% a.a.)": {"valor": "14.25", "data": "09/08/2026"},
    "IPCA acumulado 12 meses (%)": {"valor": "4.64", "data": "09/08/2026"},
}

JSON_HDR = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
PITCH = (
    "Quero escrever análises semanais sobre Selic, crédito e renda fixa, "
    "com dados do BCB e sem recomendação de investimento."
)
ARTICLE_TITLE = "Selic e o crédito imobiliário no segundo semestre"
ARTICLE_SUMMARY = (
    "O ciclo de juros altos segue pressionando o crédito imobiliário. "
    "Esta análise cruza a meta Selic com o IPCA e o impacto no bolso de "
    "quem financia imóvel no SFH."
)
ARTICLE_BODY = (
    "A manutenção da Selic em patamar elevado altera o custo do crédito, "
    "o apetite dos bancos e o ritmo de financiamento habitacional. "
    "Nesta análise original do Clareza Capital, cruzamos a meta do Copom "
    "com o IPCA acumulado em 12 meses e com o comportamento recente do "
    "crédito imobiliário. O objetivo é explicar o mecanismo — não recomendar "
    "compra ou venda de ativos. Quem tem financiamento atrelado à taxa "
    "deve acompanhar o comunicado do Copom e o IPCA cheio, sem tratar "
    "esta matéria como consultoria personalizada. "
    * 2
)


def _seed_news(client_db) -> int:
    resumo = ("Análise editorial de teste para o front. " * 40)[:900]
    client_db.execute(
        """
        INSERT INTO news (
            titulo, resumo, impacto, link, tag, sentimento, published_at, fonte,
            created_at, moderation_status, home_priority
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'published', 80)
        """,
        [
            "Copom mantém Selic e o crédito reagiu",
            resumo,
            "Juros altos encarecem financiamento e exigem planejamento.",
            f"https://example.test/noticia/{uuid.uuid4().hex[:8]}",
            "Juros",
            "Neutro",
            "2026-08-09T20:00:00Z",
            "Clareza Capital",
            "2026-08-09T20:00:00Z",
        ],
    )
    row = client_db.execute("SELECT id FROM news ORDER BY id DESC LIMIT 1")
    return int(row.rows[0][0])


def _qa_db(tmp_path):
    path = str(tmp_path / "frontend_qa.db")
    os.environ["USE_LOCAL_DB"] = "1"
    os.environ["LOCAL_DATABASE_PATH"] = path
    dbmod._client = None
    dbmod._schema_ready = False
    dbmod._fts_ready = False
    local = dbmod.LocalDbClient(path)
    dbmod.ensure_schema(local)
    dbmod._client = local
    news_id = _seed_news(local)
    return local, news_id


def _client():
    return TestClient(main.app)


def _login(c: TestClient, email: str, password: str):
    return c.post(
        "/login",
        data={"email": email, "password": password, "next": "/"},
        follow_redirects=False,
    )


def test_public_pages_and_seo_chrome(tmp_path):
    db_client, news_id = _qa_db(tmp_path)
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
        patch.object(core, "warmup_market_caches", return_value=None),
    ):
        c = _client()
        for path in [
            "/",
            "/mercado",
            "/metodologia",
            "/quem-somos",
            "/privacidade",
            "/termos",
            "/termos-colunista",
            "/login",
            "/cadastro",
            f"/noticia/{news_id}",
            "/robots.txt",
            "/sitemap.xml",
            "/feed.xml",
        ]:
            r = c.get(path)
            assert r.status_code == 200, f"{path} -> {r.status_code}"

        home = c.get("/")
        assert "Clareza" in home.text
        assert "fn-cookie" in home.text or "cookie" in home.text.lower()
        assert "/login" in home.text

        noticia = c.get(f"/noticia/{news_id}")
        assert "comentarios" in noticia.text.lower()
        assert "Entrar para comentar" in noticia.text
        assert 'id="fn-comment-form"' not in noticia.text
        assert 'id="fn-contact-modal"' in noticia.text

        login = c.get("/login")
        assert 'name="email"' in login.text and 'name="password"' in login.text
        assert "/cadastro" in login.text

        cadastro = c.get("/cadastro")
        assert 'name="name"' in cadastro.text and 'minlength="8"' in cadastro.text


def test_cadastro_verify_login_perfil_logout(tmp_path):
    db_client, _news_id = _qa_db(tmp_path)
    email = f"user-{uuid.uuid4().hex[:8]}@clareza.test"
    password = "senha-segura-123"
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
        patch.object(core, "warmup_market_caches", return_value=None),
    ):
        c = _client()
        bad_pw = c.post(
            "/cadastro",
            data={"name": "QA", "email": email, "password": "123"},
            follow_redirects=False,
        )
        assert bad_pw.status_code == 303
        assert "erro=" in (bad_pw.headers.get("location") or "")

        created = c.post(
            "/cadastro",
            data={"name": "QA User", "email": email, "password": password},
            follow_redirects=False,
        )
        assert created.status_code == 303
        loc = created.headers.get("location") or ""
        assert "/login" in loc
        assert "verificar=1" in loc or "msg=" in loc

        blocked = _login(c, email, password)
        assert blocked.status_code == 303
        assert "verificar=1" in (blocked.headers.get("location") or "")

        row = db_client.execute(
            "SELECT email_verify_token FROM users WHERE email = ? LIMIT 1",
            [email],
        )
        token = row.rows[0][0]
        verified = c.get(f"/verificar-email?token={token}", follow_redirects=False)
        assert verified.status_code == 303
        assert "msg=" in (verified.headers.get("location") or "")

        ok = _login(c, email, password)
        assert ok.status_code == 303
        assert (ok.headers.get("location") or "/") in ("/", "/perfil") or (
            ok.headers.get("location") or ""
        ).startswith("/")

        home = c.get("/")
        assert "fn-user-menu-btn" in home.text
        assert email.split("@")[0] in home.text or "QA User" in home.text or "Minha conta" in home.text

        perfil = c.get("/perfil")
        assert perfil.status_code == 200
        assert "QA User" in perfil.text
        assert email in perfil.text
        assert "/colunista" in perfil.text
        assert 'action="/perfil/avatar"' in perfil.text

        logged_login = c.get("/login", follow_redirects=False)
        assert logged_login.status_code == 303
        assert "/perfil" in (logged_login.headers.get("location") or "")

        dup = c.post(
            "/cadastro",
            data={"name": "Outro", "email": email, "password": password},
            follow_redirects=False,
        )
        assert dup.status_code == 303
        # já logado → perfil; se sessão caísse, erro de e-mail duplicado
        loc_dup = dup.headers.get("location") or ""
        assert "/perfil" in loc_dup or "já cadastrado" in loc_dup.lower() or "erro=" in loc_dup

        invalid = TestClient(main.app).post(
            "/login",
            data={"email": email, "password": "errada-demais", "next": "/"},
            follow_redirects=False,
        )
        assert invalid.status_code == 303
        assert "erro=" in (invalid.headers.get("location") or "")

        out = c.post("/logout", follow_redirects=False)
        assert out.status_code in (303, 302)
        home2 = c.get("/")
        assert "fn-user-menu-btn" not in home2.text
        assert "/login" in home2.text


def test_comments_guest_publish_upvote_delete_moderation(tmp_path):
    db_client, news_id = _qa_db(tmp_path)
    email = f"cmt-{uuid.uuid4().hex[:8]}@clareza.test"
    password = "senha-segura-123"
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
        patch.object(core, "warmup_market_caches", return_value=None),
    ):
        c = _client()
        guest = c.post(
            f"/noticia/{news_id}/comentarios",
            data={"body": "Comentário sem login."},
            headers=JSON_HDR,
        )
        assert guest.status_code == 401
        assert guest.json().get("error") == "login_required"

        c.post("/cadastro", data={"name": "Comentarista", "email": email, "password": password})
        token = db_client.execute(
            "SELECT email_verify_token FROM users WHERE email = ?", [email]
        ).rows[0][0]
        c.get(f"/verificar-email?token={token}")
        _login(c, email, password)

        page = c.get(f"/noticia/{news_id}")
        assert 'id="fn-comment-form"' in page.text
        assert "Entrar para comentar" not in page.text

        published = c.post(
            f"/noticia/{news_id}/comentarios",
            data={"body": "Leitura clara sobre Selic e crédito imobiliário."},
            headers=JSON_HDR,
        )
        assert published.status_code == 200
        payload = published.json()
        assert payload.get("ok") is True
        comment_id = int(payload["comment"]["id"])

        page2 = c.get(f"/noticia/{news_id}")
        assert "Selic e crédito imobiliário" in page2.text
        assert "fn-delete-btn" in page2.text
        assert "fn-upvote-btn" in page2.text
        assert "fn-reply-toggle" in page2.text

        up = c.post(
            f"/comentarios/{comment_id}/upvote",
            data={"news_id": news_id},
            headers=JSON_HDR,
        )
        assert up.status_code == 200
        assert up.json().get("ok") is True

        blocked = c.post(
            f"/noticia/{news_id}/comentarios",
            data={"body": "Que merda de análise"},
            headers=JSON_HDR,
        )
        assert blocked.status_code == 200
        assert blocked.json().get("ok") is False

        deleted = c.post(
            f"/comentarios/{comment_id}/excluir",
            data={"news_id": news_id},
            headers=JSON_HDR,
        )
        assert deleted.status_code == 200
        assert deleted.json().get("ok") is True
        page3 = c.get(f"/noticia/{news_id}")
        assert "Selic e crédito imobiliário" not in page3.text


def test_columnist_apply_admin_cms_boost(tmp_path):
    db_client, _news_id = _qa_db(tmp_path)
    user_email = f"col-{uuid.uuid4().hex[:8]}@clareza.test"
    admin_email = "admin-qa@clareza.test"
    password = "senha-segura-123"
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
        patch.object(core, "warmup_market_caches", return_value=None),
        patch.dict(os.environ, {"COLUMNIST_ADMIN_EMAILS": admin_email}, clear=False),
    ):
        user = _client()
        admin = _client()

        user.post(
            "/cadastro",
            data={"name": "Colunista QA", "email": user_email, "password": password},
        )
        admin.post(
            "/cadastro",
            data={"name": "Admin QA", "email": admin_email, "password": password},
        )
        for mail, browser in ((user_email, user), (admin_email, admin)):
            token = db_client.execute(
                "SELECT email_verify_token FROM users WHERE email = ?", [mail]
            ).rows[0][0]
            browser.get(f"/verificar-email?token={token}")
        _login(user, user_email, password)
        _login(admin, admin_email, password)

        guest_guard = TestClient(main.app).get("/colunista", follow_redirects=False)
        assert guest_guard.status_code == 303
        assert "/login" in (guest_guard.headers.get("location") or "")

        apply_page = user.get("/colunista/candidatar")
        assert apply_page.status_code == 200
        assert 'name="pitch"' in apply_page.text
        assert "/termos-colunista" in apply_page.text

        sent = user.post(
            "/colunista/candidatar",
            data={"pitch": PITCH},
            follow_redirects=False,
        )
        assert sent.status_code == 303
        assert "ok=1" in (sent.headers.get("location") or "")

        forbidden = user.get("/admin/colunistas")
        assert forbidden.status_code == 403

        admin_page = admin.get("/admin/colunistas")
        assert admin_page.status_code == 200
        assert user_email in admin_page.text
        assert PITCH[:30] in admin_page.text

        app_id = int(
            db_client.execute(
                "SELECT id FROM columnist_applications WHERE user_id = (SELECT id FROM users WHERE email = ?) ORDER BY id DESC LIMIT 1",
                [user_email],
            ).rows[0][0]
        )
        approved = admin.post(
            f"/admin/colunistas/candidatura/{app_id}",
            data={"decision": "approve"},
            follow_redirects=False,
        )
        assert approved.status_code == 303

        dash = user.get("/colunista")
        assert dash.status_code == 200
        assert "/colunista/novo" in dash.text
        assert "Views" in dash.text
        assert 'action="/colunista/pix"' in dash.text

        editor = user.get("/colunista/novo")
        assert editor.status_code == 200
        assert 'name="titulo"' in editor.text
        assert 'name="resumo"' in editor.text
        assert 'name="body"' in editor.text
        assert 'value="submit"' in editor.text

        created = user.post(
            "/colunista/novo",
            data={
                "titulo": ARTICLE_TITLE,
                "resumo": ARTICLE_SUMMARY,
                "body": ARTICLE_BODY,
                "tag": "Juros",
                "action": "submit",
            },
            follow_redirects=False,
        )
        assert created.status_code == 303
        news_id = int(
            db_client.execute(
                "SELECT id FROM news WHERE titulo = ? ORDER BY id DESC LIMIT 1",
                [ARTICLE_TITLE],
            ).rows[0][0]
        )

        pending_page = user.get(f"/noticia/{news_id}")
        assert pending_page.status_code == 200
        assert "revisão" in pending_page.text.lower() or "pending" in pending_page.text.lower() or ARTICLE_TITLE in pending_page.text

        review = admin.post(
            f"/admin/colunistas/artigo/{news_id}",
            data={"decision": "approve", "admin_note": "ok"},
            follow_redirects=False,
        )
        assert review.status_code == 303

        live = user.get(f"/noticia/{news_id}")
        assert live.status_code == 200
        assert ARTICLE_TITLE in live.text
        assert "Colunista" in live.text or "colunista" in live.text.lower()

        boost_page = user.get(f"/colunista/impulsionar/{news_id}")
        assert boost_page.status_code == 200
        assert "carousel_24h" in boost_page.text
        assert "simulate" in boost_page.text

        boosted = user.post(
            f"/colunista/impulsionar/{news_id}",
            data={"plan_id": "carousel_24h", "simulate": "1"},
            follow_redirects=False,
        )
        assert boosted.status_code == 303
        loc = boosted.headers.get("location") or ""
        assert "/colunista" in loc
        assert "ok=1" in loc or "simulacao" in loc.lower() or "Destaque" in loc

        pix = user.post(
            "/colunista/pix",
            data={"pix_key": "11999999999"},
            follow_redirects=False,
        )
        assert pix.status_code == 303

        payout = user.post("/colunista/saque", follow_redirects=False)
        assert payout.status_code == 303


def test_contact_validation_and_auth_guards(tmp_path):
    _qa_db(tmp_path)
    with (
        patch.object(core, "fetch_market_snapshot", return_value=FAKE_MARKET),
        patch.object(core, "fetch_bcb_snapshot", return_value=FAKE_BCB),
        patch.object(core, "fetch_sparkline_data", return_value={}),
        patch.object(core, "warmup_market_caches", return_value=None),
    ):
        c = _client()
        empty = c.post("/fale-conosco", data={"subject": "", "body": ""}, headers=JSON_HDR)
        assert empty.status_code == 400

        too_long = c.post(
            "/fale-conosco",
            data={"subject": "A" * 201, "body": "Descrição ok"},
            headers=JSON_HDR,
        )
        assert too_long.status_code == 400

        newsletter = c.post("/api/newsletter", data={"email": "nao-email"})
        assert newsletter.status_code == 400

        perfil = c.get("/perfil", follow_redirects=False)
        assert perfil.status_code in (303, 302)
        assert "/login" in (perfil.headers.get("location") or "")

"""Testes do programa de colunistas (schema lógico via mocks)."""
from __future__ import annotations

import os
from unittest.mock import MagicMock

os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("IP_HASH_SALT", "test-ip-salt")
os.environ.setdefault("COLUMNIST_SHARE_RATE", "0.35")
os.environ.setdefault("COLUMNIST_SITE_RPM_BRL", "10")

import columnists


class FakeResult:
    def __init__(self, rows=None):
        self.rows = rows or []


class FakeDb:
    def __init__(self):
        self.users = {}
        self.applications = []
        self.news = []
        self.views = []
        self.ledger = []
        self.payouts = []
        self.boosts = []
        self._id = 1

    def execute(self, sql: str, params=None):
        params = list(params or [])
        s = " ".join(sql.split()).lower()

        if "insert into columnist_applications" in s:
            row = {
                "id": self._id,
                "user_id": params[0],
                "pitch": params[1],
                "status": params[2],
                "admin_note": None,
                "created_at": params[3],
                "reviewed_at": None,
            }
            self._id += 1
            self.applications.append(row)
            return FakeResult()

        if "from columnist_applications where user_id" in s:
            for a in reversed(self.applications):
                if a["user_id"] == params[0]:
                    return FakeResult(
                        [[
                            a["id"],
                            a["user_id"],
                            a["pitch"],
                            a["status"],
                            a["admin_note"],
                            a["created_at"],
                            a["reviewed_at"],
                        ]]
                    )
            return FakeResult()

        if "update columnist_applications" in s and "set status" in s:
            for a in self.applications:
                if a["id"] == params[3]:
                    a["status"] = params[0]
                    a["admin_note"] = params[1]
                    a["reviewed_at"] = params[2]
            return FakeResult()

        if "select id, user_id, status from columnist_applications where id" in s:
            for a in self.applications:
                if a["id"] == params[0]:
                    return FakeResult([[a["id"], a["user_id"], a["status"]]])
            return FakeResult()

        if "update users set role" in s:
            self.users[params[1]] = {"role": params[0]}
            return FakeResult()

        if "insert into news" in s:
            nid = self._id
            self._id += 1
            # Compat: INSERT antigo (15) ou com imagem_url (16)
            if len(params) >= 16:
                imagem_url = params[12]
                author_id = params[13]
                content_origin = params[14]
                moderation_status = params[15]
                home_priority = params[11]
                body = params[10]
            else:
                imagem_url = None
                author_id = params[12]
                content_origin = params[13]
                moderation_status = params[14]
                home_priority = params[11]
                body = params[10]
            self.news.append(
                {
                    "id": nid,
                    "titulo": params[0],
                    "resumo": params[1],
                    "body": body,
                    "tag": params[4],
                    "link": params[3],
                    "author_id": author_id,
                    "moderation_status": moderation_status,
                    "content_origin": content_origin,
                    "home_priority": home_priority,
                    "boost_until": None,
                    "fonte": params[7],
                    "published_at": params[6],
                    "created_at": params[8],
                    "imagem_url": imagem_url,
                    "impacto": params[2],
                }
            )
            return FakeResult()

        if "select id from news where link" in s:
            for n in self.news:
                if n["link"] == params[0]:
                    return FakeResult([[n["id"]]])
            return FakeResult()

        if "from news where id" in s and "author_id" in s:
            for n in self.news:
                if n["id"] == params[0]:
                    return FakeResult(
                        [[
                            n["id"],
                            n["titulo"],
                            n["resumo"],
                            n["body"],
                            n["impacto"],
                            n["tag"],
                            n["author_id"],
                            n["content_origin"],
                            n["moderation_status"],
                            n["home_priority"],
                            n["boost_until"],
                            n["published_at"],
                            n["created_at"],
                            n["imagem_url"],
                            n["fonte"],
                        ]]
                    )
            return FakeResult()

        if "update news set" in s and "moderation_status = ?" in s and "published_at" in s:
            for n in self.news:
                if n["id"] == params[-1]:
                    n["moderation_status"] = params[0]
                    n["published_at"] = params[1]
            return FakeResult()

        if "insert into page_views" in s:
            key = (params[0], params[2], params[4])
            if any((v[0], v[2], v[4]) == key for v in self.views):
                raise Exception("unique")
            self.views.append(params)
            return FakeResult()

        if "select count(*) from page_views where author_id" in s:
            return FakeResult([[sum(1 for v in self.views if v[1] == params[0])]])

        if "select count(*) from page_views where news_id" in s:
            return FakeResult([[sum(1 for v in self.views if v[0] == params[0])]])

        if "from page_views where day" in s and "group by" in s:
            buckets: dict[tuple, int] = {}
            for v in self.views:
                if v[4] == params[0]:
                    buckets[(v[1], v[0])] = buckets.get((v[1], v[0]), 0) + 1
            return FakeResult([[a, n, c] for (a, n), c in buckets.items()])

        if "from wallet_ledger where kind" in s:
            return FakeResult()

        if "insert into wallet_ledger" in s:
            self.ledger.append(params)
            return FakeResult()

        if "sum(amount_brl)" in s:
            uid = params[0]
            total = sum(float(e[2]) for e in self.ledger if e[0] == uid)
            return FakeResult([[total]])

        if "coalesce(home_priority" in s and "from news where id" in s:
            for n in self.news:
                if n["id"] == params[0]:
                    return FakeResult([[n["home_priority"]]])
            return FakeResult([[0]])

        if "insert into boost_orders" in s:
            oid = self._id
            self._id += 1
            self.boosts.append(
                {
                    "id": oid,
                    "user_id": params[0],
                    "news_id": params[1],
                    "plan_id": params[2],
                    "amount_brl": params[3],
                    "status": params[4],
                    "external_ref": params[5],
                }
            )
            return FakeResult()

        if "from boost_orders where external_ref" in s:
            for b in self.boosts:
                if b["external_ref"] == params[0]:
                    return FakeResult([[b["id"]]])
            return FakeResult()

        if "from boost_orders where id" in s:
            for b in self.boosts:
                if b["id"] == params[0]:
                    return FakeResult([[b["id"], b["news_id"], b["plan_id"], b["status"]]])
            return FakeResult()

        if "update boost_orders set status = 'paid'" in s:
            for b in self.boosts:
                if b["id"] == params[2]:
                    b["status"] = "paid"
            return FakeResult()

        if "update news set home_priority" in s:
            for n in self.news:
                if n["id"] == params[3]:
                    n["home_priority"] = params[0]
                    n["boost_until"] = params[1]
            return FakeResult()

        return FakeResult()


def test_share_rate_clamped():
    os.environ["COLUMNIST_SHARE_RATE"] = "0.99"
    assert columnists.columnist_share_rate() == 0.40
    os.environ["COLUMNIST_SHARE_RATE"] = "0.10"
    assert columnists.columnist_share_rate() == 0.30
    os.environ["COLUMNIST_SHARE_RATE"] = "0.35"
    assert columnists.columnist_share_rate() == 0.35


def test_validate_article_rejects_short():
    try:
        columnists.validate_article_fields("curto", "resumo curto demais", "body", "Economia")
        assert False
    except ValueError:
        pass


def test_application_and_approve_flow():
    db = FakeDb()
    app = columnists.submit_application(db, 7, "x" * 50)
    assert app["status"] == "pending"
    reviewed = columnists.review_application(db, app["id"], approve=True)
    assert reviewed["status"] == "approved"
    assert db.users[7]["role"] == "columnist"


def test_create_article_pending():
    db = FakeDb()
    nid = columnists.create_article(
        db,
        user_id=3,
        author_name="Ana",
        titulo="Selic e crédito imobiliário no Brasil hoje",
        resumo="A taxa básica segue elevada e isso muda o custo do financiamento da casa própria para famílias.",
        body=("Análise detalhada sobre o impacto da Selic no crédito. " * 8),
        tag="Economia",
        submit=True,
    )
    assert nid >= 1
    art = columnists.get_article_for_author(db, nid, 3)
    assert art["moderation_status"] == "pending"
    columnists.review_article(db, nid, approve=True)
    art2 = columnists.get_article_for_author(db, nid, 3)
    assert art2["moderation_status"] == "published"


def test_pageview_dedupe_and_credit():
    db = FakeDb()
    db.news.append(
        {
            "id": 10,
            "titulo": "t",
            "resumo": "r" * 50,
            "body": "b" * 250,
            "impacto": "",
            "tag": "Economia",
            "link": "internal://x",
            "author_id": 5,
            "content_origin": "columnist",
            "moderation_status": "published",
            "home_priority": 50,
            "boost_until": None,
            "published_at": "2026-01-01",
            "created_at": "2026-01-01",
            "imagem_url": None,
            "fonte": "Colunista",
        }
    )
    assert columnists.record_page_view(db, 10, author_id=5, ip="1.1.1.1", user_agent="ua")
    assert not columnists.record_page_view(db, 10, author_id=5, ip="1.1.1.1", user_agent="ua")
    # força day no registro
    day = db.views[0][4]
    result = columnists.credit_daily_shares(db, day=day)
    assert result["ok"] is True
    assert result["entries"] >= 1
    assert columnists.wallet_balance(db, 5) > 0


def test_boost_activate_caps_priority():
    db = FakeDb()
    db.news.append(
        {
            "id": 22,
            "titulo": "Titulo longo o bastante aqui",
            "resumo": "r" * 50,
            "body": "b" * 250,
            "impacto": "",
            "tag": "Economia",
            "link": "internal://y",
            "author_id": 9,
            "content_origin": "columnist",
            "moderation_status": "published",
            "home_priority": 20,
            "boost_until": None,
            "published_at": "2026-01-01",
            "created_at": "2026-01-01",
            "imagem_url": None,
            "fonte": "Colunista",
        }
    )
    order = columnists.create_boost_order(db, user_id=9, news_id=22, plan_id="carousel_24h")
    columnists.activate_boost(db, order["id"])
    assert db.news[0]["home_priority"] <= columnists.BOOST_CAP_PRIORITY
    assert db.news[0]["boost_until"]

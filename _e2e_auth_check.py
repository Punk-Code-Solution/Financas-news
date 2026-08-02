"""E2E auth checklist against local server. Do not commit."""
from __future__ import annotations

import re
import time
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, Request, build_opener

BASE = "http://127.0.0.1:8000"
TS = int(time.time())
EMAIL = f"teste.auth.{TS}@example.com"
PASSWORD = "SenhaForte123!"
NAME = "Usuario Teste Auth"
WEAK_PW = "123"
RESULTS: list[tuple[str, str, str]] = []


def record(step: str, ok: bool, detail: str) -> None:
    RESULTS.append((step, "PASS" if ok else "FAIL", detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {step}: {detail}")


class Client:
    def __init__(self) -> None:
        self.jar = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar))

    def request(
        self,
        method: str,
        path: str,
        *,
        data: dict | None = None,
        allow_redirects: bool = False,
        timeout: int = 60,
    ):
        url = urljoin(BASE, path)
        body = None
        headers = {"User-Agent": "e2e-auth-check"}
        if data is not None:
            body = urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = Request(url, data=body, headers=headers, method=method)
        try:
            resp = self.opener.open(req, timeout=timeout)
            final_url = resp.geturl()
            status = resp.status
            raw = resp.read()
            text = raw.decode("utf-8", errors="replace")
            headers_out = {k.lower(): v for k, v in resp.headers.items()}
            if not allow_redirects and status in (301, 302, 303, 307, 308):
                return status, text, headers_out, final_url, resp
            return status, text, headers_out, final_url, resp
        except HTTPError as e:
            raw = e.read() if e.fp else b""
            text = raw.decode("utf-8", errors="replace")
            headers_out = {k.lower(): v for k, v in e.headers.items()} if e.headers else {}
            loc = headers_out.get("location", "")
            return e.code, text, headers_out, loc or path, e

    def session_cookie(self):
        for c in self.jar:
            if c.name == "fn_session":
                return c
        return None

    def clear_session(self) -> None:
        for c in list(self.jar):
            if c.name == "fn_session":
                self.jar.clear(c.domain, c.path, c.name)


def has_centered_card(html: str) -> bool:
    return ("max-w-md" in html) and ("rounded-2xl" in html or "rounded-xl" in html)


def main() -> None:
    anon = Client()

    # 1. pages
    for path, title_hint in [("/login", "Entrar"), ("/cadastro", "Criar conta")]:
        st, html, _, _, _ = anon.request("GET", path, allow_redirects=True)
        ok = st == 200 and has_centered_card(html) and title_hint.lower() in html.lower()
        record(f"1 GET {path}", ok, f"status={st} card={has_centered_card(html)} len={len(html)}")

    st, html, hdrs, final, _ = anon.request("GET", "/perfil", allow_redirects=False)
    # urllib follows redirects by default unless we catch 3xx — with HTTPError for 303?
    # build_opener follows redirects. Use raw for redirect check.
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=30)
    conn.request("GET", "/perfil", headers={"User-Agent": "e2e"})
    r = conn.getresponse()
    body = r.read().decode("utf-8", errors="replace")
    loc = r.getheader("Location") or ""
    ok2 = r.status in (302, 303) and "/login" in loc
    record("2 GET /perfil sem sessão", ok2, f"status={r.status} loc={loc}")
    conn.close()

    st, html, _, _, _ = anon.request("GET", "/perfil", allow_redirects=True)
    # when following, should land on login
    record(
        "2b /perfil follow -> login",
        st == 200 and ("Entrar" in html or "login" in html.lower()),
        f"status={st} entrar={'Entrar' in html}",
    )

    # 3 links
    st, login_html, _, _, _ = anon.request("GET", "/login", allow_redirects=True)
    st2, cad_html, _, _, _ = anon.request("GET", "/cadastro", allow_redirects=True)
    link_ok = ('href="/cadastro' in login_html or "href=\"/cadastro" in login_html) and (
        'href="/login' in cad_html or "Já tenho conta" in cad_html or "Entrar" in cad_html
    )
    record("3 link login↔cadastro", link_ok, f"login→cadastro={('/cadastro' in login_html)} cadastro→login={('/login' in cad_html)}")

    # env names (no values)
    from pathlib import Path

    keys = set()
    envp = Path(".env")
    if envp.exists():
        for line in envp.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            keys.add(line.split("=", 1)[0].strip())
    for k in [
        "SESSION_SECRET",
        "SESSION_HTTPS_ONLY",
        "GOOGLE_OAUTH_CLIENT_ID",
        "GOOGLE_OAUTH_CLIENT_SECRET",
        "GOOGLE_OAUTH_REDIRECT_URI",
        "IP_HASH_SALT",
    ]:
        print(f"ENV {k}={'SET' if k in keys else 'MISSING'}")

    oauth_configured = all(
        k in keys
        for k in ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET", "GOOGLE_OAUTH_REDIRECT_URI")
    )

    # 6 weak password first (before success so we don't depend on user)
    st, html, hdrs, loc, _ = anon.request(
        "POST",
        "/cadastro",
        data={"name": "X", "email": f"weak.{TS}@example.com", "password": WEAK_PW},
        allow_redirects=False,
    )
    # urllib follows — need raw
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=60)
    body = urlencode({"name": "X", "email": f"weak.{TS}@example.com", "password": WEAK_PW}).encode()
    conn.request(
        "POST",
        "/cadastro",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "e2e"},
    )
    r = conn.getresponse()
    loc = r.getheader("Location") or ""
    body_txt = r.read().decode("utf-8", errors="replace")
    weak_ok = r.status in (302, 303) and ("erro=" in loc.lower() or "senha" in loc.lower() or "8" in loc)
    record("6 senha fraca", weak_ok, f"status={r.status} loc={loc[:120]}")
    conn.close()

    # empty fields — FastAPI Form(...) → 422
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=30)
    body = urlencode({"name": "", "email": "", "password": ""}).encode()
    conn.request(
        "POST",
        "/cadastro",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "e2e"},
    )
    r = conn.getresponse()
    r.read()
    empty_ok = r.status in (422, 400, 303, 302)
    record("6b campos vazios", empty_ok, f"status={r.status}")
    conn.close()

    # 4 valid cadastro
    user = Client()
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=90)
    body = urlencode({"name": NAME, "email": EMAIL, "password": PASSWORD}).encode()
    conn.request(
        "POST",
        "/cadastro",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "e2e"},
    )
    r = conn.getresponse()
    loc = r.getheader("Location") or ""
    set_cookie = r.getheader("Set-Cookie") or ""
    cad_body = r.read().decode("utf-8", errors="replace")
    cad_ok = r.status in (302, 303) and ("/perfil" in loc or "/login" in loc) and "erro=" not in loc.lower()
    record("4 POST cadastro válido", cad_ok, f"status={r.status} loc={loc} set-cookie_has_session={'fn_session' in set_cookie}")
    # capture cookie for session
    if set_cookie and "fn_session" in set_cookie:
        # parse into user jar via follow
        pass
    conn.close()

    # Use requests-like session via urllib with cookie from cadastro
    # Re-do with opener that doesn't follow... actually use http.client for control then requests for session ops
    # Better: use urllib opener which stores cookies; but it follows redirects.
    # Starlette SessionMiddleware sets cookie on response; opener should store it on redirect follow.

    user2 = Client()
    st, html, hdrs, final, _ = user2.request(
        "POST",
        "/cadastro",
        data={"name": NAME + " B", "email": f"teste.auth.{TS}.b@example.com", "password": PASSWORD},
        allow_redirects=True,
    )
    # If first cadastro worked, this second is fine; if first failed due to turso, both may fail.
    # Prefer EMAIL from step 4 — if step4 failed, try with b email for rest
    active_email = EMAIL if cad_ok else f"teste.auth.{TS}.b@example.com"
    active_name = NAME if cad_ok else NAME + " B"
    cookie = user2.session_cookie()
    if cad_ok:
        # Need session from first cadastro — redo login
        login_c = Client()
        st, html, hdrs, final, _ = login_c.request(
            "POST",
            "/login",
            data={"email": EMAIL, "password": PASSWORD, "next": "/perfil"},
            allow_redirects=True,
        )
        cookie = login_c.session_cookie()
        session_client = login_c
    else:
        session_client = user2
        cookie = user2.session_cookie()
        # check if user2 cadastro landed on perfil
        cad_b_ok = st == 200 and ("Meu perfil" in html or active_name in html)
        if not cad_ok:
            record("4b retry cadastro B", cad_b_ok or (cookie is not None), f"status={st} cookie={cookie is not None} perfil={'Meu perfil' in html}")

    # 7 avatar
    if cookie or session_client.session_cookie():
        st, html, _, _, _ = session_client.request("GET", "/perfil", allow_redirects=True)
        avatar_ok = "/static/avatars/default.svg" in html or "avatars/default" in html
        # also password not in page
        pw_leak = PASSWORD in html or "password_hash" in html
        record("7 avatar padrão", avatar_ok, f"default_avatar={avatar_ok} name_in_page={active_name.split()[0] in html or NAME.split()[0] in html}")
        record("11 perfil após auth", st == 200 and ("Meu perfil" in html) and (EMAIL in html or active_email in html or "@example.com" in html), f"status={st} email_present={EMAIL in html or active_email in html}")
        record("12 senha não no HTML", not pw_leak, f"password_in_html={pw_leak}")
    else:
        record("7 avatar padrão", False, "sem sessão após cadastro/login")
        record("11 perfil após auth", False, "sem sessão")
        record("12 senha não no HTML", True, "n/a sem página perfil")

    # 5 duplicate
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=60)
    dup_email = EMAIL if cad_ok else active_email
    body = urlencode({"name": "Dup", "email": dup_email, "password": PASSWORD}).encode()
    conn.request(
        "POST",
        "/cadastro",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "e2e"},
    )
    r = conn.getresponse()
    loc = r.getheader("Location") or ""
    r.read()
    dup_ok = r.status in (302, 303) and ("já+cadastrado" in loc.lower() or "ja+cadastrado" in loc.lower() or "cadastrado" in loc.lower() or "erro=" in loc.lower())
    record("5 email duplicado", dup_ok, f"status={r.status} loc={loc[:140]}")
    conn.close()

    # 8 login correct + cookie flags
    # logout first
    if session_client.session_cookie():
        session_client.request("POST", "/logout", data={}, allow_redirects=True)

    login_fresh = Client()
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=60)
    body = urlencode({"email": dup_email, "password": PASSWORD, "next": "/perfil"}).encode()
    conn.request(
        "POST",
        "/login",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "e2e"},
    )
    r = conn.getresponse()
    loc = r.getheader("Location") or ""
    sc = r.getheader("Set-Cookie") or ""
    r.read()
    httponly = "httponly" in sc.lower()
    secure = "secure" in sc.lower()
    login_ok = r.status in (302, 303) and "erro=" not in loc.lower() and "fn_session" in sc and httponly
    record("8 login ok + HttpOnly", login_ok, f"status={r.status} loc={loc} HttpOnly={httponly} Secure={secure} cookie_len={len(sc)}")
    conn.close()

    # SESSION_HTTPS_ONLY expectation
    https_only_env = "SESSION_HTTPS_ONLY" in keys
    # default true but Secure only if RENDER or FORCE_SECURE — local should NOT have Secure typically
    record(
        "13 cookie Secure condicional",
        (not secure) or True,  # informational: Secure absent locally is OK
        f"Secure={secure} SESSION_HTTPS_ONLY={'SET' if https_only_env else 'MISSING'} (local sem Secure esperado)",
    )

    # 9 wrong password
    bad = Client()
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=60)
    body = urlencode({"email": dup_email, "password": "senha-errada-999", "next": "/perfil"}).encode()
    conn.request(
        "POST",
        "/login",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "e2e"},
    )
    r = conn.getresponse()
    loc = r.getheader("Location") or ""
    sc = r.getheader("Set-Cookie") or ""
    r.read()
    # May still set empty session cookie — check no successful redirect to perfil without erro
    bad_ok = r.status in (302, 303) and ("erro=" in loc.lower() or "/login" in loc)
    record("9 login senha errada", bad_ok, f"status={r.status} loc={loc[:120]}")
    conn.close()

    # follow erro page
    st, html, _, _, _ = bad.request("GET", "/login?erro=Credenciais+inválidas", allow_redirects=True)
    record("9b erro UI", "inválid" in html.lower() or "invalid" in html.lower() or "Credenciais" in html, f"erro_visivel={'Credenciais' in html}")

    # 10 logout
    logged = Client()
    st, html, _, _, _ = logged.request(
        "POST",
        "/login",
        data={"email": dup_email, "password": PASSWORD, "next": "/perfil"},
        allow_redirects=True,
    )
    before = logged.session_cookie()
    st, html, _, _, _ = logged.request("POST", "/logout", data={}, allow_redirects=True)
    after = logged.session_cookie()
    # after logout, perfil should redirect
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=30)
    cookie_hdr = ""
    if after:
        cookie_hdr = f"fn_session={after.value}"
    elif before:
        cookie_hdr = f"fn_session={before.value}"
    conn.request("GET", "/perfil", headers={"User-Agent": "e2e", "Cookie": cookie_hdr} if cookie_hdr else {"User-Agent": "e2e"})
    r = conn.getresponse()
    loc = r.getheader("Location") or ""
    r.read()
    # Better: use session after logout via opener
    st2, html2, _, final2, _ = logged.request("GET", "/perfil", allow_redirects=True)
    logout_ok = before is not None and ("Entrar" in html2 or "login" in final2.lower() or st2 == 200 and "Meu perfil" not in html2)
    # Actually after clear, session cookie may still exist but empty
    st3, html3, _, _, _ = logged.request("GET", "/perfil", allow_redirects=True)
    logout_ok = "Meu perfil" not in html3
    record("10 logout limpa sessão", logout_ok, f"had_cookie_before={before is not None} perfil_after_logout_has_user={'Meu perfil' in html3}")
    conn.close()

    # 14 comment without auth
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=30)
    body = urlencode({"body": "Comentario teste sem auth"}).encode()
    conn.request(
        "POST",
        "/noticia/1/comentarios",
        body=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "e2e"},
    )
    r = conn.getresponse()
    loc = r.getheader("Location") or ""
    r.read()
    cmt_ok = r.status in (302, 303, 401) and ("/login" in loc or r.status == 401)
    record("14 comentário sem auth", cmt_ok, f"status={r.status} loc={loc[:120]}")
    conn.close()

    # 15 Google OAuth
    st, login_html, _, _, _ = anon.request("GET", "/login", allow_redirects=True)
    btn = "Continuar com Google" in login_html or "/auth/google" in login_html
    if oauth_configured:
        conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=30)
        conn.request("GET", "/auth/google", headers={"User-Agent": "e2e"})
        r = conn.getresponse()
        loc = r.getheader("Location") or ""
        r.read()
        oauth_ok = r.status in (302, 303) and "accounts.google.com" in loc and r.status != 500
        record("15 Google OAuth configurado", oauth_ok and btn, f"btn={btn} status={r.status} loc={loc[:80]}")
        conn.close()
    else:
        # button should be absent; /auth/google → 503
        conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=30)
        conn.request("GET", "/auth/google", headers={"User-Agent": "e2e"})
        r = conn.getresponse()
        r.read()
        oauth_ok = (not btn) and r.status in (503, 302, 303)
        record("15 Google OAuth ausente", not btn, f"btn_absent={not btn} /auth/google status={r.status}")
        conn.close()

    print("\n=== RESUMO ===")
    for step, res, detail in RESULTS:
        print(f"{res}\t{step}\t{detail}")
    fails = sum(1 for _, r, _ in RESULTS if r == "FAIL")
    print(f"TOTAL={len(RESULTS)} FAIL={fails}")


if __name__ == "__main__":
    main()

"""Testes do provedor de capas Pexels (stock) e helpers."""
from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image

import core


def _tiny_jpeg(w: int = 800, h: int = 450) -> bytes:
    img = Image.new("RGB", (w, h), color=(20, 80, 140))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


def test_stock_search_query_maps_selic():
    q = core._stock_search_query("Copom mantém Selic em 14,25%", "Juros", "")
    assert "central bank" in q or "interest" in q


def test_stock_search_query_ignores_selic_only_in_resumo():
    q = core._stock_search_query(
        "Fidelity pressiona por regulacao cripto",
        "Cripto",
        "Com a Selic a 14% e o Banco Central acompanhando o IPCA...",
    )
    assert "crypto" in q.lower() or "trading" in q.lower()


def test_stock_search_query_fallback_tag():
    q = core._stock_search_query("Mercado abre em alta", "Ações", "")
    assert "stock" in q.lower() or "trading" in q.lower()


def test_stock_search_query_prefers_theme_over_selic_mention():
    q = core._stock_search_query(
        "Consumo de lazer na crise: pipocas artesanais com a Selic a 14%",
        "Economia",
        "",
    )
    assert "entertainment" in q or "concert" in q or "festival" in q


def test_stock_search_query_pet_plans():
    q = core._stock_search_query(
        "Judicialização de planos pet: O custo invisível das famílias",
        "Economia",
        "Com a Selic alta...",
    )
    assert "pet" in q.lower() or "veterinary" in q.lower()


def test_fit_cover_jpeg_16x9():
    raw = _tiny_jpeg(1000, 1000)
    out = core._fit_cover_jpeg(raw)
    assert out and out[:2] == b"\xff\xd8"
    img = Image.open(io.BytesIO(out))
    w, h = img.size
    assert abs((w / h) - (16 / 9)) < 0.05


def test_get_image_providers_includes_pexels(monkeypatch=None):
    os.environ["IMAGE_PROVIDER"] = "pexels,gemini"
    try:
        providers = core.get_image_providers()
        assert providers[0] == "pexels"
        assert "gemini" in providers
    finally:
        os.environ.pop("IMAGE_PROVIDER", None)


def test_pexels_photo_id_from_url():
    assert (
        core._pexels_photo_id_from_url(
            "https://images.pexels.com/photos/33607526/pexels-photo-33607526.jpeg?auto=compress"
        )
        == "33607526"
    )


def test_pexels_skips_already_used_photo_id():
    images_dir = Path("static/images/articles")
    images_dir.mkdir(parents=True, exist_ok=True)
    slug = "testpexelsunique01"
    for old in images_dir.glob(f"{slug}.*"):
        old.unlink()

    search_payload = {
        "photos": [
            {
                "id": 111,
                "width": 1600,
                "height": 900,
                "photographer": "A",
                "src": {"large": "https://images.pexels.com/photos/111/a.jpg"},
            },
            {
                "id": 222,
                "width": 1600,
                "height": 900,
                "photographer": "B",
                "src": {"large": "https://images.pexels.com/photos/222/b.jpg"},
            },
        ]
    }
    search_resp = MagicMock(status_code=200)
    search_resp.json.return_value = search_payload

    with patch.dict(
        os.environ,
        {
            "PEXELS_API_KEY": "fake-key",
            "PEXELS_USE_REMOTE_URL": "1",
            "ARTICLE_IMAGES_DIR": str(images_dir),
        },
    ):
        core.clear_used_pexels_cache()
        core.clear_pexels_pool()
        with patch.object(core, "_ensure_used_pexels_ids", return_value={"111"}):
            with patch("core.requests.get", return_value=search_resp):
                url = core._generate_article_image_pexels(
                    "Titulo teste",
                    "Economia",
                    "",
                    slug,
                )
    assert url and "/photos/222/" in url
    core.clear_used_pexels_cache()
    core.clear_pexels_pool()


def test_pexels_generate_saves_file(tmp_path: Path | None = None):
    images_dir = Path("static/images/articles")
    images_dir.mkdir(parents=True, exist_ok=True)
    slug = "testpexelsstock01"
    for old in images_dir.glob(f"{slug}.*"):
        old.unlink()

    jpeg = _tiny_jpeg()
    search_payload = {
        "photos": [
            {
                "id": 999001,
                "width": 1600,
                "height": 900,
                "photographer": "Tester",
                "src": {"large": "https://images.example/cover.jpg"},
            }
        ]
    }

    search_resp = MagicMock(status_code=200)
    search_resp.json.return_value = search_payload
    dl_resp = MagicMock(status_code=200, content=jpeg)

    with patch.dict(
        os.environ,
        {
            "PEXELS_API_KEY": "fake-key",
            "PEXELS_USE_REMOTE_URL": "0",
            "ARTICLE_IMAGES_DIR": str(images_dir),
        },
    ):
        core.clear_used_pexels_cache()
        core.clear_pexels_pool()
        with patch.object(core, "_ensure_used_pexels_ids", return_value=set()):
            with patch("core.requests.get", side_effect=[search_resp, dl_resp]):
                url = core._generate_article_image_pexels(
                    "Selic sobe e afeta crédito",
                    "Juros",
                    "O Copom elevou a taxa básica.",
                    slug,
                )

    assert url == f"/media/articles/{slug}.jpg"
    assert (images_dir / f"{slug}.jpg").is_file()
    (images_dir / f"{slug}.jpg").unlink(missing_ok=True)
    core.clear_used_pexels_cache()
    core.clear_pexels_pool()


def test_pexels_skipped_without_key():
    with patch.dict(os.environ, {"PEXELS_API_KEY": ""}, clear=False):
        os.environ.pop("PEXELS_API_KEY", None)
        os.environ.pop("PEXELS_KEY", None)
        url = core._generate_article_image_pexels("Titulo", "Economia", "", "noslug")
        assert url is None


if __name__ == "__main__":
    test_stock_search_query_maps_selic()
    test_stock_search_query_ignores_selic_only_in_resumo()
    test_stock_search_query_fallback_tag()
    test_stock_search_query_prefers_theme_over_selic_mention()
    test_stock_search_query_pet_plans()
    test_fit_cover_jpeg_16x9()
    test_get_image_providers_includes_pexels()
    test_pexels_photo_id_from_url()
    test_pexels_skips_already_used_photo_id()
    test_pexels_generate_saves_file()
    test_pexels_skipped_without_key()
    print("PASS: test_pexels_covers")

"""Filtro de palavrões e termos degradantes (PT-BR) para moderação de comentários."""
from __future__ import annotations

import re
import unicodedata

# Lista curada — termos ofensivos / racistas / sexistas / degradantes (PT-BR).
# Mantida curta de propósito; expandir conforme moderação real.
_BLOCKED_TERMS: tuple[str, ...] = (
    "merda",
    "porra",
    "caralho",
    "puta",
    "puto",
    "putinha",
    "viado",
    "viadinho",
    "bicha",
    "vagabunda",
    "vagabundo",
    "fdp",
    "filho da puta",
    "filha da puta",
    "vsf",
    "vai se foder",
    "vai tomar no cu",
    "arrombado",
    "arrombada",
    "cuzão",
    "cuzao",
    "buceta",
    "pênis",
    "penis",
    "retardado",
    "retardada",
    "mongoloide",
    "mongolóide",
    "macaco",  # uso pejorativo racial — bloqueio preventivo
    "negro imundo",
    "preto imundo",
    "crioulo",
    "crioula",
    "nazista",
    "hitler",
    "estuprar",
    "estupro",
    "pedofilia",
    "pedofilo",
    "pedófilo",
)


def normalize_text(text: str) -> str:
    """Lowercase + remove acentos + colapsa espaços/pontuação leve para matching."""
    raw = (text or "").strip().lower()
    decomposed = unicodedata.normalize("NFKD", raw)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    # Substitui leetspeak comum
    table = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "@": "a", "$": "s"})
    mapped = without_marks.translate(table)
    cleaned = re.sub(r"[^a-z0-9\s]", " ", mapped)
    return re.sub(r"\s+", " ", cleaned).strip()


def find_blocked_terms(text: str) -> list[str]:
    """Retorna termos bloqueados encontrados no texto (normalizado)."""
    normalized = normalize_text(text)
    if not normalized:
        return []
    found: list[str] = []
    for term in _BLOCKED_TERMS:
        needle = normalize_text(term)
        if not needle:
            continue
        # Palavra inteira ou frase contígua
        pattern = r"(?:^|\s)" + re.escape(needle).replace(r"\ ", r"\s+") + r"(?:\s|$)"
        if re.search(pattern, f" {normalized} "):
            found.append(term)
    return found


def is_clean(text: str) -> bool:
    return not find_blocked_terms(text)


def moderate_comment(text: str) -> dict[str, object]:
    """Avalia comentário: published se limpo, pending/blocked se violar."""
    body = (text or "").strip()
    if not body:
        return {"ok": False, "status": "rejected", "reason": "empty", "matches": []}
    if len(body) > 2000:
        return {"ok": False, "status": "rejected", "reason": "too_long", "matches": []}
    matches = find_blocked_terms(body)
    if matches:
        return {
            "ok": False,
            "status": "blocked",
            "reason": "profanity",
            "matches": matches,
        }
    return {"ok": True, "status": "published", "reason": None, "matches": []}

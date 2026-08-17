"""
Traducción ES/EN en tiempo de ejecución para el TUI (i18n-hot-swap-tui).

Fuente de verdad del idioma activo: el singleton a nivel de módulo definido
acá, inicializado una sola vez al importar desde
src.core.config_defaults.language(). Cualquier otro estado (por ejemplo un
atributo en la App de Textual) es solo un espejo de lectura — nunca la
fuente de verdad — para evitar bugs de sincronización en dos direcciones.
"""

from src.core.config_defaults import language as _default_language
from src.i18n.en import EN_STRINGS
from src.i18n.es import ES_STRINGS

_TABLES: dict[str, dict[str, str]] = {"es": ES_STRINGS, "en": EN_STRINGS}
_DEFAULT_LANGUAGE = "es"

_current_language: str = _default_language()


def get_language() -> str:
    """Idioma activo actual ('es' o 'en')."""
    return _current_language


def set_language(language: str) -> None:
    """
    Actualiza el idioma activo en memoria. No persiste a .env — eso es
    responsabilidad del caller (la Settings screen llama
    env_store.write_values antes de invocar esto).
    """
    global _current_language
    _current_language = language


def t(key: str, /, **kwargs) -> str:
    """
    Traduce `key` al idioma activo.

    `key` es solo posicional a propósito: varias templates interpolan una
    variable llamada justamente "key" (ver settings.invalid_whisper_size),
    y un parámetro nombrado colisionaría con ese kwarg.

    Si la key falta en la tabla activa, cae a la tabla default ('es'); si
    tampoco está ahí, devuelve la key cruda — nunca rompe la UI por un typo
    de traducción. Sin kwargs, la template se devuelve tal cual (evita
    KeyError si una template estática contiene llaves literales no
    destinadas a interpolación).
    """
    template = _TABLES[_current_language].get(key)
    if template is None:
        template = _TABLES[_DEFAULT_LANGUAGE].get(key, key)
    return template.format(**kwargs) if kwargs else template

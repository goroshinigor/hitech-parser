"""Загрузка HTML страниц brain.com.ua.

Основной HTTP-клиент — ``requests`` (:func:`_fetch_with_requests`), разбор
HTML делает ``bs4`` (см. :mod:`products.services.hi_parser`).

Особенность сайта: он закрыт Cloudflare managed challenge — на запрос без
браузерного TLS-отпечатка приходит 403 и заглушка "Just a moment..." (проверено
для ``requests`` с обычными заголовками, с браузерным User-Agent и с
``Session``). Поэтому, если ``requests`` получил челлендж, страница
перезагружается через ``curl_cffi`` с имперсонацией Chrome — у него API как у
``requests``. Если не помогло и это, поднимается :class:`ScraperError`.
"""

from __future__ import annotations

import time
from typing import Optional

import requests

DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
RETRY_DELAY = 2.0
IMPERSONATE = "chrome"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8,en-US;q=0.7,en;q=0.6",
    "Cache-Control": "no-cache",
}


# Признаки страницы-челленджа Cloudflare вместо карточки товара.
CHALLENGE_MARKERS = ("Just a moment", "cf_chl_opt", "Attention Required")


class ScraperError(RuntimeError):
    """Не удалось получить HTML страницы."""


def _is_challenge(html: str) -> bool:
    """Похож ли ответ на заглушку Cloudflare, а не на страницу товара."""
    return any(marker in html for marker in CHALLENGE_MARKERS)


def _fetch_with_requests(url: str, timeout: int) -> str:
    """Основной путь загрузки — обычный ``requests``."""
    response = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
    response.raise_for_status()

    html = response.text
    if _is_challenge(html):
        raise ScraperError("Cloudflare challenge не пройден (requests)")

    return html


def _fetch_with_curl_cffi(url: str, timeout: int) -> str:
    """Резервный путь — ``curl_cffi`` с имперсонацией браузера Chrome.

    Импорт ленивый: ``curl_cffi`` нужен только для обхода Cloudflare,
    без него модуль продолжает работать на ``requests``.
    """
    from curl_cffi import requests as curl_requests

    response = curl_requests.get(
        url,
        impersonate=IMPERSONATE,
        headers=BROWSER_HEADERS,
        timeout=timeout,
    )
    response.raise_for_status()

    html = response.text
    if _is_challenge(html):
        raise ScraperError("Cloudflare challenge не пройден (curl_cffi)")

    return html


def fetch_html(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> str:
    """Загружает HTML страницы и возвращает его как строку.

    Сначала одна попытка через ``requests``. Если он не смог (Cloudflare не
    пропустил запрос или сеть отвалилась), идут попытки через ``curl_cffi``
    с паузой между ними.
    """
    try:
        return _fetch_with_requests(url, timeout)
    except Exception as requests_error:  # noqa: BLE001 - нужен фолбэк
        last_error: Optional[Exception] = None

        for attempt in range(1, retries + 1):
            try:
                return _fetch_with_curl_cffi(url, timeout)
            except Exception as exc:  # noqa: BLE001 - нужен общий ретрай
                last_error = exc
                if attempt < retries:
                    time.sleep(RETRY_DELAY * attempt)

        raise ScraperError(
            f"Не удалось загрузить {url}: requests -> {requests_error}; "
            f"curl_cffi -> {last_error}"
        ) from last_error


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else (
        "https://brain.com.ua/ukr/Mobilniy_telefon_Apple_iPhone_16_Pro_Max_"
        "256GB_Black_Titanium-p1145443.html"
    )
    page = fetch_html(target)
    print(f"Загружено {len(page)} символов с {target}")

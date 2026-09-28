"""Парсер карточки товара brain.com.ua.

Из HTML страницы товара извлекаются:

* полное название;
* цвет;
* объём памяти;
* производитель;
* обычная цена и акционная цена (если есть);
* ссылки на все фото товара (список);
* код товара;
* количество отзывов;
* диагональ экрана;
* разрешение дисплея;
* все характеристики со вкладки (словарь ``группа -> {характеристика: значение}``).

Модуль не зависит от Django и может использоваться как обычный скрипт:

    python -m api.services.hi_parser [URL]

По умолчанию парсится страница из задания (iPhone 16 Pro Max).
"""

from __future__ import annotations

import json
import sys
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .hi_scraper import fetch_html

DEFAULT_URL = (
    "https://brain.com.ua/ukr/Mobilniy_telefon_Apple_iPhone_16_Pro_Max_"
    "256GB_Black_Titanium-p1145443.html"
)

# Названия характеристик на странице (украинский) -> поля результата.
FIELD_CHARACTERISTICS = {
    "color": "Колір",
    "memory": "Вбудована пам'ять",
    "manufacturer": "Виробник",
    "screen_diagonal": "Діагональ екрану",
    "screen_resolution": "Роздільна здатність екрану",
}


# --------------------------------------------------------------------------- #
# Вспомогательные функции
# --------------------------------------------------------------------------- #
def _text(node) -> str:
    """Нормализованный текст узла (без лишних пробелов и переносов)."""
    if node is None:
        return ""
    return " ".join(node.get_text(" ", strip=True).split())


def _parse_price(raw: str) -> Optional[float]:
    """Превращает '65 799 ₴' / '26 999' в число 65799.0."""
    if not raw:
        return None
    cleaned = (
        raw.replace("\xa0", "")
        .replace(" ", "")
        .replace("₴", "")
        .replace(",", ".")
        .strip()
    )
    # Убираем всё, кроме цифр, точки и минуса.
    cleaned = "".join(ch for ch in cleaned if ch.isdigit() or ch in ".-")
    if not cleaned or cleaned in {"-", ".", "-."}:
        return None
    try:
        return float(Decimal(cleaned))
    except InvalidOperation:
        return None


def _characteristic_index(characteristics: Dict[str, dict]) -> Dict[str, str]:
    """Плоский индекс {характеристика: значение} по всем группам."""
    index: Dict[str, str] = {}
    for rows in characteristics.values():
        for key, value in rows.items():
            index.setdefault(key, value)
    return index


# --------------------------------------------------------------------------- #
# Извлечение отдельных блоков
# --------------------------------------------------------------------------- #
def parse_characteristics(soup: BeautifulSoup) -> Dict[str, dict]:
    """Возвращает все характеристики как словарь группа -> {ключ: значение}."""
    result: Dict[str, dict] = {}
    wrapper = soup.select_one(".br-pr-chr-wrap")
    if wrapper is None:
        return result

    for item in wrapper.select(".br-pr-chr-item"):
        heading = item.find("h3")
        group = _text(heading) or "Інше"

        rows: Dict[str, str] = {}
        body = item.find("div")
        if body is not None:
            for row in body.find_all("div", recursive=False):
                spans = row.find_all("span", recursive=False)
                if len(spans) >= 2:
                    key = _text(spans[0])
                    value = _text(spans[1])
                    if key:
                        rows[key] = value
        result[group] = rows

    return result


def parse_photos(soup: BeautifulSoup, base_url: str) -> List[str]:
    """Ссылки на все фото товара (полноразмерные, без thumbnails)."""
    slider = soup.select_one(".br-pr-slider")
    if slider is None:
        return []

    photos: List[str] = []
    seen = set()
    for img in slider.find_all("img", src=True):
        src = img["src"]
        if "_small" in src or "star" in src:
            continue
        full = urljoin(base_url, src)
        if full not in seen:
            seen.add(full)
            photos.append(full)
    return photos


def parse_prices(soup: BeautifulSoup) -> Dict[str, Optional[float]]:
    """Обычная и акционная цены.

    На странице ``.br-pr-op`` — старая (обычная) цена, ``.br-pr-np`` — новая.
    Если старой цены нет, значит скидки нет и ``.br-pr-np`` — обычная цена.
    """
    block = soup.select_one(".price-bonuses-block .br-pr-price.main-price-block")
    if block is None:
        block = soup.select_one(".br-pr-price.main-price-block")

    old_price: Optional[float] = None
    new_price: Optional[float] = None

    if block is not None:
        old_node = block.select_one(".br-pr-op .price-wrapper")
        if old_node is None:
            old_node = block.select_one(".br-pr-op")
        new_node = block.select_one(".br-pr-np .price-wrapper")
        if new_node is None:
            new_node = block.select_one(".br-pr-np")

        old_price = _parse_price(_text(old_node))
        new_price = _parse_price(_text(new_node))

    if old_price is not None and new_price is not None:
        # Есть скидка: op — обычная цена, np — акционная.
        return {"regular_price": old_price, "promo_price": new_price}
    # Скидки нет.
    return {"regular_price": new_price or old_price, "promo_price": None}


def parse_reviews_count(soup: BeautifulSoup) -> int:
    """Количество отзывов из ссылки 'Відгуки (1)' или '1 відгук'."""
    node = soup.select_one(".brackets-reviews") or soup.select_one(
        ".reviews-count"
    )
    if node is None:
        return 0
    digits = "".join(ch for ch in _text(node) if ch.isdigit())
    return int(digits) if digits else 0


def parse_product_code(soup: BeautifulSoup) -> str:
    """Код товара (артикул магазина)."""
    node = soup.select_one(".product-code-num .br-pr-code-val")
    if node is None:
        node = soup.select_one("#product_code .br-pr-code-val")
    return _text(node)


# --------------------------------------------------------------------------- #
# Основной парсер
# --------------------------------------------------------------------------- #
def parse_product(html: str, url: str = "") -> dict:
    """Парсит HTML карточки товара и возвращает словарь с данными."""
    soup = BeautifulSoup(html, "lxml")

    name_node = soup.find("h1")
    characteristics = parse_characteristics(soup)
    char_index = _characteristic_index(characteristics)
    prices = parse_prices(soup)

    data = {
        "url": url,
        "name": _text(name_node),
        "color": char_index.get(FIELD_CHARACTERISTICS["color"], ""),
        "memory": char_index.get(FIELD_CHARACTERISTICS["memory"], ""),
        "manufacturer": char_index.get(FIELD_CHARACTERISTICS["manufacturer"], ""),
        "regular_price": prices["regular_price"],
        "promo_price": prices["promo_price"],
        "photos": parse_photos(soup, url),
        "product_code": parse_product_code(soup),
        "reviews_count": parse_reviews_count(soup),
        "screen_diagonal": char_index.get(
            FIELD_CHARACTERISTICS["screen_diagonal"], ""
        ),
        "screen_resolution": char_index.get(
            FIELD_CHARACTERISTICS["screen_resolution"], ""
        ),
        "characteristics": characteristics,
    }
    return data


def parse_url(url: str = DEFAULT_URL) -> dict:
    """Скачивает страницу и парсит её."""
    html = fetch_html(url)
    return parse_product(html, url)


# --------------------------------------------------------------------------- #
# Шаг-3: печать полученных данных
# --------------------------------------------------------------------------- #
def print_product(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    print_product(parse_url(target))

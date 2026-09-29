"""Выгрузка товаров из БД в CSV (Шаг-7).

Модуль используется и management-командой ``export_csv``, и HTTP-эндпоинтом
``/products/export/csv/``.

Списки и словари (фото, характеристики) в CSV одной колонкой:

* ``photos`` — ссылки через «, »;
* ``characteristics`` — JSON-строка со всеми характеристиками товара.
"""

from __future__ import annotations

import csv
import io
import json
from typing import Iterable, TextIO

from ..models import Product

CSV_FIELDS = (
    "id",
    "url",
    "name",
    "color",
    "memory",
    "manufacturer",
    "regular_price",
    "promo_price",
    "product_code",
    "reviews_count",
    "screen_diagonal",
    "screen_resolution",
    "photos",
    "photos_count",
    "characteristics",
    "created_at",
    "updated_at",
)


def product_row(product: Product) -> dict:
    """Строка CSV для одного товара."""
    return {
        "id": product.pk,
        "url": product.url,
        "name": product.name,
        "color": product.color,
        "memory": product.memory,
        "manufacturer": product.manufacturer,
        "regular_price": "" if product.regular_price is None else product.regular_price,
        "promo_price": "" if product.promo_price is None else product.promo_price,
        "product_code": product.product_code,
        "reviews_count": product.reviews_count,
        "screen_diagonal": product.screen_diagonal,
        "screen_resolution": product.screen_resolution,
        "photos": ", ".join(product.photos or []),
        "photos_count": len(product.photos or []),
        "characteristics": json.dumps(product.characteristics or {}, ensure_ascii=False),
        "created_at": product.created_at.isoformat(timespec="seconds"),
        "updated_at": product.updated_at.isoformat(timespec="seconds"),
    }


def write_products_csv(products: Iterable[Product], stream: TextIO) -> int:
    """Пишет товары в CSV-поток и возвращает число выгруженных строк."""
    writer = csv.DictWriter(stream, fieldnames=list(CSV_FIELDS))
    writer.writeheader()

    count = 0
    for product in products:
        writer.writerow(product_row(product))
        count += 1
    return count


def products_as_csv(products: Iterable[Product]) -> str:
    """Возвращает CSV-текст целиком (для HTTP-ответа)."""
    buffer = io.StringIO()
    write_products_csv(products, buffer)
    return buffer.getvalue()

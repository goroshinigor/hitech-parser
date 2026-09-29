"""Команда: спарсить товар brain.com.ua и сохранить его в БД.

Пример:

    python manage.py parse_product
    python manage.py parse_product "<URL товара>"
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from products.models import Product
from products.services.hi_parser import DEFAULT_URL, parse_url


class Command(BaseCommand):
    help = "Спарсить карточку товара brain.com.ua и сохранить результат в БД"

    def add_arguments(self, parser):
        parser.add_argument(
            "url",
            nargs="?",
            default=DEFAULT_URL,
            help="URL карточки товара (по умолчанию товар из задания)",
        )

    def handle(self, *args, **options):
        url = options["url"]
        self.stdout.write(f"Парсим: {url}")

        try:
            data = parse_url(url)
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"Не удалось спарсить товар: {exc}") from exc

        # Шаг-3: печать полученных данных.
        self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))

        product = Product.from_parsed(data)
        self.stdout.write(
            self.style.SUCCESS(
                f"Сохранено в БД: #{product.pk} «{product.name}»"
            )
        )

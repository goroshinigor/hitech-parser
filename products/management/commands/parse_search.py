"""Команда: найти товар через реальный браузер и сохранить его в БД.

Шаги 1-5 (открыть главную, ввести запрос, нажать «Найти», перейти на первый
результат, собрать данные) выполняет браузерный парсер — Selenium или
Playwright; Шаг-6 — печать данных; Шаг-7 — сохранение в БД.

Примеры:

    python manage.py parse_search
    python manage.py parse_search --engine playwright
    python manage.py parse_search --engine selenium --query "Apple iPhone 15 128GB Black"
    python manage.py parse_search --no-save        # только печать, без БД
    python manage.py parse_search --no-headless    # показать окно браузера
    python manage.py parse_search --chrome-binary /usr/bin/chromium
"""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from products.models import Product
from products.services.playwright_parser import PlaywrightSearchParser
from products.services.search_flow import DEFAULT_QUERY
from products.services.selenium_parser import SeleniumSearchParser

#: Доступные движки: имя для CLI -> класс парсера.
ENGINES = {
    "selenium": SeleniumSearchParser,
    "playwright": PlaywrightSearchParser,
}


class Command(BaseCommand):
    help = (
        "Найти товар на brain.com.ua через браузер (Selenium или Playwright), "
        "напечатать данные и сохранить их в БД"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--engine",
            choices=sorted(ENGINES),
            default="selenium",
            help="чем выполнять шаги в браузере (по умолчанию selenium)",
        )
        parser.add_argument(
            "--query",
            default=DEFAULT_QUERY,
            help="поисковый запрос (по умолчанию запрос из задания)",
        )
        parser.add_argument(
            "--no-save",
            action="store_true",
            help="не сохранять результат в БД (только печать)",
        )
        parser.add_argument(
            "--no-headless",
            action="store_true",
            help="запустить браузер с окном (по умолчанию headless)",
        )
        parser.add_argument(
            "--chrome-binary",
            default=None,
            help="путь к Chrome/Chromium для Selenium (если браузер не в PATH)",
        )

    def handle(self, *args, **options):
        engine_name = options["engine"]
        query = options["query"]
        engine_class = ENGINES[engine_name]

        self.stdout.write(f"Движок: {engine_name} | запрос: {query}")

        parser_options = {"query": query, "headless": not options["no_headless"]}
        if engine_name == "selenium" and options["chrome_binary"]:
            parser_options["browser_binary"] = options["chrome_binary"]

        parser = engine_class(**parser_options)
        try:
            data = parser.collect()
        except Exception as exc:  # noqa: BLE001
            raise CommandError(f"[{engine_name}] не удалось спарсить товар: {exc}") from exc
        finally:
            parser.close()

        # Шаг-6: печать полученных данных.
        self.stdout.write(json.dumps(data, ensure_ascii=False, indent=2))

        if options["no_save"]:
            self.stdout.write(self.style.WARNING("Сохранение в БД отключено (--no-save)"))
            return

        # Шаг-7: сохранение результата в БД.
        product = Product.from_parsed(data)
        self.stdout.write(
            self.style.SUCCESS(f"Сохранено в БД: #{product.pk} «{product.name}»")
        )

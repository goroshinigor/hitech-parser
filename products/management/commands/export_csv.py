"""Команда: выгрузить все товары из БД в CSV (Шаг-7).

Примеры:

    python manage.py export_csv
    python manage.py export_csv --output /tmp/products.csv
    python manage.py export_csv --to-stdout

Флаг называется ``--to-stdout`` (а не ``--stdout``), чтобы не конфликтовать
с kwarg ``stdout`` у ``call_command``: Django подставляет одноимённые опции
из ``**options`` поверх значений командной строки.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from products.models import Product
from products.services.csv_export import write_products_csv

DEFAULT_OUTPUT = "products_export.csv"


class Command(BaseCommand):
    help = "Выгрузить товары из БД в CSV-файл"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=DEFAULT_OUTPUT,
            help=f"файл выгрузки (по умолчанию {DEFAULT_OUTPUT})",
        )
        parser.add_argument(
            "--to-stdout",
            action="store_true",
            help="вывести CSV в stdout вместо файла",
        )

    def handle(self, *args, **options):
        products = Product.objects.all()

        if options["to_stdout"]:
            count = write_products_csv(products, self.stdout)
            self.stderr.write(self.style.SUCCESS(f"Выгружено строк: {count}"))
            return

        path = options["output"]
        # utf-8-sig — чтобы Excel корректно открывал кириллицу.
        with open(path, "w", newline="", encoding="utf-8-sig") as stream:
            count = write_products_csv(products, stream)

        self.stdout.write(
            self.style.SUCCESS(f"Выгружено в {path}: строк {count}")
        )


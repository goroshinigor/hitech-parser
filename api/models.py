"""Модели приложения api."""

from __future__ import annotations

from django.db import models


class Product(models.Model):
    """Спаренный товар brain.com.ua."""

    url = models.URLField(max_length=1000, unique=True)
    name = models.CharField(max_length=500)
    color = models.CharField(max_length=255, blank=True)
    memory = models.CharField(max_length=255, blank=True)
    manufacturer = models.CharField(max_length=255, blank=True)
    regular_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    promo_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    product_code = models.CharField(max_length=100, blank=True)
    reviews_count = models.PositiveIntegerField(default=0)
    screen_diagonal = models.CharField(max_length=50, blank=True)
    screen_resolution = models.CharField(max_length=100, blank=True)
    photos = models.JSONField(default=list, blank=True)
    characteristics = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def from_parsed(cls, data: dict) -> "Product":
        """Создаёт/обновляет товар по словарю из ``hi_parser.parse_product``."""
        fields = {
            "name": data.get("name", ""),
            "color": data.get("color", ""),
            "memory": data.get("memory", ""),
            "manufacturer": data.get("manufacturer", ""),
            "regular_price": data.get("regular_price"),
            "promo_price": data.get("promo_price"),
            "product_code": data.get("product_code", ""),
            "reviews_count": data.get("reviews_count", 0) or 0,
            "screen_diagonal": data.get("screen_diagonal", ""),
            "screen_resolution": data.get("screen_resolution", ""),
            "photos": data.get("photos", []),
            "characteristics": data.get("characteristics", {}),
        }
        product, _ = cls.objects.update_or_create(
            url=data.get("url", ""), defaults=fields
        )
        return product


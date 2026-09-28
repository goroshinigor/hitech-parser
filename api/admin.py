from django.contrib import admin

from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "product_code",
        "manufacturer",
        "memory",
        "color",
        "regular_price",
        "promo_price",
        "reviews_count",
    )
    search_fields = ("name", "product_code", "manufacturer")
    list_filter = ("manufacturer", "color")

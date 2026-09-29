# hitech-parser

Django + PostgreSQL парсер карточек товаров с [brain.com.ua](https://brain.com.ua).

## Что делает

1. Открывает URL карточки товара (по умолчанию — iPhone 16 Pro Max 256GB Black Titanium).
2. Собирает данные о товаре.
3. Печатает результат в консоль.
4. Сохраняет результат в базу данных.

### Извлекаемые данные

| Поле | Источник |
| --- | --- |
| Полное название | `h1` |
| Цвет | характеристика «Колір» |
| Объём памяти | характеристика «Вбудована пам'ять» |
| Производитель | характеристика «Виробник» |
| Цена обычная | `.br-pr-op` (или `.br-pr-np`, если скидки нет) |
| Цена акционная | `.br-pr-np` при наличии скидки |
| Все фото (список ссылок) | `.br-pr-slider img` |
| Код товара | `.br-pr-code-val` |
| Кол-во отзывов | `.brackets-reviews` / `.reviews-count` |
| Диагональ экрана | характеристика «Діагональ екрану» |
| Разрешение дисплея | характеристика «Роздільна здатність екрану» |
| Все характеристики (словарь) | `.br-pr-chr-wrap` → `группа -> {характеристика: значение}` |

> **Чем парсим.** Разбор HTML — `bs4` (`BeautifulSoup` с парсером `lxml`),
> загрузка — `requests`. Но сайт закрыт Cloudflare managed challenge: обычный
> `requests` (в том числе с браузерным `User-Agent` и с `Session`) получает
> **403** и страницу «Just a moment…». Поэтому загрузка устроена в два шага:
> сначала одна попытка через `requests`, а если пришёл челлендж — повтор через
> `curl_cffi` с имперсонацией Chrome (у него API как у `requests`). Обе ветки
> покрыты тестами, см. `products/tests.py`.

## Запуск

### Вариант 1. Docker (PostgreSQL)

```bash
docker compose up --build
```

Затем в другом терминале применить миграции и запустить парсер:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py parse_product
```

### Вариант 2. Локально

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

С PostgreSQL (по умолчанию хост `db`) или без него — для быстрого запуска
есть SQLite-фолбэк:

```bash
USE_SQLITE=1 python manage.py migrate
USE_SQLITE=1 python manage.py parse_product
```

## Использование

Парсинг из кода / как скрипт (Шаг-2 и Шаг-3):

```bash
python -m products.services.hi_parser
python -m products.services.hi_parser "<URL товара>"
```

Management-команда (парсинг + печать + сохранение в БД):

```bash
python manage.py parse_product
python manage.py parse_product "<URL товара>"
```

HTTP-эндпоинт:

```
GET /products/parse/?url=<URL товара>
```

Возвращает JSON `{"saved": true, "id": ..., "product": {...}}` и сохраняет
товар в БД. Без параметра `url` парсится товар из задания.

Веб-страница с кнопкой:

```
GET /products/
```

Страница с предзаполненным URL товара и кнопкой **Parse**: по клику JS
обращается к `/products/parse/`, сохраняет товар и выводит полученный JSON
в блок на странице (ошибки парсинга показываются там же).

## Тесты

```bash
USE_SQLITE=1 python manage.py test
docker compose exec web python manage.py test
```

Проверяются страница `/products/` (кнопка Parse, предзаполненный URL товара)
и `/products/parse/` (сохранение товара, повторный парс того же URL обновляет
ту же запись, ошибка парсинга → 502). Сеть не используется: `parse_url`
подменяется моком.

## Структура

```
config/                     настройки Django
products/
  models.py                 модель Product
  views.py                  /products/ (страница + кнопка Parse), /products/parse/
  admin.py                  админка для Product
  templates/products/index.html  UI: кнопка Parse + вывод JSON
  tests.py                  тесты страницы и эндпоинта (без сети)
  services/
    hi_scraper.py           загрузка HTML (requests, резерв — curl_cffi)
    hi_parser.py            разбор HTML в словарь
  management/commands/
    parse_product.py        CLI: парсинг + сохранение
```

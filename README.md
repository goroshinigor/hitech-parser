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

> Сайт защищён Cloudflare, поэтому для загрузки HTML используется `curl_cffi`
> с имперсонацией браузера Chrome (обычный `requests` получает заглушку).

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
python -m api.services.hi_parser
python -m api.services.hi_parser "<URL товара>"
```

Management-команда (парсинг + печать + сохранение в БД):

```bash
python manage.py parse_product
python manage.py parse_product "<URL товара>"
```

HTTP-эндпоинт:

```
GET /api/parse/?url=<URL товара>
```

Возвращает JSON `{"saved": true, "id": ..., "product": {...}}` и сохраняет
товар в БД. Без параметра `url` парсится товар из задания.

Веб-страница с кнопкой:

```
GET /api/hello/
```

Страница с предзаполненным URL товара и кнопкой **Parse**: по клику JS
обращается к `/api/parse/`, сохраняет товар и выводит полученный JSON
в блок на странице (ошибки парсинга показываются там же).

## Структура

```
config/                     настройки Django
api/
  models.py                 модель Product
  views.py                  /api/hello/ (страница + кнопка Parse), /api/parse/
  admin.py                  админка для Product
  templates/api/hello.html  UI: кнопка Parse + вывод JSON
  services/
    hi_scraper.py           загрузка HTML (обход Cloudflare)
    hi_parser.py            разбор HTML в словарь
  management/commands/
    parse_product.py        CLI: парсинг + сохранение
```

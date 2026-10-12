"""Тесты раздела «Бренды»: список брендов `/ru/brands` и страница бренда.

Бренд НЕ зашит: берём со страницы всех брендов тот, у которого больше всего
товаров (фикстура `brand`). Набор брендов на стенде меняют вместе с данными
магазина, и жёсткий слаг сломал бы весь файл на ровном месте.

Разметка проверена вживую 2026-10-12 (MCP-браузер + ответы API):

- СПИСОК БРЕНДОВ. Плитка — сама ссылка `a.subcatalog__item` на
  `/ru/brands/<slug>`; внутри логотип и `.brand-product-counter` с названием
  (`.title`) и счётчиком («5 товаров» / «5 produse»).

- СТРАНИЦА БРЕНДА — обычный листинг, тот же, что у категории: сайдбар
  `.filters-vertical` («Найдено товаров: N», тоггл «В наличии», цена, «Способ
  получения», дерево «Категория»), `.sorting-bar`, переключатель вида
  `.view-type`. Заголовок — `.category-title`: `h1` с названием бренда и рядом
  `<span>(4 товара)</span>`. Данные листинга приходят с
  `stage.admin.ecom.md/general/brand/<slug>?page=&filters=&sortBy=`
  (`data.products[]` с `url`, `price`, `stock`; `totalCount`).

- СЧЁТЧИК НА ПЛИТКЕ С ЛИСТИНГОМ НЕ СВЕРЯЕМ — сознательно, решение юзера
  2026-10-12. Плитка считает каждый цветовой вариант отдельно (JBL: 5), а
  листинг склеивает варианты одной группы (`is_grouped`) в одну карточку
  (JBL: 4 — Go 4 Squad и Go 4 Pink стали одной карточкой).

- Пагинации у бренда на стенде нет (4 товара) — её покрывают тесты категорий.
"""

import re
from urllib.parse import unquote

import pytest
from playwright.sync_api import Page, expect

from test_category_filters import (
    PRICE_INPUTS,
    PRICE_INPUTS_TIMEOUT,
    _commit_price_input,
    _found_count,
    _present,
    _sidebar,
    _wait_found_count,
)
from test_sorting import _pick_sort

BRANDS_URL = "/ru/brands"
UNKNOWN_BRAND_URL = "/ru/brands/qa-nonexistent-brand"

# Список брендов
BRAND_TILE = "a.subcatalog__item"
TILE_NAME = ".brand-product-counter .title"
TILE_COUNT = ".brand-product-counter span"

# Шапка страницы
BREADCRUMB_ITEM = ".breadcrumb .breadcrumb__item"
BREADCRUMB_BRANDS = '.breadcrumb a[href$="/brands"]'
TITLE_BLOCK = ".category-title"

# Листинг
CARD = ".product__items .product__item"
CARD_NAME = ".product__name"
CARD_LINK = 'a[href*="/product/"]'
OUT_OF_STOCK = ".product__out-of-stock-label"
PAGINATION = ".pagination"
VIEW_LIST_BTN = ".view-type__button:not(.view-type__button--grid)"
VIEW_GRID_BTN = ".view-type__button--grid"

# Фильтры (id чекбоксов: `sp-key-<ключ фильтра>-<значение>`)
IN_STOCK_SWITCH = ".filters-vertical__in-stock button.ui-switch-toggler__switch"
CATEGORY_PREFIX = "sp-key-categoryId-"
DELIVERY_PREFIX = "sp-key-fb_dm-"

ERROR_PAGE = ".error-page"

# Ответ API листинга бренда
BRAND_API = "/general/brand/"

SORT_LOWEST_PRICE = "От самой низкой цены"
SORT_BY_NAME = "По названию"
SORT_BY_NAME_DESC = "По названию в обратном порядке"

# Сколько плиток прокликивать: на стенде их 2, потолок — на случай, если
# подключат магазин с сотней брендов.
MAX_TILES_TO_OPEN = 5


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _first_int(text: str | None) -> int:
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else -1


def _read_tiles(page: Page) -> list[dict]:
    """Плитки брендов: ссылка, название и число товаров с плитки."""
    return page.evaluate(
        """() => [...document.querySelectorAll('a.subcatalog__item')].map(a => ({
            href: a.getAttribute('href') || '',
            name: (a.querySelector('.brand-product-counter .title')?.textContent || '').trim(),
            count: (a.querySelector('.brand-product-counter span')?.textContent || '').trim(),
        }))"""
    )


def _card_slugs(page: Page) -> list[str]:
    """Слаги товаров в порядке отрисовки (без локали — для сравнения ru/ro)."""
    return page.evaluate(
        """() => [...document.querySelectorAll('.product__items .product__item')]
            .map(c => c.querySelector('a[href*="/product/"]'))
            .filter(Boolean)
            .map(a => a.getAttribute('href').split('?')[0].split('/product/')[1])"""
    )


def _title_count(page: Page) -> int:
    """Число из «JBL (4 товара)» — span рядом с h1."""
    return _first_int(page.locator(f"{TITLE_BLOCK} > span").first.text_content())


def _card_names_by_stock(page: Page) -> list[tuple[str, bool]]:
    """(название, в наличии?) по карточкам в порядке отрисовки."""
    return page.evaluate(
        """() => [...document.querySelectorAll('.product__items .product__item')]
            .filter(c => c.querySelector('.product__name'))
            .map(c => [c.querySelector('.product__name').textContent.trim(),
                       !c.querySelector('.product__out-of-stock-label')])"""
    )


def _has_pagination(page: Page) -> bool:
    return page.locator(PAGINATION).count() > 0


def _brand_payload(page: Page, action, *must_contain: str) -> dict:
    """Выполнить `action` и вернуть JSON ответа API бренда, в URL которого
    есть все `must_contain`.

    Ждём именно ответ, а не `networkidle`: на уже загруженной странице
    networkidle выполняется мгновенно, и тест читал пустоту раньше, чем
    сервер отвечал. Фильтры в API уходят НЕ в том виде, что в адресе
    страницы: на странице `filters=inStock:true`, в запросе —
    `filters=[{"inStock":["true"]}]`."""

    def matches(response) -> bool:
        url = unquote(response.url)
        return (
            BRAND_API in url
            and response.request.method == "GET"
            and all(s in url for s in must_contain)
        )

    with page.expect_response(matches, timeout=30_000) as info:
        action()
    response = info.value
    assert response.ok, f"API бренда ответил {response.status}: {unquote(response.url)}"
    return response.json()


def _enabled_option_label(page: Page, prefix: str):
    """Первый чекбокс фильтра с id `prefix*`, который не задизейблен.

    Возвращает (id, число в скобках у опции) или None. Бэкенд дизейблит
    опции, дающие 0 товаров, — кликать по ним нельзя."""
    return page.evaluate(
        """(prefix) => {
            const root = document.querySelector(
                '.filters-vertical:not(.filters-vertical--subcategory)');
            const input = root && [...root.querySelectorAll(
                'input[id^="' + prefix + '"]')].find(i => !i.disabled);
            if (!input) return null;
            const label = root.querySelector('label[for="' + input.id + '"]');
            const m = (label?.textContent || '').match(/\\((\\d+)\\)\\s*$/);
            return [input.id, m ? parseInt(m[1]) : null];
        }""",
        prefix,
    )


def _check_option_filter(page: Page, prefix: str, url_key: str) -> None:
    """Общий сценарий чекбокс-фильтра бренда: применить → сверить → снять.

    Ожидаемое число берём из скобок у самой опции («Портативная акустика (1)»):
    сайт обещает столько товаров — столько и должно прийти."""
    option = _enabled_option_label(page, prefix)
    if option is None:
        pytest.skip(f"У бренда нет активных опций фильтра «{prefix}»")
    option_id, expected = option
    if expected is None:
        pytest.skip(f"У опции {option_id} нет числа товаров в скобках")

    initial_count = _found_count(page)
    initial_slugs = sorted(_card_slugs(page))
    label = page.locator(f'label[for="{option_id}"]').first

    # JS-клик, как в тестах фильтров категории: label обёрнут декоративными
    # спанами, и mouse-клик Playwright промахивается мимо обработчика.
    label.evaluate("el => el.click()")
    page.wait_for_function(
        "(key) => decodeURIComponent(location.search).includes(key)",
        arg=url_key,
        timeout=10_000,
    )
    count = _wait_found_count(page, expected)

    assert count == expected, (
        f"Опция {option_id} обещает {expected} товаров, а «Найдено товаров» = {count}"
    )
    if not _has_pagination(page):
        cards = len(_card_slugs(page))
        assert cards == expected, (
            f"С фильтром {option_id} счётчик {expected}, а карточек на странице {cards}"
        )

    # Снимаем — выдача возвращается к исходной
    page.locator(f'label[for="{option_id}"]').first.evaluate("el => el.click()")
    page.wait_for_function(
        "(key) => !decodeURIComponent(location.search).includes(key)",
        arg=url_key,
        timeout=10_000,
    )
    after = _wait_found_count(page, initial_count)
    assert after == initial_count, (
        f"После снятия фильтра счётчик не вернулся: {initial_count} → {after}"
    )
    if not _has_pagination(page):
        assert sorted(_card_slugs(page)) == initial_slugs, (
            "После снятия фильтра набор товаров отличается от исходного"
        )


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def brand(browser, base_url) -> dict:
    """Бренд с наибольшим числом товаров со страницы всех брендов."""
    ctx = browser.new_context(base_url=base_url, ignore_https_errors=True)
    page = ctx.new_page()
    try:
        page.goto(BRANDS_URL, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.locator(BRAND_TILE).first.wait_for(timeout=30_000)
        except Exception:
            pytest.skip("На странице брендов нет ни одной плитки")
        tiles = [t for t in _read_tiles(page) if "/brands/" in t["href"]]
    finally:
        ctx.close()

    best = max(tiles, key=lambda t: _first_int(t["count"]))
    return {
        "name": best["name"],
        "url": best["href"].split("?")[0],
        "slug": best["href"].split("?")[0].rstrip("/").split("/")[-1],
    }


@pytest.fixture
def brands_index(page: Page) -> Page:
    """Открыта страница всех брендов."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(BRANDS_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(BRAND_TILE).first).to_be_visible(timeout=30_000)
    return page


@pytest.fixture
def brand_page(page: Page, brand: dict) -> Page:
    """Открыта страница бренда с отрисованными фильтрами и карточками."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(brand["url"], wait_until="domcontentloaded", timeout=60_000)
    expect(_sidebar(page)).to_be_visible(timeout=30_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=30_000)
    return page


# ===========================================================================
# Страница всех брендов
# ===========================================================================
def test_brands_index_lists_brands(brands_index: Page):
    """Страница «Бренды»: заголовок, крошки и плитки с названием и числом товаров."""
    page = brands_index

    expect(page.locator("h1")).to_have_text(re.compile(r"Бренд", re.I), timeout=20_000)

    crumbs = page.locator(BREADCRUMB_ITEM)
    expect(crumbs).to_have_count(2, timeout=15_000)
    expect(crumbs.last).to_have_text(re.compile(r"Бренд", re.I))

    tiles = _read_tiles(page)
    assert tiles, "На странице брендов нет ни одной плитки"

    broken = [
        f"{t['href']!r}: название={t['name']!r}, счётчик={t['count']!r}"
        for t in tiles
        if not t["name"]
        or not re.match(r"^/ru/brands/[^/?]+$", t["href"])
        or not re.search(r"\d+\s+товар", t["count"])
        or _first_int(t["count"]) < 1
    ]
    assert not broken, "Плитки брендов без названия, ссылки или числа товаров: " + "; ".join(broken)


def test_brand_tile_opens_brand_page(brands_index: Page):
    """Клик по каждой плитке открывает страницу именно этого бренда."""
    page = brands_index
    tiles = _read_tiles(page)[:MAX_TILES_TO_OPEN]

    for tile in tiles:
        page.goto(BRANDS_URL, wait_until="domcontentloaded", timeout=60_000)
        page.locator(f'{BRAND_TILE}[href="{tile["href"]}"]').first.click()

        expect(page).to_have_url(re.compile(rf"{re.escape(tile['href'])}/?$"), timeout=30_000)
        expect(page.locator(f"{TITLE_BLOCK} h1")).to_have_text(tile["name"], timeout=20_000)


# ===========================================================================
# Страница бренда: шапка и карточки
# ===========================================================================
def test_brand_page_header_and_counters(brand_page: Page, brand: dict):
    """Крошки «Главная / Бренды / <бренд>», заголовок, и все счётчики совпадают."""
    page = brand_page

    crumbs = page.locator(BREADCRUMB_ITEM)
    expect(crumbs).to_have_count(3, timeout=15_000)
    expect(crumbs.nth(1)).to_have_text(re.compile(r"Бренд", re.I))
    expect(crumbs.last).to_have_text(brand["name"])

    expect(page.locator(f"{TITLE_BLOCK} h1")).to_have_text(brand["name"])

    in_title = _title_count(page)
    found = _found_count(page)
    assert in_title >= 1, f"В заголовке нет числа товаров: {page.locator(TITLE_BLOCK).inner_text()!r}"
    assert found == in_title, (
        f"Число в заголовке ({in_title}) не совпадает с «Найдено товаров» ({found})"
    )
    if not _has_pagination(page):
        cards = len(_card_slugs(page))
        assert cards == found, f"«Найдено товаров: {found}», а карточек на странице {cards}"


def test_breadcrumb_returns_to_brands_index(brand_page: Page, brand: dict):
    """Крошка «Бренды» возвращает на список брендов, где есть плитка этого бренда."""
    page = brand_page

    page.locator(BREADCRUMB_BRANDS).first.click()

    expect(page).to_have_url(re.compile(r"/ru/brands/?$"), timeout=30_000)
    expect(page.locator(f'{BRAND_TILE}[href="{brand["url"]}"]')).to_be_visible(timeout=20_000)


def test_brand_product_card_opens_product_page(brand_page: Page):
    """Клик по карточке на странице бренда открывает этот товар."""
    page = brand_page
    card = page.locator(f"{CARD}:has({CARD_NAME})").first
    name = (card.locator(CARD_NAME).first.text_content() or "").strip()
    href = card.locator(CARD_LINK).first.get_attribute("href") or ""
    slug = href.split("?")[0].rstrip("/").split("/")[-1]

    card.locator(CARD_LINK).first.click()

    expect(page).to_have_url(re.compile(rf"/product/{re.escape(slug)}"), timeout=30_000)
    expect(page.locator("h1")).to_contain_text(name[:25], timeout=20_000)


# ===========================================================================
# Сортировка
# ===========================================================================
def test_sort_lowest_price_matches_backend(brand_page: Page):
    """«От самой низкой цены»: `sort=price-` в URL, карточки в порядке ответа
    сервера, и сам этот порядок верный.

    Цены сверяем по ответу API, а не по вёрстке: у товара без стока цены на
    карточке нет вовсе, и по витрине порядок не проверить. Правило сортировки
    (проверено 2026-10-12 на обоих направлениях): сначала товары в наличии,
    потом без стока, внутри каждой группы — по цене.
    """
    page = brand_page
    if len(_card_slugs(page)) < 2:
        pytest.skip("У бренда меньше двух товаров — порядок не проверить")

    payload = _brand_payload(page, lambda: _pick_sort(page, SORT_LOWEST_PRICE), "sortBy=price-")

    assert "sort=price-" in page.url, f"В URL нет sort=price-: {page.url}"
    products = payload["data"]["products"]

    assert _card_slugs(page) == [p["url"] for p in products], (
        "Карточки на странице идут не в том порядке, что прислал сервер: "
        f"{_card_slugs(page)} vs {[p['url'] for p in products]}"
    )

    in_stock = [float(p["price"]) for p in products if float(p["stock"]) > 0]
    no_stock = [float(p["price"]) for p in products if float(p["stock"]) <= 0]
    assert in_stock == sorted(in_stock), f"Товары в наличии не по возрастанию цены: {in_stock}"
    assert no_stock == sorted(no_stock), f"Товары без стока не по возрастанию цены: {no_stock}"

    stock_flags = [float(p["stock"]) > 0 for p in products]
    assert stock_flags == sorted(stock_flags, reverse=True), (
        "Товары без стока стоят выше товаров в наличии: "
        f"{[(p['url'], p['stock']) for p in products]}"
    )


@pytest.mark.parametrize(
    "label, reverse",
    [(SORT_BY_NAME, False), (SORT_BY_NAME_DESC, True)],
    ids=["a_to_z", "z_to_a"],
)
def test_sort_by_name(brand_page: Page, label: str, reverse: bool):
    """«По названию» / «в обратном порядке» — карточки по алфавиту и наоборот.

    Как и у цены, товары в наличии всегда идут первыми, а алфавит действует
    внутри каждой группы (проверено 2026-10-12: А→Я дало «Klipsch…» в наличии,
    затем «JBL Bar…», «JBL Go 4…», «Подарочный…» без стока). Сравнение без учёта
    регистра — как в тестах сортировки категории."""
    page = brand_page

    _pick_sort(page, label)

    cards = _card_names_by_stock(page)
    if len(cards) < 2:
        pytest.skip("Меньше двух товаров в выдаче — порядок не проверить")

    for in_stock, group in ((True, "в наличии"), (False, "без стока")):
        keys = [n.casefold() for n, s in cards if s == in_stock]
        assert keys == sorted(keys, reverse=reverse), (
            f"«{label}» — товары {group} не по алфавиту: {keys}"
        )
    flags = [s for _, s in cards]
    assert flags == sorted(flags, reverse=True), (
        f"«{label}» — товары без стока стоят выше товаров в наличии: {cards}"
    )


# ===========================================================================
# Фильтры
# ===========================================================================
def test_in_stock_toggle_shows_only_available(brand_page: Page):
    """«В наличии»: `inStock:true` в URL, ни одной карточки «Нет в наличии»,
    счётчики пересчитаны; выключение возвращает исходную выдачу."""
    page = brand_page
    if not _present(page.locator(IN_STOCK_SWITCH)):
        pytest.skip("На странице бренда нет тоггла «В наличии»")

    initial_count = _found_count(page)
    initial_slugs = sorted(_card_slugs(page))

    payload = _brand_payload(page, page.locator(IN_STOCK_SWITCH).click, '"inStock"')
    page.wait_for_function(
        "() => decodeURIComponent(location.search).includes('inStock:true')",
        timeout=10_000,
    )
    expected = payload["totalCount"]
    count = _wait_found_count(page, expected)

    assert count == expected, f"Сервер вернул {expected} товаров в наличии, а счётчик {count}"
    assert _title_count(page) == expected, (
        f"Число в заголовке ({_title_count(page)}) не пересчиталось под фильтр ({expected})"
    )
    oos = page.locator(f"{CARD} {OUT_OF_STOCK}:visible")
    assert oos.count() == 0, (
        f"С фильтром «В наличии» на странице {oos.count()} карточек «Нет в наличии»"
    )

    page.locator(IN_STOCK_SWITCH).click()
    page.wait_for_function(
        "() => !decodeURIComponent(location.search).includes('inStock:true')",
        timeout=10_000,
    )
    after = _wait_found_count(page, initial_count)
    assert after == initial_count, (
        f"После выключения «В наличии» счётчик не вернулся: {initial_count} → {after}"
    )
    if not _has_pagination(page):
        assert sorted(_card_slugs(page)) == initial_slugs, (
            "После выключения «В наличии» набор товаров отличается от исходного"
        )


def test_category_filter(brand_page: Page):
    """Галочка категории оставляет столько товаров, сколько обещано в скобках,
    в URL `categoryId`; снятие возвращает исходную выдачу."""
    _check_option_filter(brand_page, CATEGORY_PREFIX, "categoryId:")


def test_delivery_method_filter(brand_page: Page):
    """«Способ получения»: то же, что для категории, — число в скобках, URL, снятие."""
    _check_option_filter(brand_page, DELIVERY_PREFIX, "fb_dm:")


def test_price_filter_keeps_products_within_range(brand_page: Page):
    """Сузить «до» до середины диапазона: счётчик уменьшился, и все товары из
    ответа сервера укладываются в диапазон.

    Цены сверяем по API: на бренде почти все товары без стока, а у таких на
    карточке цены нет — по витрине проверить было бы нечего. Верхняя граница
    слайдера = цене самого дорогого товара, поэтому середина гарантированно
    отсекает хотя бы его, и счётчик обязан уменьшиться."""
    page = brand_page
    inputs = _sidebar(page).locator(PRICE_INPUTS)
    if not _present(inputs, 2, timeout=PRICE_INPUTS_TIMEOUT):
        pytest.skip("На странице бренда нет полей ценового фильтра")

    lo = _first_int(inputs.first.input_value())
    hi = _first_int(inputs.last.input_value())
    # Круглое число: поле округляет ввод до шага слайдера (12774 → 12770), и
    # `_commit_price_input` не дождался бы введённого значения в URL.
    new_max = (lo + hi) // 2 // 100 * 100
    if new_max <= lo:
        pytest.skip(f"Диапазон цен бренда слишком узкий: {lo}-{hi} MDL")

    count_before = _found_count(page)

    payload = _brand_payload(
        page,
        lambda: _commit_price_input(page, inputs.last, str(new_max), "max"),
        '"price"',
        str(new_max),
    )
    count_after = _wait_found_count(page, payload["totalCount"])
    prices = [float(p["price"]) for p in payload["data"]["products"]]

    assert count_after == payload["totalCount"], (
        f"Сервер вернул {payload['totalCount']} товаров, а счётчик {count_after}"
    )
    assert count_after < count_before, (
        f"Граница {new_max} MDL отсекает самый дорогой товар, а счётчик не уменьшился: "
        f"{count_before} → {count_after}"
    )
    outside = [p for p in prices if p < lo or p > new_max]
    assert not outside, f"В выдаче товары вне {lo}-{new_max} MDL: {outside} (все: {prices})"


# ===========================================================================
# Вид листинга
# ===========================================================================
def test_view_toggle_switches_list_and_grid(brand_page: Page):
    """Кнопки «список» / «плитка» переключают вид карточек."""
    page = brand_page
    card = page.locator(CARD).first

    page.locator(VIEW_LIST_BTN).click()
    expect(page.locator(VIEW_LIST_BTN)).to_have_class(re.compile(r"\bactive\b"), timeout=10_000)
    expect(card).to_have_class(re.compile(r"\blist\b"), timeout=10_000)

    page.locator(VIEW_GRID_BTN).click()
    expect(page.locator(VIEW_GRID_BTN)).to_have_class(re.compile(r"\bactive\b"), timeout=10_000)
    expect(card).not_to_have_class(re.compile(r"\blist\b"), timeout=10_000)


# ===========================================================================
# Несуществующий бренд и румынская версия
# ===========================================================================
def test_unknown_brand_shows_404(page: Page):
    """Несуществующий бренд — HTTP 404 и страница ошибки, без товаров."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    response = page.goto(UNKNOWN_BRAND_URL, wait_until="domcontentloaded", timeout=60_000)

    assert response is not None and response.status == 404, (
        f"Несуществующий бренд вернул HTTP {response.status if response else None}, ждали 404"
    )
    expect(page.locator(ERROR_PAGE)).to_be_visible(timeout=20_000)
    assert page.locator(CARD).count() == 0, "На странице ошибки отрисованы товары"


def test_brand_page_in_romanian(brand_page: Page, brand: dict):
    """`/ro/brands/<slug>` — тот же бренд с тем же набором товаров, по-румынски."""
    page = brand_page
    count_ru = _found_count(page)
    slugs_ru = sorted(_card_slugs(page))

    page.goto(f"/ro/brands/{brand['slug']}", wait_until="domcontentloaded", timeout=60_000)
    page.wait_for_function("() => document.documentElement.lang === 'ro'", timeout=20_000)
    expect(_sidebar(page)).to_be_visible(timeout=30_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=30_000)

    expect(page.locator(f"{TITLE_BLOCK} h1")).to_have_text(brand["name"])
    expect(page.locator(BREADCRUMB_ITEM).nth(1)).to_have_text(re.compile(r"Brand", re.I))

    count_ro = _wait_found_count(page, count_ru)
    assert count_ro == count_ru, f"На /ro товаров {count_ro}, а на /ru {count_ru}"
    if not _has_pagination(page):
        assert sorted(_card_slugs(page)) == slugs_ru, (
            "На /ro у бренда другой набор товаров, чем на /ru"
        )

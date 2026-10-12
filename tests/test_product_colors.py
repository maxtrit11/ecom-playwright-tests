"""Тесты выбора цвета на карточке товара (блок «Выбранный цвет»).

Разметка и данные проверены вживую 2026-10-12 на семействе JBL Go 4:

- Блок `.configurator`: подпись `.item__label` («Выбранный цвет» + бейдж с
  названием цвета), образцы — ссылки `a.item__link` (картинка с `alt` =
  название цвета) на `/ru/product/<slug>` нужного цвета, у текущего — `.active`.
- Список строится из `product.colors` (`[{url, color: {title, hexCode}}]`) —
  это и есть эталон. В том же товаре есть ещё `variations` — другой механизм
  группировки, вёрстка выбора цвета его НЕ использует.
- Клик по образцу — переход на страницу варианта (SPA): меняются адрес, h1,
  бейдж, активный образец и кнопка покупки — у варианта без стока
  «Предзаказ», со стоком «В корзину» с ценой. «Назад» возвращает прежний цвет.
- Список цветов на разных страницах может различаться — ТАК ЗАДУМАНО
  (решение юзера 12.10.2026, «что-то с группировками по товарам»): товары,
  дополнительно связанные через `variations` (на 12.10 — Go 4 Squad, Pink,
  Purple), прячут часть цветов друг друга (на Squad нет Pink, на Pink нет
  Squad). Поэтому одинаковый список требуем только от вариантов БЕЗ
  `variations` — у них он полный (на 12.10 — 7 цветов).
- Данные после SPA-перехода берём из живого стора `$nuxt.$store`, а не из
  `window.__NUXT__` (это снимок первой загрузки).

Товар не зашит намертво: берём первого кандидата, у которого не меньше двух
цветов, иначе ищем такой в категории (фикстура `color_product`).
"""

import re

import pytest
from playwright.sync_api import Page, expect

# Кандидаты: у Black на 2026-10-12 полный список из 7 цветов.
_CANDIDATES = ["/ru/product/jbl-go-4-black"]
_FALLBACK_CATEGORIES = ["/ru/acustica-portabila", "/ru/casti"]
_SCAN_LIMIT = 15

CONFIGURATOR = ".configurator"
SWATCH = f"{CONFIGURATOR} .item__list a.item__link"
SWATCH_ACTIVE = f"{SWATCH}.active"
COLOR_BADGE = f"{CONFIGURATOR} .item__label .badge"

# Кнопка покупки в основном блоке товара (без карусели рекомендаций).
BUY_BUTTON = ".primary__product_info button.btn__add_cart:visible"
PREORDER_CLASS = re.compile(r"\bbtn__add_cart_preorder\b")

PRODUCT_JS = """() => {
    const p = window.$nuxt?.$store?.state?.product?.product
        || window.__NUXT__?.state?.product?.product || {};
    return {
        url: p.url,
        title: p.title,
        stock: p.stock,
        grouped: (p.variations || []).some(g => (g.product_variations || []).length > 0),
        colors: (p.colors || []).map(c => ({ url: c.url, title: c.color?.title })),
    };
}"""


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _product(page: Page) -> dict:
    return page.evaluate(PRODUCT_JS)


def _slug(href: str) -> str:
    return (href or "").split("?")[0].rstrip("/").split("/")[-1]


def _swatches(page: Page) -> list[dict]:
    """Образцы цвета на странице: слаг, alt картинки, активен ли."""
    return page.evaluate(
        """() => [...document.querySelectorAll('.configurator .item__list a.item__link')]
            .map(a => ({
                slug: (a.getAttribute('href') || '').split('?')[0].split('/').pop(),
                alt: a.querySelector('img')?.getAttribute('alt') || '',
                active: a.classList.contains('active'),
            }))"""
    )


def _wait_product(page: Page, slug: str) -> dict:
    """Дождаться, пока стор переключится на товар `slug`, и вернуть его."""
    page.wait_for_function(
        """(slug) => (window.$nuxt?.$store?.state?.product?.product?.url) === slug""",
        arg=slug,
        timeout=30_000,
    )
    return _product(page)


def _expect_variant_shown(page: Page, product: dict) -> None:
    """Страница показывает именно этот вариант: адрес, h1, бейдж, активный образец."""
    title = next((c["title"] for c in product["colors"] if c["url"] == product["url"]), None)

    expect(page).to_have_url(re.compile(rf"/product/{re.escape(product['url'])}/?$"))
    expect(page.locator("h1").first).to_have_text(product["title"], timeout=20_000)
    if title:
        expect(page.locator(COLOR_BADGE)).to_have_text(title, timeout=10_000)
    expect(page.locator(SWATCH_ACTIVE)).to_have_count(1)
    expect(page.locator(SWATCH_ACTIVE)).to_have_attribute(
        "href", re.compile(rf"/{re.escape(product['url'])}$")
    )


def _expect_buy_button_matches_stock(page: Page, product: dict) -> None:
    """Без стока — «Предзаказ», со стоком — обычная «В корзину»."""
    button = page.locator(BUY_BUTTON).first
    expect(button).to_be_visible(timeout=15_000)
    if (product["stock"] or 0) > 0:
        expect(button).not_to_have_class(PREORDER_CLASS)
    else:
        expect(button).to_have_class(PREORDER_CLASS)


def _open(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator("h1").first).to_be_visible(timeout=20_000)


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def color_product(browser, base_url) -> str:
    """URL товара, у которого в выборе цвета не меньше двух образцов."""
    ctx = browser.new_context(base_url=base_url, ignore_https_errors=True)
    page = ctx.new_page()

    def has_colors(url: str) -> bool:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            return len(page.evaluate(PRODUCT_JS)["colors"]) >= 2
        except Exception:
            return False

    try:
        for url in _CANDIDATES:
            if has_colors(url):
                return url
        for category in _FALLBACK_CATEGORIES:
            try:
                page.goto(category, wait_until="domcontentloaded", timeout=60_000)
                hrefs = page.evaluate(
                    """() => [...new Set([...document.querySelectorAll(
                        '.product__items .product__item a[href*="/product/"]')]
                        .map(a => a.getAttribute('href').split('?')[0]))]"""
                )
            except Exception:
                continue
            for href in hrefs[:_SCAN_LIMIT]:
                if has_colors(href):
                    return href
    finally:
        ctx.close()
    pytest.skip("Не нашли товара с выбором из двух и более цветов")


@pytest.fixture
def product_page(page: Page, color_product: str) -> Page:
    _open(page, color_product)
    expect(page.locator(SWATCH).first).to_be_visible(timeout=20_000)
    return page


# ===========================================================================
# Тесты
# ===========================================================================
def test_color_picker_matches_product_data(product_page: Page):
    """Образцы — ровно цвета из данных товара и в том же порядке; активен
    текущий; бейдж и подписи картинок — названия цветов."""
    page = product_page
    product = _product(page)
    swatches = _swatches(page)

    assert [s["slug"] for s in swatches] == [c["url"] for c in product["colors"]], (
        f"Образцы {[s['slug'] for s in swatches]} не совпадают с цветами товара "
        f"{[c['url'] for c in product['colors']]}"
    )
    assert [s["alt"] for s in swatches] == [c["title"] for c in product["colors"]], (
        f"Подписи образцов {[s['alt'] for s in swatches]} ≠ названиям цветов "
        f"{[c['title'] for c in product['colors']]}"
    )
    _expect_variant_shown(page, product)


def test_select_color_opens_variant(product_page: Page):
    """Клик по другому цвету открывает этот вариант, и кнопка покупки
    соответствует его стоку."""
    page = product_page
    current = _product(page)
    target = next(c for c in current["colors"] if c["url"] != current["url"])

    page.locator(f'{SWATCH}[href$="/{target["url"]}"]').first.click()

    product = _wait_product(page, target["url"])
    _expect_variant_shown(page, product)
    expect(page.locator(COLOR_BADGE)).to_have_text(target["title"])
    _expect_buy_button_matches_stock(page, product)


def test_back_returns_previous_color(product_page: Page):
    """«Назад» после выбора цвета возвращает прежний вариант."""
    page = product_page
    start = _product(page)
    target = next(c for c in start["colors"] if c["url"] != start["url"])

    page.locator(f'{SWATCH}[href$="/{target["url"]}"]').first.click()
    _wait_product(page, target["url"])
    page.go_back(wait_until="domcontentloaded", timeout=60_000)

    product = _wait_product(page, start["url"])
    _expect_variant_shown(page, product)


def test_every_color_opens_its_own_page(product_page: Page):
    """Каждый образец ведёт на живую страницу своего цвета: h1 этого товара,
    в бейдже — тот же цвет, кнопка покупки соответствует стоку."""
    page = product_page
    colors = _product(page)["colors"]

    problems = []
    for color in colors:
        response = page.goto(
            f"/ru/product/{color['url']}", wait_until="domcontentloaded", timeout=60_000
        )
        if response is None or response.status != 200:
            problems.append(f"{color['url']}: HTTP {response.status if response else None}")
            continue
        product = _product(page)
        if product["url"] != color["url"]:
            problems.append(f"{color['url']}: открылся товар {product['url']}")
            continue
        badge = (page.locator(COLOR_BADGE).text_content(timeout=15_000) or "").strip()
        if badge != color["title"]:
            problems.append(f"{color['url']}: бейдж {badge!r}, ждали {color['title']!r}")
        _expect_buy_button_matches_stock(page, product)

    assert not problems, "Страницы цветов с ошибками: " + "; ".join(problems)


def test_color_list_same_on_every_plain_variant(product_page: Page):
    """У вариантов без доп. группировки (`variations`) список цветов один и
    тот же на каждой странице — с любой можно перейти в любой цвет.

    Варианты с `variations` пропускаем: у них часть цветов скрыта намеренно
    (см. шапку файла)."""
    page = product_page
    origin = _product(page)
    if origin["grouped"]:
        pytest.skip(f"Стартовый товар {origin['url']} сам в доп. группировке")
    expected = [c["url"] for c in origin["colors"]]

    compared, skipped, problems = 0, [], []
    for slug in expected:
        if slug == origin["url"]:
            continue
        page.goto(f"/ru/product/{slug}", wait_until="domcontentloaded", timeout=60_000)
        product = _product(page)
        if product["grouped"]:
            skipped.append(slug)
            continue
        compared += 1
        shown = [s["slug"] for s in _swatches(page)]
        if shown != expected:
            missing = sorted(set(expected) - set(shown))
            extra = sorted(set(shown) - set(expected))
            problems.append(f"{slug}: нет {missing}, лишние {extra}" if missing or extra
                            else f"{slug}: другой порядок {shown}")

    if not compared:
        pytest.skip(f"Все остальные цвета в доп. группировке: {skipped}")
    assert not problems, (
        f"Список цветов отличается от {origin['url']} ({len(expected)} цв.): "
        + "; ".join(problems)
    )

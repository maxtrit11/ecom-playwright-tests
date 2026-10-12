"""Тесты блока «Характеристики» на карточке товара.

Эталон — данные товара `state.product.properties` (то, что пришло с
бэкенда), вёрстку сверяем с ними. Проверено вживую 2026-10-12:

- ИСТОЧНИК — именно `properties`: `[{unitTitle, details: [{title,
  title_value, title_values, specification_description}]}]`. В товаре есть
  ещё `specifications`, но вёрстка его НЕ использует: у PartyBox 720 там
  пусто, а на странице три строки из `properties`.
- Разметка: `.characteristics__info` с `h2` «Характеристики»; группа
  `.characteristics__item` с названием `h3.item__name` (= unitTitle) и
  таблицей строк `.characteristics__row`: название
  `.characteristics__cell-title-text`, значение `.characteristics__cell--value`.
- Подсказка «i» (`.characteristic-tooltip__button`) — только у строк с
  `specification_description`. Клик → `aria-expanded="true"` и
  `.characteristic-tooltip__body` с текстом описания (рендерится через
  портал, поэтому ищем его по странице, а не внутри строки). Закрывается
  повторным кликом, Escape и кликом мимо; на наведение не открывается.
- СТРОКА «БРЕНД»: если у товара задан бренд (`product.brand`: name, slug),
  первой строкой первой группы идёт «Бренд» со ссылкой на
  `/<локаль>/brands/<slug>`. Её нет в `properties`, и у неё нет
  `.characteristics__cell-title-text` — название лежит прямо в `th`.
  Строка выводится только вместе с характеристиками: у Klipsch Flexus бренд
  есть, а характеристик нет — блока нет совсем.
- У товара без характеристик блока нет вовсе — ни таблицы, ни заголовка.
- При выборе другого цвета (SPA-переход) блок перестраивается под новый
  товар — данные тогда в живом сторе `$nuxt.$store`, а не в
  `window.__NUXT__` (это снимок первой загрузки).

Товары не зашиты намертво: кандидаты + поиск в категории (фикстуры).
"""

import re

import pytest
from playwright.sync_api import Page, expect

# Кандидаты на 2026-10-12: у Go 4 Black 5 строк, одна с подсказкой и 7 цветов;
# у Go 4 Pink есть бренд; у Klipsch Flexus Core 300 характеристик нет.
_WITH_SPECS = ["/ru/product/jbl-go-4-black", "/ru/product/jbl-partybox-720"]
_WITH_BRAND = ["/ru/product/jbl-go-4-pink", "/ru/product/jbl-go-4-squad"]
_WITHOUT_SPECS = ["/ru/product/klipsch-flexus-core-300-walnut", "/ru/product/jbl-bar-1300mk2"]
_FALLBACK_CATEGORIES = ["/ru/acustica-portabila", "/ru/casti"]
_SCAN_LIMIT = 15

SECTION = ".characteristics__info"
SECTION_TITLE = f"{SECTION} h2"
GROUP = f"{SECTION} .characteristics__item"
GROUP_NAME = ".item__name"
ROW = ".characteristics__row"
ROW_TITLE = ".characteristics__cell-title-text"
ROW_VALUE = ".characteristics__cell--value"
TIP_BUTTON = ".characteristic-tooltip__button"
TIP_BODY = ".characteristic-tooltip__body"
SWATCH = ".configurator .item__list a.item__link"

PROPS_JS = """() => {
    const s = window.$nuxt?.$store?.state?.product || window.__NUXT__?.state?.product || {};
    return {
        url: s.product?.url,
        brand: s.product?.brand?.name
            ? { name: s.product.brand.name, slug: s.product.brand.slug } : null,
        colors: (s.product?.colors || []).map(c => c.url),
        groups: (s.properties || []).map(g => ({
            name: g.unitTitle,
            rows: (g.details || []).map(d => ({
                title: d.title,
                value: d.title_value,
                tip: d.specification_description || null,
            })),
        })),
    };
}"""

UI_JS = """() => [...document.querySelectorAll('.characteristics__info .characteristics__item')]
    .map(g => ({
        name: g.querySelector('.item__name')?.textContent || '',
        rows: [...g.querySelectorAll('.characteristics__row')].map(r => ({
            title: (r.querySelector('.characteristics__cell-title-text')
                || r.querySelector('th'))?.textContent || '',
            value: r.querySelector('.characteristics__cell--value')?.textContent || '',
            tip: !!r.querySelector('.characteristic-tooltip__button'),
            brandHref: r.querySelector('a[href*="/brands/"]')?.getAttribute('href') || null,
        })),
    }))"""


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _norm(text: str | None) -> str:
    """Схлопнуть пробелы и переносы: в значениях бывают `\\r\\n\\r\\n`."""
    return re.sub(r"\s+", " ", text or "").strip()


def _strip_html(html: str | None) -> str:
    return _norm(re.sub(r"<[^>]+>", " ", html or ""))


def _data(page: Page) -> dict:
    return page.evaluate(PROPS_JS)


def _ui(page: Page) -> list[dict]:
    return page.evaluate(UI_JS)


def _row_count(data: dict) -> int:
    """Строк характеристик в данных (без строки «Бренд»)."""
    return sum(len(g["rows"]) for g in data["groups"])


def _expected_rows(data: dict) -> list[tuple[str | None, str]]:
    """(название, значение) строк в порядке вывода. У строки «Бренд»
    название None: подпись берётся из перевода, а не из данных."""
    rows = [(_norm(r["title"]), _norm(r["value"])) for g in data["groups"] for r in g["rows"]]
    if rows and data["brand"]:
        rows.insert(0, (None, _norm(data["brand"]["name"])))
    return rows


def _shown_rows(page: Page) -> list[tuple[str | None, str]]:
    return [
        (None if r["brandHref"] else _norm(r["title"]), _norm(r["value"]))
        for g in _ui(page) for r in g["rows"]
    ]


def _open(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator("h1").first).to_be_visible(timeout=20_000)


def _first_tip(page: Page):
    button = page.locator(f"{SECTION} {TIP_BUTTON}").first
    button.scroll_into_view_if_needed()
    return button


def _open_tip(page: Page):
    """Открыть первую подсказку; повтор — на случай клика до гидрации."""
    button = _first_tip(page)
    for attempt in range(3):
        button.click()
        try:
            expect(button).to_have_attribute("aria-expanded", "true", timeout=5_000)
            break
        except AssertionError:
            if attempt == 2:
                raise
    expect(page.locator(TIP_BODY)).to_be_visible(timeout=5_000)
    return button


def _find_product(browser, base_url, candidates, accept) -> str | None:
    """Первый товар (из кандидатов, затем из категорий), для которого
    `accept(данные)` истинно."""
    ctx = browser.new_context(base_url=base_url, ignore_https_errors=True)
    page = ctx.new_page()

    def check(url: str) -> bool:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            return accept(page.evaluate(PROPS_JS))
        except Exception:
            return False

    try:
        for url in candidates:
            if check(url):
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
                if check(href):
                    return href
    finally:
        ctx.close()
    return None


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def specs_product(browser, base_url) -> str:
    """Товар с характеристиками, предпочтительно с подсказкой «i»."""
    url = _find_product(
        browser, base_url, _WITH_SPECS,
        lambda d: any(r["tip"] for g in d["groups"] for r in g["rows"]),
    ) or _find_product(browser, base_url, _WITH_SPECS, lambda d: _row_count(d) > 0)
    if not url:
        pytest.skip("Не нашли товара с характеристиками")
    return url


@pytest.fixture(scope="module")
def no_specs_product(browser, base_url) -> str:
    url = _find_product(browser, base_url, _WITHOUT_SPECS, lambda d: _row_count(d) == 0)
    if not url:
        pytest.skip("Не нашли товара без характеристик")
    return url


@pytest.fixture(scope="module")
def color_with_other_specs(browser, base_url, specs_product) -> tuple[str | None, bool]:
    """Цвет товара, у которого характеристики ОТЛИЧАЮТСЯ от стартового.

    Без этого тест «блок следует за цветом» беззубый: у большинства цветов
    Go 4 характеристики одинаковые (на 12.10 отличается только Pink — 4
    строки вместо 5), и необновившийся блок прошёл бы проверку.
    Возвращает (слаг, отличаются ли); если отличающегося нет — первый другой цвет."""
    ctx = browser.new_context(base_url=base_url, ignore_https_errors=True)
    page = ctx.new_page()
    try:
        page.goto(specs_product, wait_until="domcontentloaded", timeout=60_000)
        start = page.evaluate(PROPS_JS)
        others = [c for c in start["colors"] if c != start["url"]]
        for slug in others:
            page.goto(f"/ru/product/{slug}", wait_until="domcontentloaded", timeout=60_000)
            if page.evaluate(PROPS_JS)["groups"] != start["groups"]:
                return slug, True
    finally:
        ctx.close()
    return (others[0] if others else None), False


@pytest.fixture(scope="module")
def branded_product(browser, base_url) -> str:
    """Товар с характеристиками и заданным брендом."""
    url = _find_product(
        browser, base_url, _WITH_BRAND, lambda d: _row_count(d) > 0 and bool(d["brand"])
    )
    if not url:
        pytest.skip("Не нашли товара с брендом и характеристиками")
    return url


@pytest.fixture
def specs_page(page: Page, specs_product: str) -> Page:
    _open(page, specs_product)
    expect(page.locator(SECTION)).to_be_visible(timeout=20_000)
    return page


# ===========================================================================
# Содержимое
# ===========================================================================
def test_specs_match_product_data(specs_page: Page):
    """Заголовок «Характеристики»; группы, названия и значения строк — ровно
    те, что в данных товара, и в том же порядке."""
    page = specs_page
    expected = _data(page)["groups"]
    shown = _ui(page)

    expect(page.locator(SECTION_TITLE)).to_have_text(re.compile(r"Характеристики"))

    assert [_norm(g["name"]) for g in shown] == [_norm(g["name"]) for g in expected], (
        f"Группы на странице {[g['name'] for g in shown]} ≠ в данных "
        f"{[g['name'] for g in expected]}"
    )
    got, want = _shown_rows(page), _expected_rows(_data(page))
    assert got == want, (
        f"Характеристики расходятся с данными: на странице {got}, в данных {want} "
        "(None — строка «Бренд»)"
    )


def test_tooltip_only_on_described_specs(specs_page: Page):
    """Кнопка «i» есть ровно у тех строк, у которых в данных есть описание."""
    page = specs_page
    expected = [
        (_norm(r["title"]), bool(r["tip"])) for g in _data(page)["groups"] for r in g["rows"]
    ]
    shown = [
        (_norm(r["title"]), r["tip"]) for g in _ui(page) for r in g["rows"] if not r["brandHref"]
    ]

    assert shown == expected, (
        "Подсказки «i» не совпадают с описаниями в данных: "
        f"на странице {[t for t, tip in shown if tip]}, в данных {[t for t, tip in expected if tip]}"
    )


def test_specs_hidden_for_product_without_specs(page: Page, no_specs_product: str):
    """У товара без характеристик блока нет — ни таблицы, ни пустого заголовка."""
    _open(page, no_specs_product)

    expect(page.locator(SECTION)).to_have_count(0)
    expect(page.get_by_role("heading", name="Характеристики")).to_have_count(0)


# ===========================================================================
# Подсказка «i»
# ===========================================================================
def test_tooltip_shows_spec_description(specs_page: Page):
    """Клик по «i» показывает описание именно этой характеристики."""
    page = specs_page
    described = [r for g in _data(page)["groups"] for r in g["rows"] if r["tip"]]
    if not described:
        pytest.skip("У товара нет характеристик с описанием")

    _open_tip(page)

    expect(page.locator(TIP_BODY)).to_have_count(1)
    shown = _norm(page.locator(TIP_BODY).text_content())
    assert shown == _strip_html(described[0]["tip"]), (
        f"В подсказке «{described[0]['title']}» текст {shown!r}, "
        f"ждали {_strip_html(described[0]['tip'])!r}"
    )


@pytest.mark.parametrize("how", ["click_again", "escape", "click_outside"])
def test_tooltip_closes(specs_page: Page, how: str):
    """Подсказка закрывается повторным кликом, Escape и кликом мимо."""
    page = specs_page
    if not page.locator(f"{SECTION} {TIP_BUTTON}").count():
        pytest.skip("У товара нет характеристик с описанием")
    button = _open_tip(page)

    if how == "click_again":
        button.click()
    elif how == "escape":
        page.keyboard.press("Escape")
    else:
        page.mouse.click(5, 500)

    expect(button).to_have_attribute("aria-expanded", "false", timeout=5_000)
    expect(page.locator(TIP_BODY)).to_have_count(0)


# ===========================================================================
# Смена цвета и локаль
# ===========================================================================
def test_specs_follow_selected_color(specs_page: Page, color_with_other_specs):
    """После выбора другого цвета блок показывает характеристики нового товара.

    Цвет берём с ОТЛИЧАЮЩИМИСЯ характеристиками (фикстура), иначе блок,
    не обновившийся после перехода, прошёл бы проверку."""
    page = specs_page
    start = _data(page)
    target, differs = color_with_other_specs
    if not target:
        pytest.skip("У товара нет других цветов")

    page.locator(f'{SWATCH}[href$="/{target}"]').first.click()
    page.wait_for_function(
        "(slug) => window.$nuxt?.$store?.state?.product?.product?.url === slug",
        arg=target,
        timeout=30_000,
    )
    want = _expected_rows(_data(page))

    # Блок перестраивается после смены стора — ждём, пока строки совпадут
    # по количеству, а содержимое сверяем ассертом ниже.
    expect(page.locator(f"{SECTION} {ROW}")).to_have_count(len(want), timeout=15_000)
    got = _shown_rows(page)
    assert got == want, (
        f"После выбора цвета {target} на странице {got}, а у товара {want}"
    )
    if differs:
        assert got != _expected_rows(start), "Блок характеристик не перестроился после выбора цвета"


def test_specs_in_romanian(specs_page: Page, specs_product: str):
    """На /ro у товара те же группы и столько же строк, что и в данных /ro."""
    page = specs_page
    data_ru = _data(page)
    rows_ru = _row_count(data_ru)

    _open(page, specs_product.replace("/ru/", "/ro/", 1))
    page.wait_for_function("() => document.documentElement.lang === 'ro'", timeout=20_000)
    data_ro = _data(page)

    assert _row_count(data_ro) == rows_ru, (
        f"На /ro {_row_count(data_ro)} характеристик, на /ru {rows_ru}"
    )
    expect(page.locator(f"{SECTION} {ROW}")).to_have_count(
        len(_expected_rows(data_ro)), timeout=15_000
    )
    shown_groups = [_norm(g["name"]) for g in _ui(page)]
    assert shown_groups == [_norm(g["name"]) for g in data_ro["groups"]], (
        f"Группы на /ro {shown_groups} ≠ в данных {[g['name'] for g in data_ro['groups']]}"
    )


def test_brand_row_links_to_brand_page(page: Page, branded_product: str):
    """Строка «Бренд» — первая, с названием бренда, и ведёт на его страницу."""
    _open(page, branded_product)
    brand = _data(page)["brand"]
    row = page.locator(f"{SECTION} {ROW}").first
    link = row.locator('a[href*="/brands/"]')

    expect(row.locator("th")).to_have_text(re.compile(r"Бренд"))
    expect(link).to_have_text(brand["name"])
    expect(link).to_have_attribute("href", re.compile(rf"/ru/brands/{re.escape(brand['slug'])}$"))

    link.click()

    expect(page).to_have_url(re.compile(rf"/ru/brands/{re.escape(brand['slug'])}/?$"), timeout=30_000)
    expect(page.locator(".category-title h1")).to_have_text(brand["name"], timeout=20_000)

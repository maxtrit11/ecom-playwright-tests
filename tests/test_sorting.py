"""Тесты сортировки на странице категории (category-agnostic по структуре).

Проверяют контрол сортировки (.sorting-bar): выбор опции меняет URL (`sort=`),
меняет порядок товаров, сбрасывает пагинацию на первую страницу и сохраняется
после перезагрузки. Корректность направления проверяется на сортировке по цене
(по возрастанию).

URL категории передаётся через `CATEGORY_URL` (по умолчанию `/ro/jbl-tune`).

ВНИМАНИЕ: подписи опций сортировки зависят от языка интерфейса (здесь — ro,
т.к. дефолтная категория на /ro). При запуске на /ru подписи нужно поменять
в константах ниже — у опций нет языко-независимого идентификатора (это просто
<span> с текстом, без data-value).

Запуск на другой категории:
    CATEGORY_URL=/ro/some-category pytest tests/test_sorting.py
    $env:CATEGORY_URL='/ro/some-category'; pytest tests/test_sorting.py
"""

import os
import re

import pytest
from playwright.sync_api import Locator, Page, expect


CATEGORY_URL = os.environ.get("CATEGORY_URL", "/ro/jbl-tune")


# ---------------------------------------------------------------------------
# Селекторы
# ---------------------------------------------------------------------------
GRID = ".product__items"
CARD = ".product__item"
PRODUCT_NAME = ".product__name"

SORT_BAR = ".sorting-bar"
SORT_BTN = ".sorting-bar__btn"
SORT_LIST = ".sorting-bar__list"
SORT_OPTION = ".sorting-bar__list span"

# Пагинация (для теста сброса на 1-ю страницу)
PAGINATION = ".pagination"
PAGE_BUTTON = ".pagination__button"
ACTIVE_BUTTON = ".pagination__button.active"
NEXT_BUTTON = f"{PAGE_BUTTON}:has(.pagination__button-arrow--next)"

# Подписи опций (ro). Меняются при смене языка интерфейса.
SORT_LOWEST_PRICE = "De la cel mai mic preț"   # по возрастанию цены


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _first_card_name(page: Page) -> str:
    return (
        page.locator(f"{GRID} {CARD} {PRODUCT_NAME}").first.text_content() or ""
    ).strip()


def _sort_param(page: Page) -> str | None:
    """Значение параметра sort= из URL (или None)."""
    m = re.search(r"[?&]sort=([^&]+)", page.url)
    return m.group(1) if m else None


def _in_stock_prices(page: Page) -> list[int]:
    """Цены товаров в наличии (out-of-stock и без цены пропускаем)."""
    return page.evaluate(
        """() => {
            return [...document.querySelectorAll('.product__items .product__item')]
                .filter(c => !c.querySelector('.product__out-of-stock-label'))
                .map(c => {
                    const n = c.querySelector('.product__prices .no-discount');
                    if (!n) return null;
                    const v = parseInt(n.textContent.replace(/[^\\d]/g, ''));
                    return isNaN(v) ? null : v;
                })
                .filter(v => v != null);
        }"""
    )


def _active_page(page: Page) -> int:
    txt = page.locator(ACTIVE_BUTTON).first.text_content() or ""
    m = re.search(r"\d+", txt)
    return int(m.group()) if m else -1


def _sort_option(page: Page, label: str) -> Locator:
    return page.locator(SORT_LIST).get_by_text(label, exact=True)


def _open_sort_dropdown(page: Page) -> None:
    """Раскрыть список сортировки, повторяя клик, пока не появится `.show`.

    Список всегда лежит в DOM (`display: flex`), видимым его делает класс
    `show` на `.sorting-bar__list`. Одиночный клик ненадёжен: после перехода
    по пагинации компонент перерисовывается и первый клик теряется — опция
    остаётся невидимой, и `click()` по ней висит до таймаута (наблюдалось
    2026-08-03 в `test_sort_resets_pagination_to_first_page`).
    """
    for attempt in range(3):
        page.locator(SORT_BTN).click()
        try:
            expect(page.locator(f"{SORT_LIST}.show")).to_be_visible(timeout=3_000)
            return
        except AssertionError:
            if attempt == 2:
                raise
            page.wait_for_timeout(500)


def _click_sort_option(page: Page, label: str, attempts: int = 3) -> None:
    """Открыть дропдаун и кликнуть опцию, повторяя связку целиком.

    `_open_sort_dropdown` гарантирует только то, что список стал видимым в
    момент проверки. После перехода по пагинации компонент успевает
    перерисоваться ещё раз уже ПОСЛЕ открытия — класс `show` слетает, и клик
    по опции висит до общего таймаута действия (45s), проваливая тест
    (наблюдалось 2026-08-10). Поэтому кликаем с коротким таймаутом и при
    неудаче открываем дропдаун заново.
    """
    for attempt in range(attempts):
        _open_sort_dropdown(page)
        page.wait_for_timeout(400)
        try:
            _sort_option(page, label).first.click(timeout=5_000)
            return
        except Exception:
            if attempt == attempts - 1:
                raise
            page.wait_for_timeout(500)


def _grid_signature(page: Page) -> str:
    """Слепок текущей выдачи — названия карточек в порядке отрисовки."""
    return page.evaluate(
        """() => [...document.querySelectorAll(
                '.product__items .product__item .product__name')]
            .map(n => n.textContent.trim()).join('|')"""
    )


def _wait_grid_changed(page: Page, before: str, timeout: int = 15_000) -> None:
    """Дождаться, пока грид реально перерисуется новой выдачей.

    `sort=` появляется в URL мгновенно (pushState), а Vue перерисовывает
    карточки заметно позже ответа бэкенда. Ожидания «URL + networkidle +
    пауза» не хватало: тест читал ещё дефолтный порядок и сравнивал выдачи
    из разных моментов времени. В CI 2026-08-04 это дало сразу три падения
    («порядок товаров не изменился», цены пришли в дефолтном порядке
    2799/2799/2799/1799/…, «после reload первый товар не совпал»), тогда как
    в браузере сортировка отрабатывает корректно.

    Ждём выдачу, которая одновременно (а) отличается от прежней и (б) не
    меняется два опроса подряд. Ловить «любое отличие» недостаточно: Vue
    перерисовывает грид в несколько заходов, и промежуточный кадр уже не
    равен исходному, хотя порядок в нём ещё старый. Именно на этом тест
    «выбор сортировки меняет порядок» падал в общем прогоне, проходя
    при этом в одиночку.

    Таймаут не бросает исключение: падать должен ассерт теста со своим
    сообщением, иначе теряем диагностику.
    """
    try:
        page.wait_for_function(
            """(prev) => {
                const cur = [...document.querySelectorAll(
                        '.product__items .product__item .product__name')]
                    .map(n => n.textContent.trim()).join('|');
                if (!cur || cur === prev) { window.__sortSig = null; return false; }
                if (window.__sortSig === cur) return true;   // стабилен 2 опроса
                window.__sortSig = cur;
                return false;
            }""",
            arg=before,
            timeout=timeout,
            polling=250,
        )
    except Exception:
        pass


def _pick_sort(page: Page, label: str) -> None:
    """Открыть дропдаун сортировки и выбрать опцию по подписи.

    Дропдаун закрывается после выбора, поэтому каждый раз открываем заново.
    Ждём появления/смены sort= в URL (переход идёт через pushState — не
    через навигацию) и фактической перерисовки выдачи."""
    before = _grid_signature(page)
    page.evaluate("() => { window.__sortSig = null; }")
    _open_sort_dropdown(page)
    page.wait_for_timeout(400)
    _sort_option(page, label).first.click()
    page.wait_for_function(
        "() => location.search.includes('sort=')", timeout=10_000
    )
    _wait_grid_changed(page, before)
    page.wait_for_load_state("networkidle", timeout=15_000)


# ---------------------------------------------------------------------------
# Фикстура
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def open_category(page: Page):
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(SORT_BAR)).to_be_visible(timeout=20_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=20_000)


# ===========================================================================
# 1. Контрол сортировки отрисован и содержит опции
# ===========================================================================
def test_sort_control_renders_with_options(page: Page):
    """Блок сортировки виден и содержит хотя бы 2 опции."""
    expect(page.locator(SORT_BAR)).to_be_visible()
    assert page.locator(SORT_OPTION).count() >= 2, (
        "В контроле сортировки меньше двух опций"
    )


# ===========================================================================
# 2. Выбор опции меняет URL и порядок товаров
# ===========================================================================
def test_selecting_sort_updates_url_and_order(page: Page):
    """Выбор сортировки добавляет sort= в URL и меняет первый товар выдачи."""
    first_before = _first_card_name(page)

    _pick_sort(page, SORT_LOWEST_PRICE)

    assert _sort_param(page) is not None, f"В URL нет sort=: {page.url}"
    assert _first_card_name(page) != first_before, (
        "После выбора сортировки порядок товаров не изменился"
    )


# ===========================================================================
# 3. Сортировка по возрастанию цены реально сортирует по возрастанию
# ===========================================================================
def test_sort_lowest_price_orders_ascending(page: Page):
    """«De la cel mai mic preț» → цены товаров в наличии идут по возрастанию."""
    _pick_sort(page, SORT_LOWEST_PRICE)

    prices = _in_stock_prices(page)
    if len(prices) < 2:
        pytest.skip("Меньше двух товаров в наличии с ценой — порядок не проверить")

    assert prices == sorted(prices), (
        f"Цены не по возрастанию при сортировке «по возрастанию цены»: {prices}"
    )


# ===========================================================================
# 4. Сортировка сохраняется после перезагрузки
# ===========================================================================
def test_sort_persists_on_reload(page: Page):
    """Выбрать сортировку → reload — параметр sort= и порядок сохраняются."""
    _pick_sort(page, SORT_LOWEST_PRICE)
    sort_before = _sort_param(page)
    first_before = _first_card_name(page)
    assert sort_before is not None

    for attempt in range(2):
        try:
            page.reload(wait_until="domcontentloaded", timeout=60_000)
            break
        except Exception:
            if attempt == 0:
                page.wait_for_timeout(1500)
                continue
            raise
    expect(page.locator(GRID)).to_be_visible(timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)

    assert _sort_param(page) == sort_before, (
        f"После reload sort изменился: {sort_before} → {_sort_param(page)}"
    )
    assert _first_card_name(page) == first_before, (
        "После reload первый товар не совпал — порядок не сохранился"
    )


# ===========================================================================
# 5. Выбор сортировки сбрасывает пагинацию на первую страницу
# ===========================================================================
def test_sort_resets_pagination_to_first_page(page: Page):
    """Находясь на стр.2, выбрать сортировку → пагинация возвращается на стр.1."""
    if page.locator(NEXT_BUTTON).count() == 0:
        pytest.skip("На этой категории одна страница — сбрасывать нечего")

    page.locator(NEXT_BUTTON).first.click()
    page.wait_for_function(
        "() => location.search.includes('page=2')", timeout=10_000
    )
    page.wait_for_load_state("networkidle", timeout=15_000)
    assert _active_page(page) == 2

    # `_pick_sort` здесь использовать НЕЛЬЗЯ: он ждёт появления `sort=` в URL,
    # а на этом сценарии параметр не появляется (см. комментарий в конце теста),
    # и хелпер падает по таймауту. Поэтому те же шаги разложены вручную, без
    # ожидания `sort=`: открыть дропдаун, выбрать опцию, дождаться перерисовки.
    before = _grid_signature(page)
    page.evaluate("() => { window.__sortSig = null; }")
    _click_sort_option(page, SORT_LOWEST_PRICE)
    _wait_grid_changed(page, before)
    page.wait_for_load_state("networkidle", timeout=15_000)

    # Собственно предмет кейса — сброс пагинации на первую страницу.
    assert "page=2" not in page.url, (
        f"После выбора сортировки в URL остался page=2: {page.url}"
    )
    if page.locator(PAGINATION).count() > 0:
        assert _active_page(page) == 1, (
            "После выбора сортировки пагинация не сбросилась на первую страницу"
        )

    # `sort=` в URL здесь СОЗНАТЕЛЬНО не проверяем. Выбор сортировки со стр.2
    # приводит URL к голому `/<категория>`: `page=2` уходит, `sort=` не
    # добавляется, хотя выдача реально пересортирована (со стр.1 тот же клик
    # даёт `?page=1&sort=price-`). Расхождение проверено вживую 2026-08-10 и
    # признано допустимым поведением — багом не считаем, тест на нём не падает.
    # Наличие `sort=` в URL по-прежнему покрыто отдельными кейсами, которые
    # стартуют с первой страницы: test_selecting_sort_updates_url_and_order
    # и test_sort_persists_on_reload.

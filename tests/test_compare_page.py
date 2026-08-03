"""Тесты страницы Сравнение товаров (Qase suite 17).

Адаптировано под реальную реализацию stage.ecom.md (проверено через MCP):
- Корень страницы: `.compare__page`.
- В сайдбаре `.compare__categories` лежат ВСЕ радио-фильтры:
  сначала категории (id `radio-<subcategoryId>`), затем
  «Все параметры» (`input[name="show"][value="showAll"]`) и
  «Различия» (`input[name="show"][value="showDiff"]`).
- Таблица сравнения перевёрстана на CSS-grid (проверено 2026-08-03):
  `.compare__table > .compare__table-grid`, внутри по порядку идут карточки
  товаров `.compare__table-product` (по одной на товар), затем строки
  характеристик — `.compare__char-head` (название) и следом по одной
  `.compare__char-cell` на каждый товар. Старых `.compare__item` и
  `.compare__proprieties-item` в DOM больше нет.
- Кнопка удаления одного товара: `button.btn__delete[title="Удалить товар"]`
  внутри `.compare__table-product`.
- Кнопка «Удалить все товары» — `button.btn__link` с этим же текстом.
- Заглушка пустого списка — `.favorites__empty` с текстом
  «Нет товаров для сравнения» + кнопка «Посмотреть товары» (тоже
  `button.btn__link`); клик по ней открывает мега-меню каталога
  (`#header` получает класс `show-catalog`, body — `overflow:hidden`),
  а не редиректит на отдельную страницу.
- Сравнение хранится в localStorage["compare"] и cookie `compare` как
  JSON-массив объектов товара (содержит productId, category[], …).
"""

import re

import pytest
from playwright.sync_api import Page, expect


COMPARE_URL = "/ru/compare"
# Два товара одной категории «Портативные Partybox» — для тестов "Различия"
PRODUCT_A_URL = "/ru/product/jbl-partybox-on-the-go-2"
PRODUCT_B_URL = "/ru/product/jbl-partybox-720"
# Товар другой категории (Lifestyle) — для проверки нескольких категорий
PRODUCT_OTHER_URL = "/ru/product/klipsch-detroit"

# Кнопка сравнения на странице товара
BTN_COMPARE_PRODUCT = "button.compare__product"

# Корень
COMPARE_PAGE = ".compare__page"

# Фильтры в сайдбаре
CATEGORY_FILTER_ITEM = ".compare__categories .compare__filters-item"
INPUT_SHOW_ALL = 'input[name="show"][value="showAll"]'
INPUT_SHOW_DIFF = 'input[name="show"][value="showDiff"]'

# Строки характеристик в сравнении: заголовок строки + ячейки значений
PROP_ITEM = ".compare__char-head"
PROP_CELL = ".compare__char-cell"

# Карточки товаров
COMPARE_ITEM = ".compare__table-product"
BTN_DELETE_ONE = f'{COMPARE_ITEM} button.btn__delete[title="Удалить товар"]'

# Кнопки «Удалить все товары» и «Посмотреть товары» — обе `button.btn__link`
# в одном корне, поэтому фильтруем по тексту.

# Заглушка
EMPTY_STUB = ".favorites__empty"


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _clear_compare(page: Page):
    page.evaluate(
        """() => {
            try { localStorage.removeItem('compare'); } catch (e) {}
            document.cookie = 'compare=%5B%5D; path=/; max-age=0';
        }"""
    )


def _add_to_compare(page: Page, product_url: str):
    """Открыть страницу товара и кликнуть «Сравнение»."""
    page.goto(product_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(BTN_COMPARE_PRODUCT).first).to_be_visible(timeout=15_000)
    page.locator(BTN_COMPARE_PRODUCT).first.click()
    page.wait_for_timeout(400)


def _btn_with_text(page: Page, text_re: re.Pattern):
    """Найти button.btn__link по тексту."""
    return page.locator("button.btn__link").filter(has_text=text_re).first


@pytest.fixture
def empty_compare(page: Page):
    """Чистый стейт сравнения. Открывает /compare с пустым списком."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.context.clear_cookies()
    page.goto(COMPARE_URL, wait_until="domcontentloaded", timeout=60_000)
    _clear_compare(page)
    page.reload(wait_until="domcontentloaded")
    return page


@pytest.fixture
def two_same_category(page: Page):
    """Два товара одной категории (Партибоксы) уже добавлены, /compare открыт."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.context.clear_cookies()
    # Очищаем перед началом
    page.goto(PRODUCT_A_URL, wait_until="domcontentloaded", timeout=60_000)
    _clear_compare(page)

    _add_to_compare(page, PRODUCT_A_URL)
    _add_to_compare(page, PRODUCT_B_URL)

    page.goto(COMPARE_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(COMPARE_PAGE)).to_be_visible(timeout=15_000)
    expect(page.locator(COMPARE_ITEM).first).to_be_visible(timeout=15_000)
    return page


@pytest.fixture
def two_different_categories(page: Page):
    """Два товара РАЗНЫХ категорий: PartyBox + Klipsch (Lifestyle)."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.context.clear_cookies()
    page.goto(PRODUCT_A_URL, wait_until="domcontentloaded", timeout=60_000)
    _clear_compare(page)

    _add_to_compare(page, PRODUCT_A_URL)
    _add_to_compare(page, PRODUCT_OTHER_URL)

    page.goto(COMPARE_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(COMPARE_PAGE)).to_be_visible(timeout=15_000)
    # Дожидаемся гидрации сайдбара с радио-категориями
    page.wait_for_selector(
        ".compare__categories input[type='radio'][id^='radio-']",
        state="attached", timeout=15_000,
    )
    return page


# ===========================================================================
# Кейс 99: «Все параметры» — отображаются все характеристики, чекбокс отмечен
# ===========================================================================
def test_show_all_parameters_checked_and_props_visible(two_same_category: Page):
    """По умолчанию должно быть выбрано «Все параметры», список параметров
    непустой."""
    page = two_same_category

    show_all = page.locator(INPUT_SHOW_ALL)
    expect(show_all).to_be_checked()

    props = page.locator(PROP_ITEM)
    assert props.count() >= 1, "Ожидался хотя бы 1 параметр сравнения"


# ===========================================================================
# Кейс 100: «Различия» — отображаются только отличающиеся характеристики
# ===========================================================================
def test_show_diff_reduces_parameters(two_same_category: Page):
    """Клик по «Различия» → checkbox отмечен, число параметров уменьшается
    (выводятся только характеристики, в которых значения у товаров разные)."""
    page = two_same_category

    props_all = page.locator(PROP_ITEM).count()
    assert props_all >= 1, "Нет параметров — нечего проверять"

    # Клик по label (input перекрыт span'ом cart__checkbox)
    diff_label = page.locator(f"label:has({INPUT_SHOW_DIFF})").first
    diff_label.click()
    page.wait_for_timeout(700)

    expect(page.locator(INPUT_SHOW_DIFF)).to_be_checked()

    props_diff = page.locator(PROP_ITEM).count()
    assert props_diff < props_all, (
        f"После «Различия» параметров не стало меньше: было {props_all}, "
        f"стало {props_diff}"
    )


# ===========================================================================
# Кейс 104: Заглушка при пустом списке
# ===========================================================================
def test_empty_compare_shows_stub(empty_compare: Page):
    """На пустом /compare отображается заглушка «Нет товаров для сравнения»."""
    page = empty_compare

    expect(page.locator(EMPTY_STUB)).to_be_visible(timeout=10_000)
    expect(page.locator(EMPTY_STUB)).to_contain_text(
        re.compile(r"Нет товаров для сравнения", re.IGNORECASE)
    )
    # Карточек товаров нет
    assert page.locator(COMPARE_ITEM).count() == 0


# ===========================================================================
# Кейс 241: Отображение категорий когда товары из разных категорий
# ===========================================================================
def test_multiple_category_filters_shown(two_different_categories: Page):
    """Если в сравнении товары из разных категорий — в сайдбаре отображаются
    обе категории (минимум 2 categry radio)."""
    page = two_different_categories

    # Категории — это .compare__filters-item с input id вида radio-<число>
    cat_inputs = page.locator(".compare__categories input[type='radio'][id^='radio-']")
    count = cat_inputs.count()
    assert count >= 2, (
        f"Ожидалось ≥2 категорий-фильтров (товары разных категорий), "
        f"фактически {count}"
    )


# ===========================================================================
# Кейс 242: Кнопка «Посмотреть товары» с пустой страницы → открывается каталог
# ===========================================================================
def test_see_products_button_opens_catalog(empty_compare: Page):
    """Клик «Посмотреть товары» в заглушке → открывается мега-меню каталога
    (header получает класс `show-catalog`, body — overflow:hidden)."""
    page = empty_compare

    see_btn = _btn_with_text(page, re.compile(r"Посмотреть.*товар", re.IGNORECASE))
    expect(see_btn).to_be_visible()
    see_btn.click()
    page.wait_for_timeout(600)

    catalog_open = page.evaluate(
        """() => {
            const header = document.querySelector('#header');
            const overlay = document.querySelector('.background__overlay.show');
            return {
                hasClass: !!header && header.classList.contains('show-catalog'),
                overlayVisible: !!overlay && getComputedStyle(overlay).display !== 'none',
                bodyOverflow: getComputedStyle(document.body).overflow,
            };
        }"""
    )
    assert catalog_open["hasClass"], "У #header нет класса show-catalog"
    assert catalog_open["overlayVisible"], "Overlay каталога не показался"
    assert catalog_open["bodyOverflow"] == "hidden", (
        f"body overflow != hidden: {catalog_open['bodyOverflow']}"
    )


# ===========================================================================
# Кейс 243: Удалить все товары → пустая страница + заглушка
# ===========================================================================
def test_remove_all_compare(two_same_category: Page):
    """Клик «Удалить все товары» → 0 карточек + заглушка пустого списка."""
    page = two_same_category

    remove_all = _btn_with_text(page, re.compile(r"Удалить.*все.*товар", re.IGNORECASE))
    expect(remove_all).to_be_visible()
    remove_all.click()
    page.wait_for_timeout(800)

    expect(page.locator(COMPARE_ITEM)).to_have_count(0, timeout=10_000)
    expect(page.locator(EMPTY_STUB)).to_be_visible()
    expect(page.locator(EMPTY_STUB)).to_contain_text(
        re.compile(r"Нет товаров для сравнения", re.IGNORECASE)
    )


# ===========================================================================
# Кейс 244: Удаление одного товара (иконка корзины на карточке)
# ===========================================================================
def test_remove_one_product_from_compare(two_same_category: Page):
    """Клик `button.btn__delete[title="Удалить товар"]` на одной карточке
    → количество карточек уменьшается на 1."""
    page = two_same_category

    items_before = page.locator(COMPARE_ITEM).count()
    assert items_before >= 2

    page.locator(BTN_DELETE_ONE).first.click()
    page.wait_for_timeout(700)

    items_after = page.locator(COMPARE_ITEM).count()
    assert items_after == items_before - 1, (
        f"Карточек не уменьшилось на 1: {items_before} → {items_after}"
    )


# ===========================================================================
# Кейс 468 (ecom-3019): Переключение «Различия» не оставляет в результате
# характеристик с полностью совпадающими значениями
# ===========================================================================
def test_show_diff_keeps_only_differing_rows(two_same_category: Page):
    """В режиме «Различия» каждая видимая строка должна иметь
    как минимум 2 разных значения у разных товаров (никаких дублей строк,
    где у всех товаров одинаковое значение).

    Это адаптация ecom-3019 (мульти-значения характеристики) — в JSON
    кейс описан на одежде (Хлопок+Полиэстер vs Шёлк), на JBL Store
    таких характеристик нет, поэтому проверяем общее свойство: «Различия»
    действительно убирает идентичные строки."""
    page = two_same_category

    # Переключаемся в Различия
    page.locator(f"label:has({INPUT_SHOW_DIFF})").first.click()
    page.wait_for_timeout(700)
    expect(page.locator(INPUT_SHOW_DIFF)).to_be_checked()

    # Для каждой видимой строки характеристики ищем значения каждого товара
    # в той же строке и проверяем что они различаются.
    # Таблица — плоский grid: за каждым `.compare__char-head` идут ячейки
    # `.compare__char-cell` (по одной на товар) до следующего заголовка,
    # поэтому строку собираем обходом соседей, а не через общий контейнер.
    has_identical_row = page.evaluate(
        """() => {
            const grid = document.querySelector('.compare__table-grid');
            if (!grid) return null;
            const kids = Array.from(grid.children);
            for (let i = 0; i < kids.length; i++) {
                if (!kids[i].classList.contains('compare__char-head')) continue;
                const values = [];
                for (let j = i + 1; j < kids.length; j++) {
                    if (!kids[j].classList.contains('compare__char-cell')) break;
                    values.push((kids[j].textContent || '').trim());
                }
                const filled = values.filter(t => t.length > 0);
                if (filled.length >= 2 && new Set(filled).size === 1) {
                    return { row: kids[i].textContent.trim().slice(0, 60), values: filled };
                }
            }
            return null;
        }"""
    )
    assert has_identical_row is None, (
        f"В режиме «Различия» обнаружена строка с одинаковыми значениями: "
        f"{has_identical_row}"
    )

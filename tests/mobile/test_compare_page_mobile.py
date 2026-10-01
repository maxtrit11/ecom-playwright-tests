"""Страница Сравнение товаров — мобильная версия (зеркало tests/test_compare_page.py).

Таблица сравнения, удаление и заглушка на телефоне те же (проверено в
MCP-браузере), а вот фильтры другие:
  * бокового сайдбара с категориями и «Все параметры / Различия» не видно —
    вместо него кнопка-переключатель `.compare__mobile-trigger` с названием
    текущей категории;
  * она открывает полноэкранный поп-ап `.modal__sort.compare-cats`: категории
    с количеством товаров (`#compare-cat-mobile-<id>`), блок «Показать»
    (`#compare-view-mode-all` / `#compare-view-mode-diff`) и кнопка «Готово»;
  * выбор применяется СРАЗУ, «Готово» и крестик только закрывают поп-ап;
  * «Посмотреть товары» на пустой странице открывает мобильную шторку
    каталога `.catalog__mobile`, а не десктопное мега-меню.

Тесты, не зависящие от вёрстки (заглушка, удалить все, удалить один),
импортированы из десктопного файла целиком и идут с мобильными фикстурами.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from test_compare_page import (  # noqa: F401 — тесты собирает pytest
    COMPARE_ITEM,
    COMPARE_URL,
    EMPTY_STUB,
    PRODUCT_A_URL,
    PRODUCT_B_URL,
    PRODUCT_OTHER_URL,
    PROP_ITEM,
    _add_to_compare,
    _btn_with_text,
    _clear_compare,
    _open_compare,
    test_empty_compare_shows_stub,
    test_remove_all_compare,
    test_remove_one_product_from_compare,
)

# Мобильный переключатель категорий и поп-ап фильтров сравнения
MODE_TRIGGER = ".compare__mobile-trigger"
MODE_TRIGGER_TEXT = ".compare__mobile-trigger-text"
MODE_MODAL = ".modal__sort.show.compare-cats"
MODAL_CATEGORY = f"{MODE_MODAL} input[name='compare-category-mobile']"
MODAL_DONE = f"{MODE_MODAL} .modal__sort__btns__show-all"  # «Готово»
MODAL_CLOSE = f"{MODE_MODAL} .btn__close"
VIEW_ALL = "compare-view-mode-all"
VIEW_DIFF = "compare-view-mode-diff"

MOBILE_CATALOG = ".catalog__mobile"


# ---------------------------------------------------------------------------
# Фикстуры — как десктопные, но без принудительного 1920×1080
# ---------------------------------------------------------------------------
@pytest.fixture
def empty_compare(page: Page):
    page.context.clear_cookies()
    page.goto(COMPARE_URL, wait_until="domcontentloaded", timeout=60_000)
    _clear_compare(page)
    page.reload(wait_until="domcontentloaded")
    return page


def _compare_with(page: Page, *product_urls: str) -> Page:
    page.context.clear_cookies()
    page.goto(product_urls[0], wait_until="domcontentloaded", timeout=60_000)
    _clear_compare(page)
    for url in product_urls:
        _add_to_compare(page, url)
    _open_compare(page)
    expect(page.locator(COMPARE_ITEM).first).to_be_visible(timeout=15_000)
    return page


@pytest.fixture
def two_same_category(page: Page):
    """Два товара одной категории (Партибоксы), /compare открыт."""
    return _compare_with(page, PRODUCT_A_URL, PRODUCT_B_URL)


@pytest.fixture
def two_different_categories(page: Page):
    """Два товара разных категорий: PartyBox + Klipsch (Lifestyle)."""
    return _compare_with(page, PRODUCT_A_URL, PRODUCT_OTHER_URL)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _open_mode_modal(page: Page):
    """Тапнуть переключатель категории и дождаться поп-апа фильтров.
    Тап с повтором, пока поп-апа нет (первый тап после загрузки может
    потеряться — гонка с гидрацией)."""
    modal = page.locator(MODE_MODAL)
    for _ in range(3):
        if modal.count():
            break
        page.locator(MODE_TRIGGER).tap()
        try:
            modal.wait_for(state="visible", timeout=5_000)
            break
        except Exception:
            continue
    expect(modal).to_be_visible()
    return modal


def _choose(page: Page, input_id: str):
    """Отметить радио в поп-апе тапом по его подписи."""
    page.locator(f'{MODE_MODAL} label[for="{input_id}"]').tap()
    expect(page.locator(f"#{input_id}")).to_be_checked()


def _switch_to_diff(page: Page) -> int:
    """Включить «Различия» и дождаться, пока строк характеристик станет
    меньше. Вернуть их число «до» переключения."""
    props_all = page.locator(PROP_ITEM).count()
    _open_mode_modal(page)
    _choose(page, VIEW_DIFF)
    try:
        page.wait_for_function(
            "(n) => document.querySelectorAll('.compare__char-head').length < n",
            arg=props_all,
            timeout=10_000,
        )
    except Exception:
        pass  # решит ассерт теста
    return props_all


# ===========================================================================
# Кейс 99 (моб.): «Все параметры» выбраны по умолчанию, характеристики видны
# ===========================================================================
def test_show_all_parameters_checked_and_props_visible(two_same_category: Page):
    page = two_same_category

    expect(page.locator(PROP_ITEM).first).to_be_visible()
    _open_mode_modal(page)
    expect(page.locator(f"#{VIEW_ALL}")).to_be_checked()
    expect(page.locator(f"#{VIEW_DIFF}")).not_to_be_checked()


# ===========================================================================
# Кейс 100 (моб.): «Различия» — только отличающиеся характеристики
# ===========================================================================
def test_show_diff_reduces_parameters(two_same_category: Page):
    page = two_same_category

    props_all = _switch_to_diff(page)
    assert props_all >= 1, "Нет параметров — нечего проверять"

    props_diff = page.locator(PROP_ITEM).count()
    assert props_diff < props_all, (
        f"После «Различия» параметров не стало меньше: было {props_all}, стало {props_diff}"
    )


# ===========================================================================
# Кейс 468 (моб.): в «Различиях» нет строк с одинаковыми значениями
# ===========================================================================
def test_show_diff_keeps_only_differing_rows(two_same_category: Page):
    """Зачем и как обходим grid — см. десктопный тест."""
    page = two_same_category
    _switch_to_diff(page)
    page.locator(MODAL_DONE).tap()

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
        f"В режиме «Различия» обнаружена строка с одинаковыми значениями: {has_identical_row}"
    )


# ===========================================================================
# Кейс 241 (моб.): товары из разных категорий — в поп-апе обе категории
# ===========================================================================
def test_multiple_category_filters_shown(two_different_categories: Page):
    """В поп-апе ≥2 категории, у каждой счётчик товаров, и в сумме они дают
    всё, что лежит в сравнении."""
    page = two_different_categories
    modal = _open_mode_modal(page)

    categories = page.locator(MODAL_CATEGORY)
    assert categories.count() >= 2, (
        f"Ожидалось ≥2 категорий (товары разных категорий), фактически {categories.count()}"
    )
    counts = [int(c) for c in modal.locator(".compare-cats__count").all_inner_texts()]
    assert sum(counts) == 2, f"Счётчики категорий {counts} не дают 2 товара в сумме"


# ===========================================================================
# Моб.: выбор категории показывает её товары и меняет подпись переключателя
# ===========================================================================
def test_switch_category_shows_its_products(two_different_categories: Page):
    page = two_different_categories
    trigger_before = page.locator(MODE_TRIGGER_TEXT).inner_text().strip()
    names_before = page.locator(f"{COMPARE_ITEM} .product__name").all_inner_texts()

    _open_mode_modal(page)
    other = page.locator(f"{MODE_MODAL} .compare-cats__item").filter(
        has=page.locator("input:not(:checked)")
    ).first
    other_title = other.locator(".compare-cats__title").inner_text().strip()
    other_id = other.locator("input").get_attribute("id")
    _choose(page, other_id)
    page.locator(MODAL_DONE).tap()

    expect(page.locator(MODE_MODAL)).to_have_count(0)
    expect(page.locator(MODE_TRIGGER_TEXT)).to_have_text(other_title)
    assert other_title != trigger_before
    expect(page.locator(f"{COMPARE_ITEM} .product__name").first).to_be_visible()
    names_after = page.locator(f"{COMPARE_ITEM} .product__name").all_inner_texts()
    assert names_after and set(names_after).isdisjoint(names_before), (
        f"После смены категории остались товары прежней: {names_before} → {names_after}"
    )


# ===========================================================================
# Моб.: поп-ап фильтров закрывается крестиком, выбор при этом сохраняется
# ===========================================================================
def test_mode_modal_closes_by_x_keeping_choice(two_same_category: Page):
    page = two_same_category
    _switch_to_diff(page)

    page.locator(MODAL_CLOSE).tap()

    expect(page.locator(MODE_MODAL)).to_have_count(0)
    _open_mode_modal(page)
    expect(page.locator(f"#{VIEW_DIFF}")).to_be_checked()


# ===========================================================================
# Кейс 242 (моб.): «Посмотреть товары» с пустой страницы открывает каталог
# ===========================================================================
def test_see_products_button_opens_catalog(empty_compare: Page):
    """На телефоне кнопка открывает мобильную шторку каталога (а не
    мега-меню шапки, как на десктопе)."""
    page = empty_compare

    see_btn = _btn_with_text(page, re.compile(r"Посмотреть.*товар", re.IGNORECASE))
    expect(see_btn).to_be_visible(timeout=10_000)
    see_btn.tap()

    catalog = page.locator(MOBILE_CATALOG)
    expect(catalog).to_have_class(re.compile(r"\bshow\b"))
    expect(catalog).to_be_in_viewport()
    expect(page.locator("body")).to_have_css("overflow", "hidden")

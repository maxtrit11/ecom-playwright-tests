"""Листинг товаров — мобильная версия (зеркало tests/test_product_listing.py).

Что на телефоне иначе (проверено 30.09.2026 в MCP-браузере на ширине 412 и
в эмуляции Pixel 7, /ru/serie-partybox):
  * плитка — 2 товара в ряду (на десктопе 3), список — 1;
  * переключатель вида — ОДНА видимая кнопка-тумблер
    (`.view-type__button[title="Посмотреть в виде списка"]`): тап включает
    список, повторный тап возвращает плитку. Кнопка плитки
    `.view-type__button--grid` в DOM есть, но всегда скрыта — десктопный
    кейс 249, который жмёт её, на телефоне не воспроизводится;
  * фильтры — в поп-апе «Фильтры» (см. mobile/test_category_filters_mobile.py);
  * ЧИПОВ АКТИВНЫХ ФИЛЬТРОВ на телефоне нет: `.catalog__sort__parameters`
    в DOM рисуется, но скрыт. Вместо них — счётчик активных фильтров на
    кнопке «Фильтры» (`.filter-btn__count`, без фильтров его нет). Поэтому
    кейсы 255/256 («Очистить все» и «×» на чипе) переписаны на то, что видит
    пользователь телефона: счётчик и снятие опции в поп-апе;
  * сортировка — тот же выпадающий `.sorting-bar__list`, но у этой категории
    по умолчанию «От самой высокой цены», и `sort=` в URL бывает ещё ДО
    выбора сортировки. Ждать надо смены значения `sort`, а не его появления.

Карточка, плашка «В корзину», переход в корзину и на товар от вёрстки не
зависят — эти тесты импортированы из десктопного файла.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from mobile.test_category_filters_mobile import (
    BTN_APPLY,
    BTN_RESET,
    FILTERS_MODAL,
    _found_count,
    _open_filters,
    _panel,
    _wait_after_filter,
    _wait_found_count_changed,
)
from mobile.test_filters_pagination_mobile import _WIDEST_GROUP_JS
from test_product_listing import (  # noqa: F401 — тесты собирает pytest
    CARD,
    CATEGORY_URL,
    GRID,
    SORT_BTN,
    SORT_LIST,
    SORT_LOWEST_PRICE,
    VIEW_ACTIVE,
    _products_per_row,
    test_add_to_cart_from_listing_shows_notification,
    test_open_cart_from_listing_notification,
    test_open_product_page_from_listing_card,
)
from test_price_consistency import _bani

VIEW_TOGGLE = ".view-type__button:visible"
VIEW_LIST_TITLE = "Посмотреть в виде списка"
VIEW_GRID_TITLE = "Посмотреть в виде grid"
FILTER_BADGE = ".filter-btn .filter-btn__count"


@pytest.fixture(autouse=True)
def open_listing(page: Page):
    """Как десктопная, но без принудительного 1920×1080 — вьюпорт телефона."""
    page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(GRID)).to_be_visible(timeout=20_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=20_000)


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _toggle_view(page: Page, expected_active_title: str) -> None:
    """Тапнуть тумблер вида и дождаться нужной активной кнопки. Тап с
    повтором: первый после загрузки может потеряться (гидрация)."""
    for _ in range(3):
        page.locator(VIEW_TOGGLE).first.tap()
        try:
            expect(page.locator(VIEW_ACTIVE)).to_have_attribute(
                "title", expected_active_title, timeout=3_000
            )
            return
        except AssertionError:
            continue
    expect(page.locator(VIEW_ACTIVE)).to_have_attribute("title", expected_active_title)


def _widest_group_ids(page: Page, need: int) -> list[str]:
    """id опций самой широкой группы фильтров, по убыванию числа товаров.

    Самая широкая — чтобы после фильтра осталось что сортировать (первая
    опция на этой категории оставляет один товар). Внутри группы опции
    объединяются по OR, поэтому вторая опция той же группы доступна и после
    первой. По id, а не по позиции: поп-ап перестраивает список групп.
    """
    plan = page.evaluate(_WIDEST_GROUP_JS)
    if not plan or len(plan["ids"]) < need:
        pytest.skip(f"Нет группы фильтров минимум с {need} опциями")
    return plan["ids"][:need]


def _tap_option(page: Page, option_id: str, checked: bool) -> None:
    """Тапнуть опцию в поп-апе и дождаться новой выдачи.

    Повторяем, только пока опция не пришла в нужное состояние: это
    переключатель, лишний тап вернул бы её обратно.
    """
    option = page.locator(f'[id="{option_id}"]')
    for _ in range(3):
        if option.is_checked() == checked:
            break
        before = _found_count(page)
        _panel(page).locator(f'label[for="{option_id}"]').tap()
        try:
            expect(option).to_be_checked(checked=checked, timeout=5_000)
        except AssertionError:
            continue
        _wait_after_filter(page)
        _wait_found_count_changed(page, before)
    expect(option).to_be_checked(checked=checked)


def _close_filters_keeping(page: Page) -> None:
    """«Готово» — закрыть поп-ап, сохранив фильтр."""
    page.locator(BTN_APPLY).tap()
    expect(page.locator(FILTERS_MODAL)).to_have_count(0, timeout=10_000)


# ===========================================================================
# Кейс 248 (моб.): Переключение на табличный вид
# ===========================================================================
def test_switch_to_list_view(page: Page):
    """Тап по тумблеру вида выстраивает товары по одному в ряд."""
    assert _products_per_row(page) > 1, (
        "Листинг открылся не в плиточном виде — переключать не с чего"
    )

    _toggle_view(page, VIEW_LIST_TITLE)

    per_row = _products_per_row(page)
    assert per_row == 1, f"В табличном виде в ряду {per_row} товаров вместо 1"


# ===========================================================================
# Кейс 249 (моб.): Возврат к плиточному виду
# ===========================================================================
def test_switch_back_to_grid_view(page: Page):
    """Повторный тап по тумблеру возвращает плитку — 2 товара в ряд."""
    _toggle_view(page, VIEW_LIST_TITLE)
    assert _products_per_row(page) == 1, "Табличный вид не включился"

    _toggle_view(page, VIEW_GRID_TITLE)

    per_row = _products_per_row(page)
    assert per_row == 2, f"В плиточном виде на телефоне в ряду {per_row} товаров вместо 2"


# ===========================================================================
# Кейс 255 (моб.): Счётчик активных фильтров и сброс всех
# ===========================================================================
def test_filter_badge_counts_and_reset_clears(page: Page):
    """Отмеченная опция → на кнопке «Фильтры» счётчик «1»; «Сбросить» в
    поп-апе снимает фильтр, счётчик пропадает, выдача возвращается."""
    expect(page.locator(FILTER_BADGE)).to_have_count(0)

    _open_filters(page)
    found_initial = _found_count(page)
    option_id = _widest_group_ids(page, 1)[0]
    _tap_option(page, option_id, checked=True)
    _close_filters_keeping(page)

    expect(page.locator(FILTER_BADGE)).to_have_text("1", timeout=10_000)

    _open_filters(page)
    page.locator(BTN_RESET).tap()
    _wait_after_filter(page)
    found = _wait_found_count_changed(page, _found_count(page))
    page.locator(f"{FILTERS_MODAL} .btn__close").tap()
    expect(page.locator(FILTERS_MODAL)).to_have_count(0, timeout=10_000)

    expect(page.locator(FILTER_BADGE)).to_have_count(0, timeout=10_000)
    assert "filters=" not in page.url, f"В URL остались фильтры: {page.url}"
    assert found == found_initial, f"Выдача не вернулась к исходной: {found} против {found_initial}"


# ===========================================================================
# Кейс 256 (моб.): Снятие одного фильтра из нескольких
# ===========================================================================
def test_remove_single_filter_keeps_others(page: Page):
    """Две опции → счётчик «2»; снять одну → «1», фильтр в URL остался."""
    _open_filters(page)
    first_id, second_id = _widest_group_ids(page, 2)
    _tap_option(page, first_id, checked=True)
    _tap_option(page, second_id, checked=True)
    _close_filters_keeping(page)
    expect(page.locator(FILTER_BADGE)).to_have_text("2", timeout=10_000)

    _open_filters(page)
    _tap_option(page, first_id, checked=False)
    expect(page.locator(f'[id="{second_id}"]')).to_be_checked()
    _close_filters_keeping(page)

    expect(page.locator(FILTER_BADGE)).to_have_text("1", timeout=10_000)
    assert "filters=" in page.url, f"Вместе с одной опцией слетели все фильтры: {page.url}"


# ===========================================================================
# Кейс 257 (моб.): Сортировка при активных фильтрах
# ===========================================================================
def test_sorting_keeps_active_filters(page: Page):
    """Сортировка применяется к отфильтрованной выдаче и не сбрасывает фильтр.

    Опции одной группы (OR) добираем, пока в выдаче не станет минимум 4
    товара. На двух товарах проверка порядка беззубая: на 30.09.2026 самая
    широкая опция оставляла два Club 120, и «По названию» давало тот же
    порядок, что «по цене», — мутант с неверной сортировкой проходил.

    Ограничение данных: в /ru/serie-partybox «По названию» и на большей
    выборке совпадает с «От самой низкой цены» (Encore Essential → Club 120 →
    Club 120 White → Stage 320), так что подмену именно на сортировку по
    имени тест не отличит. Подмену на «По названию в обратном порядке» —
    ловит (проверено мутацией).
    """
    _open_filters(page)
    plan = page.evaluate(_WIDEST_GROUP_JS)
    if not plan:
        pytest.skip("В поп-апе нет чекбокс-фильтров")
    applied = 0
    for option_id in plan["ids"]:
        _tap_option(page, option_id, checked=True)
        applied += 1
        if _found_count(page) >= 4:
            break
    _close_filters_keeping(page)

    expect(page.locator(FILTER_BADGE)).to_have_text(str(applied), timeout=10_000)
    filters_before = re.search(r"filters=[^&]+", page.url).group()
    cards_before = page.locator(CARD).count()
    if cards_before < 3:
        pytest.skip(f"В отфильтрованной выдаче {cards_before} товара — порядок не проверить")

    sort_before = page.evaluate("() => new URLSearchParams(location.search).get('sort')")
    page.locator(SORT_BTN).tap()
    expect(page.locator(f"{SORT_LIST}.show")).to_be_visible(timeout=10_000)
    page.locator(SORT_LIST).get_by_text(SORT_LOWEST_PRICE, exact=True).tap()
    # `sort=` бывает в URL ещё до выбора — ждём смены значения
    page.wait_for_function(
        "(before) => new URLSearchParams(location.search).get('sort') !== before",
        arg=sort_before,
        timeout=20_000,
    )

    # 1. Фильтр не сбросился
    expect(page.locator(FILTER_BADGE)).to_have_text(str(applied), timeout=10_000)
    assert filters_before in page.url, f"Сортировка потеряла фильтр {filters_before}: {page.url}"

    # 2. Сортировка применилась к той же выдаче и по возрастанию цены.
    # Цены дробные («6 649.05 MDL») — считаем в банях, иначе склейка цифр
    # даёт 664905 и порядок проверяется неверно.
    expect(page.locator(CARD)).to_have_count(cards_before, timeout=15_000)
    # Грид перерисовывается позже смены URL — ждём упорядоченную выдачу, но
    # без исключения: если порядок так и не сложился, пусть падает ассерт
    # ниже с понятным списком цен.
    try:
        page.wait_for_function(
            """() => {
                const v = [...document.querySelectorAll('.product__items .product__item .product__prices')]
                    .map(p => parseFloat(p.innerText.split('MDL')[0].replace(/[^\\d.,]/g, '').replace(',', '.')))
                    .filter(x => !isNaN(x));
                return v.every((x, i) => i === 0 || v[i - 1] <= x);
            }""",
            timeout=15_000,
        )
    except Exception:
        pass
    texts = page.locator(f"{GRID} {CARD} .product__prices").all_inner_texts()
    prices = [_bani(t) for t in texts if "MDL" in t]
    assert len(prices) >= 2, f"В отфильтрованной выдаче меньше двух цен: {texts}"
    assert prices == sorted(prices), f"Цены не по возрастанию: {[p / 100 for p in prices]}"

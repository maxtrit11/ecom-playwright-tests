"""Сортировка на странице категории — мобильная версия (зеркало
tests/test_sorting.py).

Сортировка на телефоне та же, что на десктопе (проверено 30.09.2026 в
эмуляции Pixel 7, /ro/jbl-tune): `.sorting-bar` над выдачей, кнопка-стрелка
`.sorting-bar__btn` (18×22) раскрывает абсолютный список
`.sorting-bar__list.show` поверх карточек, выбор меняет `sort=` в URL,
пагинация та же. Поэтому тесты импортированы из десктопного файла и идут
с мобильной фикстурой `open_category` (без принудительного 1920×1080).

Кроме кейса 5 (сброс пагинации): десктопный после перехода на стр.2 ждёт
`networkidle`, а мобильная категория со стр.2 не затихает и за 15 с (как в
mobile/test_filters_pagination_mobile.py) — тест падал по таймауту на
исправной странице. Мобильная версия ждёт по факту: активная кнопка
страницы и перерисовка выдачи.

Своё — только то, чего на десктопе не бывает: на узком экране список может
вылезти за край или уйти под липкий нижний бар, и тогда пункт виден, но
тап по нему достаётся другому элементу.
"""

import pytest
from playwright.sync_api import Page, expect

from test_sorting import (  # noqa: F401 — тесты собирает pytest
    CARD,
    CATEGORY_URL,
    SORT_BAR,
    SORT_BTN,
    SORT_LIST,
    SORT_OPTION,
    test_sort_control_renders_with_options,
    test_selecting_sort_updates_url_and_order,
    test_sort_lowest_price_orders_ascending,
    test_sort_highest_price_orders_descending,
    test_sort_by_name_orders_alphabetically,
    test_sort_by_name_reversed_orders_backwards,
    test_sort_persists_on_reload,
)
from test_sorting import (
    ACTIVE_BUTTON,
    NEXT_BUTTON,
    PAGINATION,
    SORT_LOWEST_PRICE,
    _active_page,
    _click_sort_option,
    _grid_signature,
    _wait_grid_changed,
)


@pytest.fixture(autouse=True)
def open_category(page: Page):
    """Как десктопная, но без принудительного 1920×1080 — вьюпорт телефона."""
    page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(SORT_BAR)).to_be_visible(timeout=20_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=20_000)


def _wait_active_page(page: Page, number: int) -> None:
    expect(page.locator(ACTIVE_BUTTON).first).to_have_text(str(number), timeout=15_000)


# ===========================================================================
# 5 (моб.). Выбор сортировки сбрасывает пагинацию на первую страницу
# ===========================================================================
def test_sort_resets_pagination_to_first_page(page: Page):
    """Со стр.2 выбрать сортировку → стр.1, `page=2` из URL уходит.

    `sort=` в URL здесь не проверяется — решение юзера, см. десктопный тест.
    """
    next_btn = page.locator(NEXT_BUTTON).first
    expect(next_btn).to_be_visible(timeout=15_000)

    before = _grid_signature(page)
    page.evaluate("() => { window.__sortSig = null; }")
    next_btn.tap()
    page.wait_for_function("() => location.search.includes('page=2')", timeout=10_000)
    _wait_active_page(page, 2)
    _wait_grid_changed(page, before)

    before = _grid_signature(page)
    page.evaluate("() => { window.__sortSig = null; }")
    _click_sort_option(page, SORT_LOWEST_PRICE)
    _wait_grid_changed(page, before)

    assert "page=2" not in page.url, (
        f"После выбора сортировки в URL остался page=2: {page.url}"
    )
    expect(page.locator(PAGINATION).first).to_be_visible(timeout=10_000)
    _wait_active_page(page, 1)
    assert _active_page(page) == 1, (
        "После выбора сортировки пагинация не сбросилась на первую страницу"
    )


# ===========================================================================
# 6 (моб.). Раскрытый список сортировки целиком на экране и тапается
# ===========================================================================
def test_sort_list_fits_screen_and_options_are_tappable(page: Page):
    """Тап по стрелке раскрывает список; он не выходит за края экрана, а в
    центре каждого пункта сверху лежит сам пункт (не нижний бар, не карточка).
    """
    list_shown = page.locator(f"{SORT_LIST}.show")
    for _ in range(3):
        page.locator(SORT_BTN).tap()
        try:
            expect(list_shown).to_be_visible(timeout=3_000)
            break
        except AssertionError:
            continue
    expect(list_shown).to_be_visible()
    list_shown.scroll_into_view_if_needed()

    options = page.locator(SORT_OPTION)
    assert options.count() >= 2, "В списке сортировки меньше двух пунктов"

    width = page.viewport_size["width"]
    box = list_shown.bounding_box()
    assert box["x"] >= 0 and box["x"] + box["width"] <= width + 1, (
        f"Список сортировки выходит за край экрана шириной {width}: {box}"
    )

    blocked = page.evaluate(
        """(sel) => [...document.querySelectorAll(sel)].map(o => {
                const r = o.getBoundingClientRect();
                const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                return (top && (top === o || o.contains(top))) ? null
                    : `${o.textContent.trim()} ← ${top ? top.className || top.tagName : 'вне экрана'}`;
            }).filter(Boolean)""",
        SORT_OPTION,
    )
    assert not blocked, f"Пункты сортировки перекрыты другими элементами: {blocked}"

"""Фильтры + пагинация — мобильная версия (зеркало tests/test_filters_pagination.py).

Пагинация на телефоне та же (`.pagination`, кнопки страниц и стрелка «далее»,
проверено в MCP-браузере), а фильтры — в полноэкранном поп-апе «Filtre»
(подробно — в mobile/test_category_filters_mobile.py). Отсюда сценарий:
открыть поп-ап → отметить опцию (применяется сразу) → «EFECTUAT» закрывает
поп-ап → смотрим пагинацию под ним.

Хелперы пагинации взяты из десктопного файла, работа с поп-апом фильтров —
из мобильного файла фильтров.
"""

import pytest
from playwright.sync_api import Page, expect

from mobile.test_category_filters_mobile import (
    BTN_APPLY,
    BTN_CLOSE,
    FILTER_BTN,
    FILTERS_MODAL,
    _apply_first_checkbox,
    _found_count,
    _open_filters,
    _panel,
    _wait_after_filter,
    _wait_found_count_changed,
)
from test_filters_pagination import (
    CARD,
    CATEGORY_URL,
    NEXT_BUTTON,
    PAGINATION,
    _active_page,
    _first_card_key,
    _last_page_number,
    _present,
    _wait_active_page,
    _wait_first_card_changed,
    _wait_last_page,
)

# «Самая широкая» группа чекбоксов — тот же расчёт, что в десктопном
# `_WIDEST_GROUP_JS`, только корень — поп-ап, а не сайдбар, и опции
# возвращаются стабильными id инпутов, а не номерами позиций: мобильный поп-ап
# после первой отмеченной опции ПЕРЕСТРАИВАЕТ список групп, и «группа №6»
# начинает указывать на другую группу. Второй тап уходил в чужую группу
# (в URL два разных ключа `15:…,263581:…` — между группами AND), выдача не
# росла, и тест уходил в ложный skip (проверено пробой в эмуляции Pixel 7).
_WIDEST_GROUP_JS = """
() => {
    const root = document.querySelector('.modal__sort.show');
    if (!root) return null;
    const groups = [...root.querySelectorAll('.filters-vertical__content__params__item')];
    let best = null;
    groups.forEach(g => {
        const boxes = [...g.querySelectorAll(
            '.filters-vertical__content__params__item__content__checkboxes__item')];
        const opts = boxes.map(b => {
            const m = (b.textContent || '').match(/\\((\\d+)\\)/);
            const input = b.querySelector('input');
            return { n: m ? parseInt(m[1]) : 0, id: input && input.id };
        });
        const total = opts.reduce((a, o) => a + o.n, 0);
        if (!best || total > best.total) {
            const ids = opts.filter(o => o.n > 0 && o.id)
                .sort((a, b) => b.n - a.n).map(o => o.id);
            best = { ids, total };
        }
    });
    return best && best.ids.length ? best : null;
}
"""


# ---------------------------------------------------------------------------
# Фикстура и хелперы
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def open_category(page: Page):
    page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=20_000)
    expect(page.locator(FILTER_BTN)).to_be_visible(timeout=20_000)


def _require_pages(page: Page) -> None:
    if not _present(page.locator(PAGINATION)) or _last_page_number(page) < 2:
        pytest.skip("На этой категории меньше двух страниц пагинации")


def _close_filters(page: Page) -> None:
    """Закрыть поп-ап. «EFECTUAT» (фильтр остаётся), а если ни одна опция не
    отмечена — она `disabled` и тап не принимает, тогда крестиком."""
    apply_btn = page.locator(BTN_APPLY)
    if "disabled" in (apply_btn.get_attribute("class") or ""):
        page.locator(BTN_CLOSE).tap()
    else:
        apply_btn.tap()
    expect(page.locator(FILTERS_MODAL)).to_have_count(0)


def _next_page(page: Page, target: int) -> None:
    """Перейти стрелкой «далее» и дождаться смены страницы по факту.

    Десктопный `_go_to_page` в конце ждёт networkidle, а на мобильной странице
    сеть за 15 с так и не затихает — ждём то, что видно: активную кнопку
    страницы и смену первой карточки."""
    before = _first_card_key(page)
    page.locator(NEXT_BUTTON).first.tap()
    _wait_active_page(page, target)
    _wait_first_card_changed(page, before)


def _apply_filter_until_multipage(page: Page) -> bool:
    """Отмечать опции самой широкой группы (внутри группы — OR), пока выдаче
    не станет мало одной страницы. Зачем так — см. десктопный хелпер."""
    plan = page.evaluate(_WIDEST_GROUP_JS)
    if not plan:
        return False
    for option_id in plan["ids"]:
        option = page.locator(f'[id="{option_id}"]')
        if not option.count() or option.is_disabled():
            continue
        before = _found_count(page)
        _panel(page).locator(f'label[for="{option_id}"]').tap()
        page.wait_for_function("() => location.search.includes('filters=')", timeout=10_000)
        _wait_after_filter(page)
        found = _wait_found_count_changed(page, before)
        # Пагинация под поп-апом перерисовывается вслед за счётчиком
        if found > page.locator(CARD).count() and _wait_last_page(page, 2, timeout=5_000) >= 2:
            return True
    return False


# ===========================================================================
# 1 (моб.). Фильтр, применённый со 2-й страницы, сбрасывает на 1-ю
# ===========================================================================
def test_applying_filter_resets_to_first_page(page: Page):
    _require_pages(page)

    _next_page(page, 2)
    assert _active_page(page) == 2, "Не удалось перейти на страницу 2"

    _open_filters(page)
    _apply_first_checkbox(page)
    assert "page=2" not in page.url, f"После применения фильтра в URL остался page=2: {page.url}"

    _close_filters(page)
    # Фильтр мог сузить выдачу до одной страницы — тогда пагинации нет, и это ОК.
    if page.locator(PAGINATION).count() > 0 and _last_page_number(page) > 1:
        assert _active_page(page) == 1, "После фильтра пагинация не сбросилась на 1-ю страницу"


# ===========================================================================
# 2 (моб.). Фильтр не увеличивает ни число результатов, ни число страниц
# ===========================================================================
def test_filter_updates_result_count_and_page_structure(page: Page):
    _require_pages(page)
    pages_before = _last_page_number(page)

    _open_filters(page)
    _, count_before, count_after = _apply_first_checkbox(page)
    _close_filters(page)
    pages_after = _last_page_number(page) if page.locator(PAGINATION).count() else 1

    assert count_after <= count_before, (
        f"После фильтра число результатов выросло: {count_before} → {count_after}"
    )
    assert pages_after <= pages_before, (
        f"После фильтра число страниц выросло: {pages_before} → {pages_after}"
    )


# ===========================================================================
# 3 (моб.). Пагинация работает внутри отфильтрованной выдачи
# ===========================================================================
def test_pagination_works_within_filtered_results(page: Page):
    _require_pages(page)

    _open_filters(page)
    if not _apply_filter_until_multipage(page):
        pytest.skip(
            "Ни одна комбинация чекбоксов одной группы не оставляет больше "
            "одной страницы — пагинацию внутри фильтра не проверить"
        )
    _close_filters(page)

    _next_page(page, 2)

    assert _active_page(page) == 2, "Внутри фильтра не удалось перейти на стр.2"
    assert "filters=" in page.url, f"При пагинации внутри фильтра потерялся filters=: {page.url}"
    assert "page=2" in page.url, f"В URL нет page=2: {page.url}"


# ===========================================================================
# 4 (моб.). Снятие фильтра восстанавливает исходную пагинацию
# ===========================================================================
def test_removing_filter_restores_pagination(page: Page):
    _require_pages(page)
    pages_before = _last_page_number(page)

    _open_filters(page)
    option_id, _, _ = _apply_first_checkbox(page)

    page.locator(f'{FILTERS_MODAL} label[for="{option_id}"]').tap()
    page.wait_for_function("() => !location.search.match(/filters=\\d/)", timeout=10_000)
    _wait_after_filter(page)
    _close_filters(page)

    pages_after = _wait_last_page(page, pages_before)
    assert pages_after == pages_before, (
        f"После снятия фильтра число страниц не восстановилось: {pages_before} → {pages_after}"
    )

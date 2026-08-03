"""Тесты взаимодействия фильтров и пагинации (category-agnostic).

Проверяют, что фильтры и пагинация работают согласованно: применение фильтра
сбрасывает пагинацию на первую страницу, меняет число результатов и структуру
страниц; пагинация продолжает работать внутри отфильтрованной выдачи.

URL категории передаётся через `CATEGORY_URL` (по умолчанию `/ro/jbl-tune` —
категория, у которой есть И фильтры, И >1 страницы пагинации).

Запуск на другой категории:
    CATEGORY_URL=/ro/some-category pytest tests/test_filters_pagination.py
    или (Windows PowerShell)
    $env:CATEGORY_URL='/ro/some-category'; pytest tests/test_filters_pagination.py

Тесты пропускаются (`pytest.skip`), если на категории нет чекбокс-фильтров
или всего одна страница пагинации — это нормально.
"""

import os
import re

import pytest
from playwright.sync_api import Locator, Page, expect


# URL категории — должен иметь и фильтры, и многостраничную пагинацию.
CATEGORY_URL = os.environ.get("CATEGORY_URL", "/ro/jbl-tune")


# ---------------------------------------------------------------------------
# Селекторы фильтров (из test_category_filters.py)
# ---------------------------------------------------------------------------
# `.filters-vertical` на странице ДВА: сайдбар фильтров и блок ссылок на
# подкатегории (`--subcategory`) с такими же BEM-детьми. Отсекаем второй по
# модификатору и всё внутреннее ищем от сайдбара — см. test_category_filters.py.
FILTERS_SIDEBAR = ".filters-vertical:not(.filters-vertical--subcategory)"
FILTER_GROUP = ".filters-vertical__content__params__item"
CHECKBOX_ITEM = ".filters-vertical__content__params__item__content__checkboxes__item"
CHECKBOX_LABEL = f"{CHECKBOX_ITEM} label"
FOUND_GOODS = ".filters-vertical__header__found-goods"

# ---------------------------------------------------------------------------
# Селекторы пагинации/грида (из test_pagination.py)
# ---------------------------------------------------------------------------
GRID = ".product__items"
CARD = ".product__item"
PAGINATION = ".pagination"
PAGE_BUTTON = ".pagination__button"
ACTIVE_BUTTON = ".pagination__button.active"
NEXT_ARROW = ".pagination__button-arrow--next"
NEXT_BUTTON = f"{PAGE_BUTTON}:has({NEXT_ARROW})"
_NUM_RE = re.compile(r"^\s*\d+\s*$")


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _sidebar(page: Page) -> Locator:
    """Настоящий сайдбар фильтров (не блок ссылок на подкатегории)."""
    return page.locator(FILTERS_SIDEBAR)


def _present(loc: Locator, count: int = 1, timeout: int = 10_000) -> bool:
    """Дождаться, что элементов `loc` стало >= `count`.

    Голый `.count()` не ждёт, а сайдбар и пагинация доезжают уже после
    гидрации — мгновенная проверка даёт ложный skip, и тест молча ничего
    не проверяет (в изоляции проходит, в полном прогоне скипается)."""
    try:
        loc.nth(count - 1).wait_for(state="attached", timeout=timeout)
        return True
    except Exception:
        return False


def _found_count(page: Page) -> int:
    """Число из счётчика «Produse găsite: N»."""
    text = _sidebar(page).locator(FOUND_GOODS).text_content() or ""
    nums = re.findall(r"\d+", text)
    return int(nums[0]) if nums else -1


def _active_page(page: Page) -> int:
    txt = page.locator(ACTIVE_BUTTON).first.text_content() or ""
    m = re.search(r"\d+", txt)
    return int(m.group()) if m else -1


def _number_buttons(page: Page) -> Locator:
    return page.locator(PAGE_BUTTON).filter(has_text=_NUM_RE)


def _page_button(page: Page, n: int) -> Locator:
    return page.locator(PAGE_BUTTON).filter(has_text=re.compile(rf"^\s*{n}\s*$"))


def _last_page_number(page: Page) -> int:
    nums = []
    btns = _number_buttons(page)
    for i in range(btns.count()):
        t = btns.nth(i).text_content() or ""
        m = re.search(r"\d+", t)
        if m:
            nums.append(int(m.group()))
    return max(nums) if nums else 1


def _first_card_key(page: Page) -> str | None:
    return page.evaluate(
        """() => {
            const grid = document.querySelector('.product__items');
            const card = grid && grid.querySelector('.product__item');
            if (!card) return null;
            const a = [...card.querySelectorAll('a[href*="/product/"]')]
                .map(x => x.getAttribute('href'))
                .find(h => h && !h.includes('scrollTo'));
            return a || card.textContent.replace(/\\s+/g, ' ').trim().slice(0, 40);
        }"""
    )


def _wait_active_page(page: Page, n: int, timeout: int = 15_000) -> None:
    page.wait_for_function(
        """(n) => {
            const b = document.querySelector('.pagination__button.active');
            return !!b && b.textContent.trim() === String(n);
        }""",
        arg=n,
        timeout=timeout,
    )


def _wait_first_card_changed(page: Page, before_key: str | None,
                             timeout: int = 15_000) -> None:
    page.wait_for_function(
        """(before) => {
            const grid = document.querySelector('.product__items');
            const card = grid && grid.querySelector('.product__item');
            if (!card) return false;
            const a = [...card.querySelectorAll('a[href*="/product/"]')]
                .map(x => x.getAttribute('href'))
                .find(h => h && !h.includes('scrollTo'));
            const key = a || card.textContent.replace(/\\s+/g, ' ').trim().slice(0, 40);
            return !!key && key !== before;
        }""",
        arg=before_key,
        timeout=timeout,
    )


def _wait_after_filter(page: Page) -> None:
    """Дождаться пересчёта выдачи бекендом и ре-рендера Vue."""
    page.wait_for_load_state("networkidle", timeout=15_000)
    page.wait_for_timeout(500)


def _go_to_page(page: Page, action, target: int) -> None:
    before_key = _first_card_key(page)
    action()
    _wait_active_page(page, target)
    _wait_first_card_changed(page, before_key)
    page.wait_for_load_state("networkidle", timeout=15_000)


def _first_checkbox_label(page: Page) -> Locator | None:
    """Первый чекбокс-фильтр (label) на странице, или None."""
    if not _present(_sidebar(page).locator(CHECKBOX_ITEM)):
        return None
    groups = _sidebar(page).locator(FILTER_GROUP)
    for i in range(groups.count()):
        g = groups.nth(i)
        if g.locator(CHECKBOX_ITEM).count() >= 1:
            return g.locator(CHECKBOX_LABEL).first
    return None


_WIDEST_GROUP_JS = """
() => {
    const sb = document.querySelector('.filters-vertical:not(.filters-vertical--subcategory)');
    if (!sb) return null;
    const groups = [...sb.querySelectorAll('.filters-vertical__content__params__item')];
    let best = null;
    groups.forEach((g, gi) => {
        const boxes = [...g.querySelectorAll(
            '.filters-vertical__content__params__item__content__checkboxes__item')];
        const counts = boxes.map(b => {
            const m = (b.textContent || '').match(/\\((\\d+)\\)/);
            return m ? parseInt(m[1]) : 0;
        });
        const total = counts.reduce((a, b) => a + b, 0);
        if (!best || total > best.total) {
            const order = counts
                .map((n, i) => ({ n, i }))
                .filter(x => x.n > 0)
                .sort((a, b) => b.n - a.n)
                .map(x => x.i);
            best = { groupIndex: gi, boxIndexes: order, total };
        }
    });
    return best && best.boxIndexes.length ? best : null;
}
"""


def _apply_filter_until_multipage(page: Page) -> bool:
    """Набрать фильтром выборку, которой хватает больше чем на одну страницу.

    Одиночный чекбокс на этой категории всегда сужает выдачу до одной страницы
    (31 товар, 15 на страницу, самый «толстый» чекбокс — 13), из-за чего кейс
    уходил в вечный skip. Внутри одной группы фильтры работают по OR, поэтому
    отмечаем несколько чекбоксов самой широкой группы, пока страниц не станет
    больше одной (проверено вживую: 5 чекбоксов «GREUTATE» → 21 товар, 2 стр.).

    Между группами действует AND — брать чекбоксы из разных групп нельзя,
    выборка будет только сужаться (см. заметку в test_category_filters.py).
    """
    plan = page.evaluate(_WIDEST_GROUP_JS)
    if not plan:
        return False

    labels = _sidebar(page).locator(FILTER_GROUP).nth(plan["groupIndex"]).locator(CHECKBOX_LABEL)
    for idx in plan["boxIndexes"]:
        if idx >= labels.count():
            continue
        found_before = _found_count(page)
        labels.nth(idx).evaluate("el => el.click()")
        page.wait_for_function(
            "() => location.search.includes('filters=')", timeout=10_000
        )
        _wait_after_filter(page)
        # Счётчик «Produse găsite» пересчитывается заметно позже ответа сети
        # (вживую: 31 → 21 через ~3 с). Пока он не изменился, в DOM висит
        # пагинация от ПРЕЖНЕЙ выборки — читать её нельзя, иначе тест то
        # уходит в ложный skip, то пытается открыть несуществующую стр.2.
        try:
            page.wait_for_function(
                """(before) => {
                    const el = document.querySelector(
                        '.filters-vertical__header__found-goods');
                    if (!el) return false;
                    const m = (el.textContent || '').match(/\\d+/);
                    return !!m && parseInt(m[0]) !== before;
                }""",
                arg=found_before,
                timeout=10_000,
            )
        except Exception:
            pass
        page.wait_for_timeout(400)

        # Страниц больше одной — и по пагинации, и по счётчику против
        # фактического числа карточек на странице.
        if (
            _last_page_number(page) >= 2
            and page.locator(NEXT_BUTTON).count() > 0
            and _found_count(page) > page.locator(CARD).count()
        ):
            return True
    return False


def _require_filters_and_pages(page: Page) -> Locator:
    """Скип, если нет чекбокс-фильтров или одной страницы мало.
    Возвращает локатор первого чекбокса."""
    if not _present(page.locator(PAGINATION)) or _last_page_number(page) < 2:
        pytest.skip("На этой категории меньше двух страниц пагинации")
    label = _first_checkbox_label(page)
    if label is None:
        pytest.skip("На этой категории нет чекбокс-фильтров")
    return label


# ---------------------------------------------------------------------------
# Фикстура
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def open_category(page: Page):
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(_sidebar(page)).to_be_visible(timeout=20_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=20_000)


# ===========================================================================
# 1. Применение фильтра со 2-й страницы сбрасывает пагинацию на 1-ю
# ===========================================================================
def test_applying_filter_resets_to_first_page(page: Page):
    """Находясь на стр.2, применить фильтр → пагинация возвращается на стр.1."""
    label = _require_filters_and_pages(page)

    # Перейти на страницу 2
    _go_to_page(page, lambda: page.locator(NEXT_BUTTON).first.click(), target=2)
    assert _active_page(page) == 2, "Не удалось перейти на страницу 2"

    # Применить фильтр
    label.evaluate("el => el.click()")
    page.wait_for_function(
        "() => location.search.includes('filters=')", timeout=10_000
    )
    _wait_after_filter(page)

    # Сброс на первую страницу: в URL не должно остаться page=2.
    assert "page=2" not in page.url, (
        f"После применения фильтра в URL остался page=2: {page.url}"
    )
    # Если после фильтра пагинация осталась (страниц >1) — активна именно стр.1.
    # Если фильтр сузил выдачу до одной страницы — пагинация исчезает, и это ОК.
    if page.locator(PAGINATION).count() > 0 and _last_page_number(page) > 1:
        assert _active_page(page) == 1, (
            "После применения фильтра пагинация не сбросилась на первую страницу"
        )


# ===========================================================================
# 2. Фильтр меняет число результатов и структуру пагинации
# ===========================================================================
def test_filter_updates_result_count_and_page_structure(page: Page):
    """Применение фильтра не увеличивает число результатов и число страниц."""
    label = _require_filters_and_pages(page)

    count_before = _found_count(page)
    pages_before = _last_page_number(page)

    label.evaluate("el => el.click()")
    page.wait_for_function(
        "() => location.search.includes('filters=')", timeout=10_000
    )
    _wait_after_filter(page)

    count_after = _found_count(page)
    pages_after = _last_page_number(page)

    assert count_after <= count_before, (
        f"После фильтра число результатов выросло: {count_before} → {count_after}"
    )
    assert pages_after <= pages_before, (
        f"После фильтра число страниц выросло: {pages_before} → {pages_after}"
    )


# ===========================================================================
# 3. Пагинация работает внутри отфильтрованной выдачи
# ===========================================================================
def test_pagination_works_within_filtered_results(page: Page):
    """После применения фильтра, если страниц всё ещё >1 — переход на стр.2
    работает и фильтр в URL сохраняется."""
    _require_filters_and_pages(page)

    if not _apply_filter_until_multipage(page):
        pytest.skip(
            "Ни одна комбинация чекбоксов одной группы не оставляет больше "
            "одной страницы — пагинацию внутри фильтра не проверить"
        )

    _go_to_page(page, lambda: page.locator(NEXT_BUTTON).first.click(), target=2)

    assert _active_page(page) == 2, "Внутри фильтра не удалось перейти на стр.2"
    assert "filters=" in page.url, (
        f"При пагинации внутри фильтра потерялся filters=: {page.url}"
    )
    assert "page=2" in page.url, f"В URL нет page=2: {page.url}"


# ===========================================================================
# 4. Снятие фильтра восстанавливает исходную пагинацию
# ===========================================================================
def test_removing_filter_restores_pagination(page: Page):
    """Применить → снять фильтр: число страниц возвращается к исходному."""
    label = _require_filters_and_pages(page)

    pages_before = _last_page_number(page)
    label_id = label.get_attribute("for")
    assert label_id, "У чекбокса нет for-атрибута для повторного клика"

    # Применить
    label.evaluate("el => el.click()")
    page.wait_for_function(
        "() => location.search.includes('filters=')", timeout=10_000
    )
    _wait_after_filter(page)
    page.wait_for_timeout(800)

    # Снять тот же чекбокс по стабильному id
    page.locator(f'label[for="{label_id}"]').first.evaluate("el => el.click()")
    page.wait_for_function(
        "() => !location.search.match(/filters=\\d/)", timeout=10_000
    )
    _wait_after_filter(page)

    pages_after = _last_page_number(page)
    assert pages_after == pages_before, (
        f"После снятия фильтра число страниц не восстановилось: "
        f"{pages_before} → {pages_after}"
    )

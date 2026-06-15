"""Тесты пагинации на странице категории (category-agnostic).

Не привязаны к конкретной категории и не зависят от количества страниц или
товаров. URL категории передаётся через переменную окружения `CATEGORY_URL`
(по умолчанию `/ro/actiuni-jbl` — категория с >1 страницы пагинации).

Запуск на другой категории:
    CATEGORY_URL=/ro/some-category pytest tests/test_pagination.py
    или (Windows PowerShell)
    $env:CATEGORY_URL='/ro/some-category'; pytest tests/test_pagination.py

Все тесты опираются на структурные селекторы вёрстки (.product__items,
.pagination*, стрелки --next/--prev) и должны работать на любой категории с
этой же шаблонной разметкой. Категория с одной страницей (нет пагинации)
вызывает `pytest.skip` — это нормально.

Особенности фронта (Nuxt/Vue SPA):
  — Пагинация — это <button>, а не <a>; переход идёт через pushState,
    поэтому ждём не через wait_for_url, а через wait_for_function.
  — Грид (.product__items) перерисовывается асинхронно: после клика URL и
    активная кнопка меняются раньше, чем приедет новый список товаров,
    поэтому ждём, пока реально сменится первый товар в гриде.
  — На первой странице нет кнопки «назад», на последней — нет «вперёд».
"""

import os
import re

import pytest
from playwright.sync_api import Locator, Page, expect


# URL категории — можно переопределить через env var.
CATEGORY_URL = os.environ.get("CATEGORY_URL", "/ro/actiuni-jbl")


# ---------------------------------------------------------------------------
# Селекторы (структурные — не зависят от категории и языка интерфейса)
# ---------------------------------------------------------------------------
GRID = ".product__items"
CARD = ".product__item"

PAGINATION = ".pagination"
PAGE_ITEM = ".pagination__item"
PAGE_BUTTON = ".pagination__button"
ACTIVE_BUTTON = ".pagination__button.active"
NEXT_ARROW = ".pagination__button-arrow--next"
PREV_ARROW = ".pagination__button-arrow--prev"

# Кнопки «вперёд/назад» определяем по стрелке (не по тексту) — это работает
# и на ro, и на ru версии сайта.
NEXT_BUTTON = f"{PAGE_BUTTON}:has({NEXT_ARROW})"
PREV_BUTTON = f"{PAGE_BUTTON}:has({PREV_ARROW})"

# Числовая кнопка-страница: текст = только цифры, без стрелки.
_NUM_RE = re.compile(r"^\s*\d+\s*$")


# ---------------------------------------------------------------------------
# JS-сниппеты для чтения состояния грида (нужен один источник правды)
# ---------------------------------------------------------------------------
_JS_FIRST_KEY = """() => {
    const grid = document.querySelector('.product__items');
    if (!grid) return null;
    const card = grid.querySelector('.product__item');
    if (!card) return null;
    const a = [...card.querySelectorAll('a[href*="/product/"]')]
        .map(x => x.getAttribute('href'))
        .find(h => h && !h.includes('scrollTo'));
    return a || card.textContent.replace(/\\s+/g, ' ').trim().slice(0, 40);
}"""

_JS_ALL_KEYS = """() => {
    const grid = document.querySelector('.product__items');
    if (!grid) return [];
    return [...grid.querySelectorAll('.product__item')].map(card => {
        const a = [...card.querySelectorAll('a[href*="/product/"]')]
            .map(x => x.getAttribute('href'))
            .find(h => h && !h.includes('scrollTo'));
        return a || card.textContent.replace(/\\s+/g, ' ').trim().slice(0, 40);
    });
}"""


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _active_page(page: Page) -> int:
    """Номер активной страницы (из подсвеченной кнопки)."""
    txt = page.locator(ACTIVE_BUTTON).first.text_content() or ""
    m = re.search(r"\d+", txt)
    return int(m.group()) if m else -1


def _first_card_key(page: Page) -> str | None:
    """Стабильный идентификатор первого товара в гриде (ссылка на /product/)."""
    return page.evaluate(_JS_FIRST_KEY)


def _card_keys(page: Page) -> list[str]:
    """Идентификаторы всех товаров текущей страницы грида."""
    return page.evaluate(_JS_ALL_KEYS)


def _number_buttons(page: Page) -> Locator:
    """Числовые кнопки-страницы (1, 2, 3...), без стрелок «вперёд/назад»."""
    return page.locator(PAGE_BUTTON).filter(has_text=_NUM_RE)


def _page_button(page: Page, n: int) -> Locator:
    """Кнопка конкретного номера страницы."""
    return page.locator(PAGE_BUTTON).filter(
        has_text=re.compile(rf"^\s*{n}\s*$")
    )


def _last_page_number(page: Page) -> int:
    """Максимальный доступный номер страницы в пагинации."""
    nums = []
    btns = _number_buttons(page)
    for i in range(btns.count()):
        t = btns.nth(i).text_content() or ""
        m = re.search(r"\d+", t)
        if m:
            nums.append(int(m.group()))
    return max(nums) if nums else 1


def _wait_active_page(page: Page, n: int, timeout: int = 15_000) -> None:
    """Дождаться, пока активной станет страница с номером `n`."""
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
    """Дождаться, пока первый товар грида сменится (грид реально перерисован)."""
    page.wait_for_function(
        """(before) => {
            const grid = document.querySelector('.product__items');
            if (!grid) return false;
            const card = grid.querySelector('.product__item');
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


def _go_to_page(page: Page, action, target: int) -> None:
    """Выполнить переход (`action()` кликает) и дождаться полной отрисовки:
    сначала меняется активная страница, затем — содержимое грида."""
    before_key = _first_card_key(page)
    action()
    _wait_active_page(page, target)
    _wait_first_card_changed(page, before_key)
    page.wait_for_load_state("networkidle", timeout=15_000)


def _grid_count(page: Page) -> int:
    """Число товаров в основном гриде (не в каруселях/рекомендациях)."""
    return page.locator(GRID).locator(CARD).count()


def _require_pagination(page: Page) -> None:
    """Пропустить тест, если на категории нет пагинации (одна страница)."""
    if page.locator(PAGINATION).count() == 0:
        pytest.skip("На этой категории нет пагинации (одна страница)")


def _require_multipage(page: Page) -> None:
    """Пропустить тест, если страниц меньше двух."""
    _require_pagination(page)
    if _number_buttons(page).count() < 2 and page.locator(NEXT_BUTTON).count() == 0:
        pytest.skip("На этой категории всего одна страница пагинации")


# ---------------------------------------------------------------------------
# Фикстура: открыть категорию
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def open_category(page: Page):
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(GRID)).to_be_visible(timeout=20_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=20_000)


# ===========================================================================
# 1. Контрол пагинации отрисован
# ===========================================================================
@pytest.mark.smoke
def test_pagination_control_renders(page: Page):
    """Блок пагинации виден и содержит хотя бы одну числовую кнопку."""
    _require_pagination(page)
    expect(page.locator(PAGINATION)).to_be_visible()
    assert _number_buttons(page).count() >= 1, (
        "В пагинации нет ни одной числовой кнопки-страницы"
    )


# ===========================================================================
# 2. По умолчанию активна первая страница, кнопки «назад» нет
# ===========================================================================
def test_first_page_active_and_no_prev(page: Page):
    """На свежо открытой категории активна страница 1 и нет кнопки «назад»."""
    _require_pagination(page)
    assert _active_page(page) == 1, (
        f"При открытии категории активна не первая страница: {_active_page(page)}"
    )
    assert page.locator(PREV_BUTTON).count() == 0, (
        "На первой странице не должно быть кнопки «назад»"
    )


# ===========================================================================
# 3. Кнопка «вперёд» переводит на следующую страницу
# ===========================================================================
def test_next_button_advances_page(page: Page):
    """Клик «вперёд»: активной становится страница 2, в URL появляется page=2,
    содержимое грида меняется."""
    _require_multipage(page)
    assert _active_page(page) == 1

    _go_to_page(page, lambda: page.locator(NEXT_BUTTON).first.click(), target=2)

    assert _active_page(page) == 2, "После «вперёд» активна не вторая страница"
    assert "page=2" in page.url, f"В URL нет page=2: {page.url}"


# ===========================================================================
# 4. На разных страницах — разные товары (нет пересечения)
# ===========================================================================
def test_pages_have_distinct_products(page: Page):
    """Товары страницы 2 не пересекаются с товарами страницы 1."""
    _require_multipage(page)

    keys_p1 = _card_keys(page)
    assert keys_p1, "На первой странице не нашлось товаров"

    _go_to_page(page, lambda: page.locator(NEXT_BUTTON).first.click(), target=2)
    keys_p2 = _card_keys(page)
    assert keys_p2, "На второй странице не нашлось товаров"

    overlap = set(keys_p1) & set(keys_p2)
    assert not overlap, (
        f"Товары повторяются на стр. 1 и 2 ({len(overlap)} шт.): {list(overlap)[:3]}"
    )


# ===========================================================================
# 5. Клик по номеру страницы переводит на неё
# ===========================================================================
def test_click_page_number_navigates(page: Page):
    """Клик по числовой кнопке «2» делает активной страницу 2."""
    _require_multipage(page)
    if _number_buttons(page).count() < 2:
        pytest.skip("Меньше двух числовых кнопок-страниц")

    _go_to_page(page, lambda: _page_button(page, 2).first.click(), target=2)

    assert _active_page(page) == 2, "Клик по «2» не сделал активной страницу 2"
    assert "page=2" in page.url, f"В URL нет page=2: {page.url}"


# ===========================================================================
# 6. Кнопка «назад» возвращает на предыдущую страницу
# ===========================================================================
def test_prev_button_returns_to_previous_page(page: Page):
    """Со страницы 2 «назад» возвращает на страницу 1 с исходными товарами."""
    _require_multipage(page)

    keys_p1 = _card_keys(page)
    _go_to_page(page, lambda: page.locator(NEXT_BUTTON).first.click(), target=2)
    assert _active_page(page) == 2

    expect(page.locator(PREV_BUTTON).first).to_be_visible()
    _go_to_page(page, lambda: page.locator(PREV_BUTTON).first.click(), target=1)

    assert _active_page(page) == 1, "После «назад» активна не первая страница"
    assert _card_keys(page) == keys_p1, (
        "После возврата на страницу 1 список товаров не совпал с исходным"
    )


# ===========================================================================
# 7. Прямая ссылка ?page=2 открывает вторую страницу
# ===========================================================================
def test_deeplink_page_param_loads_page(page: Page):
    """Переход напрямую по ?page=2 открывает именно вторую страницу."""
    _require_multipage(page)

    keys_p1 = _card_keys(page)

    sep = "&" if "?" in CATEGORY_URL else "?"
    page.goto(f"{CATEGORY_URL}{sep}page=2",
              wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(GRID)).to_be_visible(timeout=20_000)
    _wait_active_page(page, 2)
    page.wait_for_load_state("networkidle", timeout=15_000)

    assert _active_page(page) == 2, "Deep-link ?page=2 не открыл вторую страницу"
    keys_p2 = _card_keys(page)
    assert keys_p2, "На deep-link странице 2 нет товаров"
    assert set(keys_p1) != set(keys_p2), (
        "Deep-link ?page=2 показал тот же набор товаров, что и страница 1"
    )


# ===========================================================================
# 8. Состояние пагинации сохраняется после перезагрузки
# ===========================================================================
def test_pagination_persists_on_reload(page: Page):
    """Перейти на страницу 2 → reload — всё ещё страница 2."""
    _require_multipage(page)

    _go_to_page(page, lambda: page.locator(NEXT_BUTTON).first.click(), target=2)
    assert "page=2" in page.url

    # Стейдж иногда отвечает 504 на первую попытку — даём один ретрай
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
    _wait_active_page(page, 2)

    assert "page=2" in page.url, f"После reload page=2 потерян: {page.url}"
    assert _active_page(page) == 2, "После reload активна не вторая страница"


# ===========================================================================
# 9. На последней странице нет кнопки «вперёд»
# ===========================================================================
def test_no_next_button_on_last_page(page: Page):
    """На последней странице пагинации кнопка «вперёд» отсутствует."""
    _require_multipage(page)

    last = _last_page_number(page)
    if last < 2:
        pytest.skip("Всего одна страница — последняя совпадает с первой")

    _go_to_page(page, lambda: _page_button(page, last).first.click(), target=last)

    assert _active_page(page) == last
    assert page.locator(NEXT_BUTTON).count() == 0, (
        "На последней странице не должно быть кнопки «вперёд»"
    )


# ===========================================================================
# 10. Невалидный номер страницы в URL обрабатывается без падения
# ===========================================================================
@pytest.mark.parametrize("bad_page", ["999999", "0", "abc"])
def test_invalid_page_param_handled_gracefully(page: Page, bad_page: str):
    """?page=<мусор> не роняет страницу: грид виден, товары есть, активна
    валидная страница (для слишком большого номера — клампится к последней,
    для 0/нечисла — к первой)."""
    _require_pagination(page)

    last = _last_page_number(page)

    sep = "&" if "?" in CATEGORY_URL else "?"
    page.goto(f"{CATEGORY_URL}{sep}page={bad_page}",
              wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(GRID)).to_be_visible(timeout=20_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=20_000)
    page.wait_for_load_state("networkidle", timeout=15_000)

    assert _grid_count(page) > 0, (
        f"При ?page={bad_page} грид пустой — страница сломалась"
    )
    # Если активная страница определена — она должна быть валидной (1..last)
    active = _active_page(page)
    if active != -1:
        assert 1 <= active <= last, (
            f"При ?page={bad_page} активна невалидная страница: {active}"
        )


# ===========================================================================
# 11. Размер страницы постоянен (полные страницы одинаковы, последняя — остаток)
# ===========================================================================
def test_page_size_is_consistent(page: Page):
    """Число товаров на не-последних страницах одинаково; на последней — не больше."""
    _require_multipage(page)

    last = _last_page_number(page)
    if last < 2:
        pytest.skip("Всего одна страница")

    counts: dict[int, int] = {1: _grid_count(page)}
    for n in range(2, last + 1):
        _go_to_page(page, lambda n=n: _page_button(page, n).first.click(), target=n)
        counts[n] = _grid_count(page)

    page_size = counts[1]
    assert page_size > 0, "На первой странице нет товаров"

    # Все страницы, кроме последней, должны быть «полными» (== page_size)
    for n in range(1, last):
        assert counts[n] == page_size, (
            f"Размер страницы непостоянен: стр.{n}={counts[n]}, стр.1={page_size}. "
            f"Все: {counts}"
        )
    # Последняя — остаток, не больше полной страницы и не пустая
    assert 0 < counts[last] <= page_size, (
        f"Размер последней страницы вне диапазона 1..{page_size}: {counts}"
    )


# ===========================================================================
# 12. Кнопка «назад» браузера возвращает к предыдущей странице
# ===========================================================================
# Ранее тут был баг (browser back: URL/пагинация = стр.1, но грид оставался на
# товарах стр.2). Проверено через MCP 2026-06-15 — починено: back корректно
# синхронизирует и URL, и подсветку, и сам список товаров. xfail снят.
def test_browser_back_navigates_to_previous_page(page: Page):
    """Перейти на стр.2 → нажать «назад» в браузере → должна вернуться стр.1
    и в URL, и в подсветке пагинации, И в самом списке товаров."""
    _require_multipage(page)

    keys_p1 = _card_keys(page)
    _go_to_page(page, lambda: page.locator(NEXT_BUTTON).first.click(), target=2)
    assert _active_page(page) == 2

    page.go_back()
    _wait_active_page(page, 1)
    page.wait_for_load_state("networkidle", timeout=15_000)

    assert _active_page(page) == 1, "После browser back активна не первая страница"
    assert _card_keys(page) == keys_p1, (
        "После browser back грид не вернулся к товарам страницы 1"
    )

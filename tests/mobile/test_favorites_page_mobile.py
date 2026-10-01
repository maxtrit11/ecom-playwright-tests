"""Страница Избранные — мобильная версия (зеркало tests/test_favorites_page.py).

Что на телефоне иначе (проверено в эмуляции Pixel 7):
  * ссылки «Избранное» со счётчиком в шапке нет — она в нижнем баре
    (`.mobile__bar .bar__item-favorites`); число — в `span` внутри, при нуле
    он скрыт (`display: none`);
  * наведения нет (`hover: none`), поэтому сердечки на карточках видны сразу,
    без hover, и нажимаются тапом;
  * кнопка «Избранное» на странице товара и тост «Товар был добавлен в
    избранное» — те же, что на десктопе.

Тесты, не завязанные на шапку и наведение (тост, несколько карточек, переход
на товар, заглушка), импортированы из десктопного файла целиком и идут с
мобильной фикстурой `page`.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from conftest import _HIDE_OVERLAYS_SCRIPT
from test_favorites_page import (  # noqa: F401 — тесты собирает pytest
    BTN_REMOVE_ALL,
    CATALOG_CARD_WITH_HEART,
    CARD_HEART_ACTIVE,
    EMPTY_STUB,
    FAV_CARDS_TIMEOUT,
    FAVORITES_URL,
    HOME_URL,
    PRODUCT_CARD,
    PRODUCT_URL,
    _add_to_favorites,
    _clear_favorites,
    test_open_favorites_via_notification_after_add,
    test_multiple_favorites_render_correctly,
    test_open_product_page_from_favorites_card,
    test_empty_favorites_shows_stub,
)

BAR_FAV_LINK = ".mobile__bar .bar__item-favorites"
BAR_FAV_COUNT = f"{BAR_FAV_LINK} span"

_BAR_COUNT_JS = """
    () => {
        const s = document.querySelector('.mobile__bar .bar__item-favorites span');
        if (!s || getComputedStyle(s).display === 'none') return 0;
        const m = (s.textContent || '').match(/\\d+/);
        return m ? parseInt(m[0]) : 0;
    }
"""


@pytest.fixture
def page(page: Page):
    """Как десктопная, но без принудительного 1920×1080: чистое избранное,
    открыта страница товара.

    Гашение оверлеев подключаем ЗДЕСЬ, до первой навигации. Эта фикстура
    переопределяет `page`, поэтому автоматическая `_suppress_overlays` из
    conftest получает страницу уже после goto/reload ниже — и на этой первой
    странице cookie-баннер остаётся. На телефоне он во всю ширину внизу и
    перекрывал ссылку тоста «Открыть избранное» и сердечки.
    """
    page.add_init_script(_HIDE_OVERLAYS_SCRIPT)
    page.context.clear_cookies()
    page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=60_000)
    _clear_favorites(page)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("h1")).to_be_visible(timeout=15_000)
    expect(page.locator(BAR_FAV_LINK)).to_be_visible()
    return page


def _bar_count(page: Page) -> int:
    """Число на «Избранном» в нижнем баре (0, если счётчик скрыт)."""
    return page.evaluate(_BAR_COUNT_JS)


def _wait_bar_count(page: Page, expected: int, timeout: int = 10_000) -> int:
    """Дождаться нужного числа в баре и вернуть то, что там на самом деле
    (без исключения — падать должен ассерт теста)."""
    try:
        page.wait_for_function(
            f"(n) => ({_BAR_COUNT_JS})() === n", arg=expected, timeout=timeout
        )
    except Exception:
        pass
    return _bar_count(page)


def _open_favorites_with_product(page: Page):
    _add_to_favorites(page)
    assert _wait_bar_count(page, 1) == 1, "Товар не добавился в избранное"
    page.goto(FAVORITES_URL, wait_until="domcontentloaded")
    expect(page.locator(PRODUCT_CARD).first).to_be_visible(timeout=FAV_CARDS_TIMEOUT)


# ===========================================================================
# Кейс 260 (моб.): Добавление в Избранное со страницы товара
# ===========================================================================
def test_add_to_favorites_from_product_page(page: Page):
    """Кнопка «Избранное» на товаре → счётчик в нижнем баре +1 и становится
    виден, кнопка получает is-active."""
    before = _bar_count(page)
    expect(page.locator(BAR_FAV_COUNT)).to_be_hidden()

    btn = _add_to_favorites(page)

    after = _wait_bar_count(page, before + 1)
    assert after == before + 1, f"Счётчик избранного в баре не вырос: {before} → {after}"
    expect(page.locator(BAR_FAV_COUNT)).to_be_visible()
    expect(btn).to_have_class(re.compile(r"\bis-active\b"))


# ===========================================================================
# Кейс 261 (моб.): Удаление с /favorites тапом по сердечку на карточке
# ===========================================================================
def test_remove_from_favorites_via_card_heart(page: Page):
    """Сердечко на карточке видно без наведения; тап по нему убирает
    карточку, счётчик в баре уменьшается."""
    _open_favorites_with_product(page)
    before = _bar_count(page)

    heart = page.locator(CARD_HEART_ACTIVE).first
    expect(heart).to_be_visible()  # без hover — на телефоне его нет
    heart.tap()

    expect(page.locator(PRODUCT_CARD)).to_have_count(0, timeout=10_000)
    after = _wait_bar_count(page, before - 1)
    assert after == before - 1, f"Счётчик избранного не уменьшился: {before} → {after}"


# ===========================================================================
# Кейс 262 (моб.): Открытие Избранного через нижний бар
# ===========================================================================
def test_open_favorites_page_via_bottom_bar(page: Page):
    _add_to_favorites(page)

    link = page.locator(BAR_FAV_LINK)
    expect(link).to_have_attribute("href", re.compile(r"/favorites$"))
    link.tap()

    page.wait_for_url(re.compile(r"/favorites$"), timeout=10_000)
    expect(page.locator(PRODUCT_CARD).first).to_be_visible(timeout=FAV_CARDS_TIMEOUT)


# ===========================================================================
# Кейс 264 (моб.): Удалить все товары
# ===========================================================================
def test_remove_all_favorites(page: Page):
    _open_favorites_with_product(page)

    remove_all = page.locator(BTN_REMOVE_ALL).first
    expect(remove_all).to_be_visible()
    remove_all.tap()

    expect(page.locator(PRODUCT_CARD)).to_have_count(0, timeout=10_000)
    assert _wait_bar_count(page, 0) == 0, "Счётчик в баре не обнулился"
    expect(page.locator(BAR_FAV_COUNT)).to_be_hidden()
    expect(page.locator(EMPTY_STUB)).to_be_visible()


# ===========================================================================
# Кейс 265 (моб.): Добавление в Избранное с карточки каталога на главной
# ===========================================================================
def test_add_to_favorites_from_catalog_card(page: Page):
    """Сердечко на карточке каталога видно сразу (без наведения) → тап →
    is-active, счётчик в баре +1. Почему карточку выбираем с сердечком, а не
    `.first`, — см. десктопный тест."""
    page.goto(HOME_URL, wait_until="domcontentloaded")
    # Каталог монтируется лениво при прокрутке — прокручиваем, пока не появится
    page.evaluate(
        """async (sel) => {
            for (let y = 0; y < 8000; y += 600) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 400));
                if (document.querySelector(sel)) return;
            }
        }""",
        CATALOG_CARD_WITH_HEART,
    )
    card = page.locator(CATALOG_CARD_WITH_HEART).first
    card.scroll_into_view_if_needed()
    heart = card.locator(".btn__wrap[title*='избранн' i]").first
    expect(heart).to_be_visible(timeout=10_000)  # без hover

    before = _bar_count(page)
    # Тап до гидрации теряется — повторяем, но только пока сердечко НЕ активно:
    # оно переключатель, лишний тап снял бы товар обратно.
    for _ in range(3):
        if "is-active" in (heart.get_attribute("class") or ""):
            break
        heart.tap()
        try:
            expect(heart).to_have_class(re.compile(r"\bis-active\b"), timeout=3_000)
            break
        except AssertionError:
            page.wait_for_timeout(500)

    expect(heart).to_have_class(re.compile(r"\bis-active\b"))
    after = _wait_bar_count(page, before + 1)
    assert after == before + 1, f"Счётчик избранного не вырос: {before} → {after}"

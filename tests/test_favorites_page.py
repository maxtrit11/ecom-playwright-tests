"""Тесты страницы Избранные (Qase suite 50: Страница Избранные).

Адаптировано под реальную реализацию stage.ecom.md (проверено через MCP):
- На карточке /favorites сердечко — это `<div class="btn__wrap is-active">`
  (не `<button>`), клик по нему удаляет товар.
- При добавлении в избранное появляется тост `.notification.favorite.show`
  внизу страницы с текстом «Товар был добавлен в избранное» и ссылкой
  `a.btn__ntf` («Открыть избранное») → ведёт на /ru/favorites.
  В JSON кейс 263 называет это «поп-апом» — на сайте это тост-нотификация.
- Избранные хранятся в localStorage["favorites"] и cookie `favorites` как
  JSON-массив ID товаров.
"""

import re

import pytest
from playwright.sync_api import Page, expect


PRODUCT_URL = "/ru/product/klipsch-detroit"
SECOND_PRODUCT_URL = "/ru/product/jbl-partybox-on-the-go-2"
FAVORITES_URL = "/ru/favorites"
HOME_URL = "/ru"

# Кнопка «Избранное» на странице товара
BTN_FAV_PRODUCT = "button.save__product"

# Ссылка/счётчик «Избранное» в шапке
HEADER_FAV_LINK = "a.btn__action.favorite__link"

# Карточка товара в каталоге / на /favorites
PRODUCT_CARD = ".product__item"
# Сердечко на карточке (это div, не button)
CARD_HEART = ".product__item .btn__wrap[title*='избранн' i]"
CARD_HEART_ACTIVE = ".product__item .btn__wrap.is-active"

# «Удалить все товары из избранного» — `button.btn__delete` есть ещё внутри
# скрытой формы поиска, поэтому фильтруем по title
BTN_REMOVE_ALL = "button.btn__delete[title*='Удалить все']"

# Тост-нотификация, появляется после клика на избранное
NOTIFICATION = ".notification.favorite.show"
NOTIFICATION_LINK = f"{NOTIFICATION} a.btn__ntf"

# Заглушка при пустом списке
EMPTY_STUB = ".favorites__empty"


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _header_fav_count(page: Page) -> int:
    text = page.locator(HEADER_FAV_LINK).first.text_content() or ""
    nums = re.findall(r"\d+", text)
    return int(nums[0]) if nums else 0


def _clear_favorites(page: Page):
    """Сбросить избранное в localStorage + cookie."""
    page.evaluate(
        """() => {
            try { localStorage.removeItem('favorites'); } catch (e) {}
            document.cookie = 'favorites=%5B%5D; path=/; max-age=0';
        }"""
    )


@pytest.fixture
def page(page: Page):
    """Стандартный page: desktop viewport, чистое избранное."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    # Очищаем cookie до первого goto
    page.context.clear_cookies()
    page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=60_000)
    _clear_favorites(page)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("h1")).to_be_visible(timeout=15_000)
    return page


# ===========================================================================
# Кейс 260: Добавление товара в Избранное со страницы товара
# ===========================================================================
def test_add_to_favorites_from_product_page(page: Page):
    """Клик на «Избранное» на странице товара → счётчик в шапке +1,
    кнопка получает класс is-active."""
    count_before = _header_fav_count(page)

    btn = page.locator(BTN_FAV_PRODUCT).first
    expect(btn).to_be_visible()
    btn.click()
    page.wait_for_timeout(800)

    count_after = _header_fav_count(page)
    assert count_after == count_before + 1, (
        f"Счётчик избранного в шапке не вырос: {count_before} → {count_after}"
    )
    expect(btn).to_have_class(re.compile(r"\bis-active\b"))


# ===========================================================================
# Кейс 261: Удаление товара со страницы /favorites через сердечко на карточке
# ===========================================================================
def test_remove_from_favorites_via_card_heart(page: Page):
    """Добавить товар → перейти на /favorites → клик по сердечку на карточке
    → карточка пропадает, счётчик в шапке уменьшается."""
    page.locator(BTN_FAV_PRODUCT).first.click()
    page.wait_for_timeout(800)
    assert _header_fav_count(page) >= 1, "Товар не добавился в избранное"

    page.goto(FAVORITES_URL, wait_until="domcontentloaded")
    expect(page.locator(PRODUCT_CARD).first).to_be_visible(timeout=10_000)
    count_before = _header_fav_count(page)

    # Hover карточки (по кейсу — кнопки появляются при наведении)
    page.locator(PRODUCT_CARD).first.hover()
    page.wait_for_timeout(300)

    # Клик по активному сердечку
    page.locator(CARD_HEART_ACTIVE).first.click()
    page.wait_for_timeout(800)

    # Карточка пропала
    expect(page.locator(PRODUCT_CARD)).to_have_count(0, timeout=10_000)
    # Счётчик уменьшился
    count_after = _header_fav_count(page)
    assert count_after == count_before - 1, (
        f"Счётчик избранного не уменьшился: {count_before} → {count_after}"
    )


# ===========================================================================
# Кейс 262: Открытие страницы Избранные через хедер
# ===========================================================================
def test_open_favorites_page_via_header(page: Page):
    """Клик на «Избранное» в шапке → переход на /ru/favorites."""
    page.locator(BTN_FAV_PRODUCT).first.click()
    page.wait_for_timeout(500)

    header_link = page.locator(HEADER_FAV_LINK).first
    expect(header_link).to_be_visible()
    expect(header_link).to_have_attribute("href", re.compile(r"/favorites$"))

    header_link.click()
    page.wait_for_url(re.compile(r"/favorites$"), timeout=10_000)
    # Дожидаемся отрисовки контента (Vue лениво рендерит)
    page.wait_for_selector(
        f"{PRODUCT_CARD}, {EMPTY_STUB}", state="attached", timeout=15_000
    )
    assert page.locator(PRODUCT_CARD).count() > 0 or page.locator(EMPTY_STUB).count() > 0


# ===========================================================================
# Кейс 263: Открытие Избранного через тост-нотификацию после добавления
# ===========================================================================
def test_open_favorites_via_notification_after_add(page: Page):
    """Клик на «Избранное» → внизу появляется тост «Товар был добавлен
    в избранное» с ссылкой «Открыть избранное» → клик по ссылке открывает
    /ru/favorites."""
    page.locator(BTN_FAV_PRODUCT).first.click()

    # Тост появляется сразу и автоматически скрывается через несколько секунд —
    # ждём именно видимости (короткое окно)
    toast = page.locator(NOTIFICATION).first
    expect(toast).to_be_visible(timeout=5_000)
    expect(toast).to_contain_text(
        re.compile(r"Товар.*добавлен.*избранн", re.IGNORECASE)
    )

    link = page.locator(NOTIFICATION_LINK).first
    expect(link).to_be_visible()
    expect(link).to_contain_text(re.compile(r"Открыть.*избранн", re.IGNORECASE))
    expect(link).to_have_attribute("href", re.compile(r"/favorites$"))

    link.click()
    page.wait_for_url(re.compile(r"/favorites$"), timeout=10_000)
    # На странице есть либо карточка добавленного товара, либо (по тайм-ауту)
    # стаб — основное проверяемое условие это сам переход
    assert page.locator(PRODUCT_CARD).count() > 0 or page.locator(EMPTY_STUB).count() > 0


# ===========================================================================
# Кейс 264: Удаление всех товаров через кнопку «Удалить все»
# ===========================================================================
def test_remove_all_favorites(page: Page):
    """Добавить товар → /favorites → клик «Удалить все товары из избранного»
    → все карточки удалены, счётчик = 0, отображается заглушка."""
    page.locator(BTN_FAV_PRODUCT).first.click()
    page.wait_for_timeout(800)

    page.goto(FAVORITES_URL, wait_until="domcontentloaded")
    expect(page.locator(PRODUCT_CARD).first).to_be_visible(timeout=10_000)

    remove_all = page.locator(BTN_REMOVE_ALL).first
    expect(remove_all).to_be_visible()
    remove_all.click()
    page.wait_for_timeout(800)

    expect(page.locator(PRODUCT_CARD)).to_have_count(0, timeout=10_000)
    assert _header_fav_count(page) == 0, "Счётчик в шапке не обнулился"
    expect(page.locator(EMPTY_STUB)).to_be_visible()


# ===========================================================================
# Кейс 265: Добавление товара в Избранное с карточки в каталоге (главная)
# ===========================================================================
def test_add_to_favorites_from_catalog_card(page: Page):
    """Hover на карточку товара в каталоге на главной → клик по сердечку
    → счётчик +1, на карточке появляется класс is-active."""
    page.goto(HOME_URL, wait_until="domcontentloaded")
    # Каталог отрисовывается Swiper-ом лениво при попадании в viewport.
    # Скроллим постепенно, чтобы триггернуть IntersectionObserver.
    page.evaluate(
        """async () => {
            for (let y = 0; y < 4000; y += 600) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 400));
                if (document.querySelectorAll('.product__item').length > 0) return;
            }
        }"""
    )
    page.wait_for_selector(PRODUCT_CARD, state="attached", timeout=15_000)
    page.wait_for_timeout(500)

    card = page.locator(PRODUCT_CARD).first
    card.scroll_into_view_if_needed()
    expect(card).to_be_visible(timeout=10_000)

    count_before = _header_fav_count(page)

    card.hover()
    page.wait_for_timeout(300)

    heart = card.locator(".btn__wrap[title*='избранн' i]")
    expect(heart.first).to_be_visible()
    heart.first.click()
    page.wait_for_timeout(800)

    count_after = _header_fav_count(page)
    assert count_after == count_before + 1, (
        f"Счётчик избранного не вырос: {count_before} → {count_after}"
    )
    # У сердечка появился класс is-active
    expect(heart.first).to_have_class(re.compile(r"\bis-active\b"))


# ===========================================================================
# Кейс 266: Корректное отображение нескольких товаров на /favorites
# ===========================================================================
def test_multiple_favorites_render_correctly(page: Page):
    """Добавить 2 разных товара → /favorites → все карточки видимы,
    имеют положительные размеры и не перекрывают друг друга."""
    # Добавляем первый товар
    page.locator(BTN_FAV_PRODUCT).first.click()
    page.wait_for_timeout(500)
    # Второй товар
    page.goto(SECOND_PRODUCT_URL, wait_until="domcontentloaded")
    expect(page.locator(BTN_FAV_PRODUCT).first).to_be_visible(timeout=10_000)
    page.locator(BTN_FAV_PRODUCT).first.click()
    page.wait_for_timeout(800)

    page.goto(FAVORITES_URL, wait_until="domcontentloaded")
    cards = page.locator(PRODUCT_CARD)
    expect(cards.first).to_be_visible(timeout=10_000)
    assert cards.count() >= 2, f"Ожидалось ≥2 карточек, фактически {cards.count()}"

    # Все карточки должны иметь положительные bbox и не перекрываться
    overlap = page.evaluate(
        """() => {
            const cards = Array.from(document.querySelectorAll('.product__item'));
            const rects = cards.map(c => c.getBoundingClientRect());

            // Все с положительной площадью
            const badRect = rects.find(r => r.width <= 0 || r.height <= 0);
            if (badRect) return { error: 'Карточка нулевого размера', rect: badRect };

            // Проверка перекрытия: для каждой пары — пересечение площадей
            for (let i = 0; i < rects.length; i++) {
                for (let j = i + 1; j < rects.length; j++) {
                    const a = rects[i], b = rects[j];
                    const overlapX = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
                    const overlapY = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
                    // Допустим перекрытие до 2 px (бордеры/тени)
                    if (overlapX > 2 && overlapY > 2) {
                        return { error: 'Карточки перекрываются', i, j };
                    }
                }
            }
            return { ok: true, count: rects.length };
        }"""
    )
    assert overlap.get("ok"), f"Ошибка отображения карточек: {overlap}"


# ===========================================================================
# Кейс 267: Переход на страницу товара через карточку из /favorites
# ===========================================================================
def test_open_product_page_from_favorites_card(page: Page):
    """Клик по карточке товара на /favorites → переход на страницу товара."""
    page.locator(BTN_FAV_PRODUCT).first.click()
    page.wait_for_timeout(800)

    page.goto(FAVORITES_URL, wait_until="domcontentloaded")
    card = page.locator(PRODUCT_CARD).first
    expect(card).to_be_visible(timeout=10_000)

    # Кликаем по ссылке внутри карточки (картинка/название ведут на /product/*)
    link = card.locator("a[href*='/product/']").first
    expect(link).to_be_visible()
    href = link.get_attribute("href")
    assert href and "/product/" in href

    link.click()
    page.wait_for_url(re.compile(r"/product/"), timeout=15_000)
    expect(page.locator("h1")).to_be_visible(timeout=10_000)


# ===========================================================================
# Кейс 269: Отображение заглушки при пустом списке
# ===========================================================================
def test_empty_favorites_shows_stub(page: Page):
    """Открыть /favorites без товаров в списке → видна заглушка
    «В списке избранных продуктов пока что ничего нет»."""
    page.goto(FAVORITES_URL, wait_until="domcontentloaded")

    expect(page.locator(EMPTY_STUB)).to_be_visible(timeout=10_000)
    expect(page.locator(EMPTY_STUB)).to_contain_text(
        re.compile(r"В списке избранных продуктов пока что ничего нет", re.IGNORECASE)
    )
    # Карточек товаров на странице нет
    assert page.locator(PRODUCT_CARD).count() == 0

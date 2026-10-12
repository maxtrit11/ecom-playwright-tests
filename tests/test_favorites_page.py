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

from conftest import wait_until


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
# ВАЖНО: «первая карточка каталога на главной» дважды оказывалась не тем, чем
# кажется, поэтому берём не `.first`, а первую карточку с сердечком внутри.
# 1) Класс `product__item` переиспользован рекламными баннерами
#    (`image-banner product__item image-banner--start`), и баннер идёт ПЕРВЫМ.
#    Внутри него нет ни сердечка, ни ссылки на товар — тест падал на
#    «element(s) not found» (проверено в браузере 2026-07-30).
# 2) Исключить баннеры мало: следом идут товары не в наличии (подарочные
#    сертификаты), у них ОБА `.btn__wrap` имеют `title="Нет в наличии"`, а
#    сердечка «Добавить в список избранных» в карточке нет вовсе. Локатор
#    сердечка был пустой → «Locator expected to be visible», хотя продукт
#    исправен: на карточке с сердечком hover проявляет его штатно
#    (проверено 2026-08-10).
CATALOG_CARD_WITH_HEART = (
    ".product__item:not(.image-banner)"
    ":has(.btn__wrap[title*='избранн' i])"
)
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

# Карточки на /favorites строятся на клиенте после гидрации (id берутся из
# localStorage, товары догружаются отдельно): локально ~5 с от начала перехода,
# в CI 10 с не хватало (прогон 36104780965).
FAV_CARDS_TIMEOUT = 20_000


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _header_fav_count(page: Page) -> int:
    text = page.locator(HEADER_FAV_LINK).first.text_content() or ""
    nums = re.findall(r"\d+", text)
    return int(nums[0]) if nums else 0


def _add_to_favorites(page: Page):
    """Добавить открытый товар в избранное, дождавшись, что состояние применилось.

    Одиночный клик сразу после загрузки карточки регулярно теряется (Vue ещё не
    навесил обработчик), и тест падал уже на следующем шаге: счётчик 0, на
    /favorites пусто. Проверено в браузере 2026-07-30 — сам сайт работает
    корректно: клик даёт `is-active`, счётчик +1, карточка на /favorites есть.
    Поэтому кликаем, пока кнопка не станет активной.
    """
    btn = page.locator(BTN_FAV_PRODUCT).first
    expect(btn).to_be_visible(timeout=15_000)
    for _ in range(3):
        btn.click()
        try:
            expect(btn).to_have_class(re.compile(r"\bis-active\b"), timeout=3_000)
            return btn
        except AssertionError:
            page.wait_for_timeout(500)
    expect(btn).to_have_class(re.compile(r"\bis-active\b"), timeout=3_000)
    return btn


def _wait_fav_count(page: Page, done) -> int:
    """Дождаться нужного значения счётчика избранного в шапке и вернуть его.

    Счётчик обновляется после ответа сервера, а не в момент смены класса
    сердечка — вместо паузы в 500-800 мс опрашиваем его по факту.
    """
    return wait_until(page, lambda: _header_fav_count(page), done)


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

    btn = _add_to_favorites(page)
    count_after = _wait_fav_count(page, lambda value: value != count_before)
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
    _add_to_favorites(page)
    # Ждём, что добавление дошло до шапки, прежде чем уходить со страницы:
    # с фиксированной паузой на /favorites приезжали раньше товара.
    assert _wait_fav_count(page, lambda value: value >= 1) >= 1, (
        "Товар не добавился в избранное"
    )

    page.goto(FAVORITES_URL, wait_until="domcontentloaded")
    expect(page.locator(PRODUCT_CARD).first).to_be_visible(timeout=FAV_CARDS_TIMEOUT)
    count_before = _header_fav_count(page)

    # Hover карточки (по кейсу — кнопки появляются при наведении)
    page.locator(PRODUCT_CARD).first.hover()

    # Клик по активному сердечку (click сам дождётся, пока оно проявится)
    page.locator(CARD_HEART_ACTIVE).first.click()

    # Карточка пропала
    expect(page.locator(PRODUCT_CARD)).to_have_count(0, timeout=10_000)
    # Счётчик уменьшился
    count_after = _wait_fav_count(page, lambda value: value != count_before)
    assert count_after == count_before - 1, (
        f"Счётчик избранного не уменьшился: {count_before} → {count_after}"
    )


# ===========================================================================
# Кейс 262: Открытие страницы Избранные через хедер
# ===========================================================================
def test_open_favorites_page_via_header(page: Page):
    """Клик на «Избранное» в шапке → переход на /ru/favorites."""
    _add_to_favorites(page)
    _wait_fav_count(page, lambda value: value >= 1)

    header_link = page.locator(HEADER_FAV_LINK).first
    expect(header_link).to_be_visible()
    expect(header_link).to_have_attribute("href", re.compile(r"/favorites$"))

    header_link.click()
    page.wait_for_url(re.compile(r"/favorites$"), timeout=10_000)
    # Только что добавленный товар должен быть на странице. Прежнее «карточка
    # ИЛИ заглушка пустого списка» засчитывало и пустое избранное — то есть
    # тест зеленел, даже если товар до /favorites не доехал.
    expect(page.locator(PRODUCT_CARD).first).to_be_visible(timeout=FAV_CARDS_TIMEOUT)


# ===========================================================================
# Кейс 263: Открытие Избранного через тост-нотификацию после добавления
# ===========================================================================
def test_open_favorites_via_notification_after_add(page: Page):
    """Клик на «Избранное» → внизу появляется тост «Товар был добавлен
    в избранное» с ссылкой «Открыть избранное» → клик по ссылке открывает
    /ru/favorites."""
    _add_to_favorites(page)

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
    # Контент рисуется Vue уже ПОСЛЕ смены URL — ждём карточку, а не считаем
    # мгновенно. И ждём именно карточку: товар только что добавлен, а прежнее
    # «карточка ИЛИ заглушка» засчитывало и пустой список.
    expect(page.locator(PRODUCT_CARD).first).to_be_visible(timeout=FAV_CARDS_TIMEOUT)


# ===========================================================================
# Кейс 264: Удаление всех товаров через кнопку «Удалить все»
# ===========================================================================
def test_remove_all_favorites(page: Page):
    """Добавить товар → /favorites → клик «Удалить все товары из избранного»
    → все карточки удалены, счётчик = 0, отображается заглушка."""
    _add_to_favorites(page)
    _wait_fav_count(page, lambda value: value >= 1)

    page.goto(FAVORITES_URL, wait_until="domcontentloaded")
    expect(page.locator(PRODUCT_CARD).first).to_be_visible(timeout=FAV_CARDS_TIMEOUT)

    remove_all = page.locator(BTN_REMOVE_ALL).first
    expect(remove_all).to_be_visible()
    remove_all.click()

    expect(page.locator(PRODUCT_CARD)).to_have_count(0, timeout=10_000)
    assert _wait_fav_count(page, lambda value: value == 0) == 0, (
        "Счётчик в шапке не обнулился"
    )
    expect(page.locator(EMPTY_STUB)).to_be_visible()


# ===========================================================================
# Кейс 265: Добавление товара в Избранное с карточки в каталоге (главная)
# ===========================================================================
def test_add_to_favorites_from_catalog_card(page: Page):
    """Hover на карточку товара в каталоге на главной → клик по сердечку
    → счётчик +1, на карточке появляется класс is-active."""
    page.goto(HOME_URL, wait_until="domcontentloaded")
    # Каталог отрисовывается Swiper-ом лениво при попадании в viewport.
    # Скроллим постепенно, чтобы триггернуть IntersectionObserver. Карусели
    # монтируются по очереди, а первая бывает целиком «Нет в наличии» (без
    # сердечка), поэтому листаем до карточки с сердечком, а не до любой.
    page.evaluate(
        """async (sel) => {
            for (let y = 0; y < 9000; y += 600) {
                window.scrollTo(0, y);
                await new Promise(r => setTimeout(r, 400));
                if (document.querySelector(sel)) return;
            }
        }""",
        CATALOG_CARD_WITH_HEART,
    )
    page.wait_for_selector(CATALOG_CARD_WITH_HEART, state="attached", timeout=15_000)
    # Пауза намеренная: карусель доигрывает анимацию появления, и карточка
    # «не стабильна». Без паузы (проверено 12.10.2026) клик по сердечку
    # прокручивал карточку под липкую шапку, hover слетал, сердечко пряталось —
    # 45 с таймаута. Наблюдаемого признака конца анимации у карусели нет.
    page.wait_for_timeout(500)

    card = page.locator(CATALOG_CARD_WITH_HEART).first
    card.scroll_into_view_if_needed()
    expect(card).to_be_visible(timeout=10_000)

    count_before = _header_fav_count(page)

    # Сердечко на карточке каталога скрыто и проявляется только по наведению,
    # поэтому проверять видимость до hover нельзя — локатор находится, но
    # остаётся hidden.
    heart = card.locator(".btn__wrap[title*='избранн' i]").first
    card.hover()
    expect(heart).to_be_visible()

    # Клик по сердечку в каталоге тоже теряется до гидрации — жмём, пока
    # карточка не перейдёт в is-active.
    for _ in range(3):
        card.hover()
        page.wait_for_timeout(300)  # CSS-переход проявления сердечка после hover
        heart.click()
        try:
            expect(heart).to_have_class(re.compile(r"\bis-active\b"), timeout=3_000)
            break
        except AssertionError:
            page.wait_for_timeout(500)

    count_after = _wait_fav_count(page, lambda value: value != count_before)
    assert count_after == count_before + 1, (
        f"Счётчик избранного не вырос: {count_before} → {count_after}"
    )
    # У сердечка появился класс is-active
    expect(heart).to_have_class(re.compile(r"\bis-active\b"))


# ===========================================================================
# Кейс 266: Корректное отображение нескольких товаров на /favorites
# ===========================================================================
def test_multiple_favorites_render_correctly(page: Page):
    """Добавить 2 разных товара → /favorites → все карточки видимы,
    имеют положительные размеры и не перекрывают друг друга."""
    # Добавляем первый товар
    _add_to_favorites(page)
    _wait_fav_count(page, lambda value: value >= 1)
    # Второй товар
    page.goto(SECOND_PRODUCT_URL, wait_until="domcontentloaded")
    expect(page.locator(BTN_FAV_PRODUCT).first).to_be_visible(timeout=10_000)
    _add_to_favorites(page)
    _wait_fav_count(page, lambda value: value >= 2)

    page.goto(FAVORITES_URL, wait_until="domcontentloaded")
    cards = page.locator(PRODUCT_CARD)
    expect(cards.first).to_be_visible(timeout=FAV_CARDS_TIMEOUT)
    # Карточки дорисовываются по мере догрузки товаров — ждём вторую по факту
    n_cards = wait_until(page, cards.count, lambda value: value >= 2)
    assert n_cards >= 2, f"Ожидалось ≥2 карточек, фактически {n_cards}"

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
    _add_to_favorites(page)
    _wait_fav_count(page, lambda value: value >= 1)

    page.goto(FAVORITES_URL, wait_until="domcontentloaded")
    card = page.locator(PRODUCT_CARD).first
    expect(card).to_be_visible(timeout=FAV_CARDS_TIMEOUT)

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

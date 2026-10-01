"""Главная страница — мобильная версия (зеркало tests/test_homepage.py).

Что на телефоне иначе (проверено 30.09.2026 в эмуляции Pixel 7 и в
MCP-браузере на ширине 412):
  * десктопный `<footer>` скрыт (`none-is-under-and-equal-1024`), вместо него
    `.footer__mobile` — аккордеон: секции `.footer__section` с кнопкой
    `.head__footer`, класс секции `close` ↔ `open`; у закрытой список
    ссылок схлопнут до нулевой высоты. Секции раскрываются независимо —
    открытие одной не закрывает другую;
  * в ряду карусели помещается ~2 карточки, остальные — за правым краем.
    Карточку, найденную в DOM, надо сначала пролистать в видимую часть,
    иначе тап упирается в «element is outside of the viewport»;
  * слайдер и карусели листаются свайпом — это основной жест на телефоне,
    поэтому к стрелкам и буллетам добавлены свайп-тесты;
  * стрелки каруселей и буллеты слайдера на телефоне есть и работают так же,
    как на десктопе; ленивый монтаж каруселей — тот же (см. десктопный файл).

Остальное — слайдер, заголовки и карточки каруселей, переходы на товар,
«Смотреть все», «Акции», «Бренды», «Видео-обзоры» — от вёрстки не зависит:
эти тесты импортированы из десктопного файла и идут с мобильной фикстурой.
«Акций» и «Видео-обзоров» на 30.09.2026 на главной нет ни в одной версии —
их тесты честно уходят в skip.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from test_homepage import (  # noqa: F401 — тесты собирает pytest
    ARROW_NEXT,
    BLOCKS,
    BULLET_ACTIVE_CLASS,
    BTN_ADD_CART,
    CARD,
    CARD_ACTIVE,
    CARD_NAME,
    CARD_PRICES,
    CAROUSEL,
    HOME_URL,
    NOTIFICATION,
    NOTIFICATION_BTN,
    SLIDER,
    SLIDER_BULLET,
    _active_bullet_index,
    _active_card_name,
    _carousel_with_cards,
    _first_card_matching,
    test_main_slider_shows_slides_with_bullets,
    test_slider_bullet_switches_active_slide,
    test_product_carousels_have_title_and_cards,
    test_carousel_next_arrow_scrolls_products,
    test_product_card_shows_name_and_price,
    test_product_card_opens_product_page,
    test_see_all_opens_selection_page,
    test_promo_block_links_to_all_offers,
    test_brands_block_opens_brand_page,
    test_video_block_links_to_reviews,
)

DESKTOP_FOOTER = "footer"
MOBILE_FOOTER = ".footer__mobile"
FOOTER_SECTION = f"{MOBILE_FOOTER} .footer__section"
FOOTER_HEAD = ".head__footer"
FOOTER_LINK = "a.menu__link"


@pytest.fixture(autouse=True)
def open_homepage(page: Page):
    """Как десктопная, но без принудительного 1920×1080 — вьюпорт телефона."""
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(BLOCKS).first).to_be_visible(timeout=30_000)
    yield


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _swipe(page: Page, x_from: float, x_to: float, y: float) -> None:
    """Горизонтальный свайп пальцем через CDP.

    У Playwright есть только `tap()`, жеста перетаскивания для touch нет, а
    мышиный drag Swiper в эмуляции телефона не принимает. Touch-события CDP —
    ровно то, что шлёт настоящий экран: touchStart → серия touchMove →
    touchEnd. Шаги с паузой нужны, чтобы Swiper посчитал это свайпом, а не
    тапом.
    """
    cdp = page.context.new_cdp_session(page)
    try:
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x_from, "y": y}]})
        for i in range(1, 11):
            x = x_from + (x_to - x_from) * i / 10
            cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y}]})
            page.wait_for_timeout(16)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    finally:
        cdp.detach()


def _swipe_left(page: Page, element) -> None:
    """Свайп справа налево по элементу — листает «вперёд»."""
    element.scroll_into_view_if_needed()
    box = element.bounding_box()
    width = page.viewport_size["width"]
    _swipe(page, width * 0.85, width * 0.15, box["y"] + box["height"] / 3)


def _swipe_right(page: Page, element) -> None:
    """Свайп слева направо по элементу — листает «назад»."""
    element.scroll_into_view_if_needed()
    box = element.bounding_box()
    width = page.viewport_size["width"]
    _swipe(page, width * 0.15, width * 0.85, box["y"] + box["height"] / 3)


def _bring_card_into_view(page: Page, card) -> None:
    """Пролистать карусель стрелкой, пока карточка не станет видна целиком.

    На телефоне в ряду ~2 карточки, и первая подходящая по DOM часто лежит
    за правым краем — тапнуть её нельзя.
    """
    block = card.locator(f"xpath=ancestor::*[contains(@class,'{CAROUSEL[1:]}')]").first
    width = page.viewport_size["width"]
    for _ in range(12):
        card.scroll_into_view_if_needed()
        box = card.bounding_box()
        if box and box["x"] >= 0 and box["x"] + box["width"] <= width + 1:
            return
        block.locator(ARROW_NEXT).first.tap()
        page.wait_for_timeout(700)  # анимация слайда Swiper ~300 мс
    pytest.fail("Не удалось пролистать карусель до нужной карточки")


def _requires_chromium(browser_name: str) -> None:
    if browser_name != "chromium":
        pytest.skip("Свайп эмулируется touch-событиями CDP — только Chromium")


# ===========================================================================
# Каркас страницы
# ===========================================================================
def test_homepage_opens_with_key_blocks(page: Page):
    """Главная собирается: слайдер, карусели, и внизу — МОБИЛЬНЫЙ футер.

    Десктопный `footer` на телефоне остаётся в DOM, но скрыт, поэтому
    десктопная проверка `to_be_attached` тут прошла бы и без мобильного
    футера — проверяем видимость именно `.footer__mobile`.
    """
    assert page.locator(BLOCKS).count() > 1, (
        f"На главной собрался только {page.locator(BLOCKS).count()} блок — "
        f"страница отрисовалась не полностью"
    )
    expect(page.locator(SLIDER)).to_be_visible(timeout=20_000)
    assert page.locator(CAROUSEL).count() >= 1, "На главной нет ни одной карусели товаров"

    footer = page.locator(MOBILE_FOOTER)
    footer.scroll_into_view_if_needed(timeout=20_000)
    expect(footer).to_be_visible()
    expect(page.locator(DESKTOP_FOOTER).first).to_be_hidden()


# ===========================================================================
# Свайпы
# ===========================================================================
def test_main_slider_swipe_changes_slide(page: Page, browser_name: str):
    """Свайп вправо по главному слайдеру возвращает на предыдущий слайд.

    Свайп именно НАЗАД. У слайдера автоплей: раз в 5 с он листает ВПЕРЁД и
    после тапа по буллету НЕ останавливается (`disableOnInteraction: false`).
    Проверка «после свайпа стал +1» не отличила бы свайп от автоплея, а шаг
    −1 автоплей дать не может. Слайдер не зациклен, поэтому сначала уводим
    его тапом по буллету в середину — слева должно быть куда листать.

    Индекс берём прямо перед свайпом: автоплей мог успеть сдвинуть слайд
    между тапом и свайпом, и тогда от позиции тапа шаг был бы не тот. Если
    автоплей сработал ровно во время жеста — вторая попытка.
    """
    _requires_chromium(browser_name)
    bullets = page.locator(SLIDER_BULLET)
    total = bullets.count()
    if total < 3:
        pytest.skip("В слайдере меньше трёх слайдов — не из середины листать")

    start = total // 2
    # Первый тап до гидрации теряется — повторяем, пока буллет не станет активным
    for _ in range(3):
        bullets.nth(start).tap()
        try:
            expect(bullets.nth(start)).to_have_class(
                re.compile(BULLET_ACTIVE_CLASS), timeout=3_000
            )
            break
        except AssertionError:
            continue

    seen = []
    for _ in range(2):
        before = _active_bullet_index(page)
        if before <= 0:
            pytest.fail(f"Слайдер не ушёл с первого слайда, листать назад некуда (индекс {before})")
        _swipe_right(page, page.locator(SLIDER))
        try:
            expect(bullets.nth(before - 1)).to_have_class(
                re.compile(BULLET_ACTIVE_CLASS), timeout=3_000
            )
            return
        except AssertionError:
            seen.append(f"{before} → {_active_bullet_index(page)}")
    pytest.fail("Свайп вправо не вернул на предыдущий слайд: " + "; ".join(seen))


def test_carousel_swipe_scrolls_products(page: Page, browser_name: str):
    """Свайп влево по карусели товаров меняет активную карточку."""
    _requires_chromium(browser_name)
    block = _carousel_with_cards(page, min_cards=3)
    before = _active_card_name(block)

    _swipe_left(page, block.locator(f"{CARD}{CARD_ACTIVE}").first)

    expect(block.locator(f"{CARD}{CARD_ACTIVE} {CARD_NAME}").first).not_to_have_text(
        before, timeout=10_000
    )


# ===========================================================================
# Мобильный футер-аккордеон
# ===========================================================================
def _footer_section_with_links(page: Page):
    """Первая секция футера, в которой есть ссылки на страницы стенда.

    Состав секций задаётся в админке, поэтому не привязываемся к названию.
    Внешние ссылки (соцсети, viber://) не подходят: переход увёл бы со стенда.
    """
    page.locator(MOBILE_FOOTER).scroll_into_view_if_needed(timeout=20_000)
    section = page.locator(FOOTER_SECTION).filter(
        has=page.locator(f'{FOOTER_LINK}[href^="/"]')
    ).first
    if not section.count():
        pytest.skip("В мобильном футере нет секции со ссылками на страницы сайта")
    return section


def test_footer_section_toggles_on_tap(page: Page):
    """Тап по заголовку секции раскрывает её, повторный — сворачивает."""
    section = _footer_section_with_links(page)
    head = section.locator(FOOTER_HEAD)
    link = section.locator(FOOTER_LINK).first

    expect(section).to_have_class(re.compile(r"\bclose\b"))
    expect(link).to_be_hidden()

    head.tap()
    expect(section).to_have_class(re.compile(r"\bopen\b"), timeout=5_000)
    expect(link).to_be_visible()

    head.tap()
    expect(section).to_have_class(re.compile(r"\bclose\b"), timeout=5_000)
    expect(link).to_be_hidden()


def test_footer_link_opens_page(page: Page):
    """Ссылка из раскрытой секции футера открывает страницу сайта."""
    section = _footer_section_with_links(page)
    section.locator(FOOTER_HEAD).tap()
    expect(section).to_have_class(re.compile(r"\bopen\b"), timeout=5_000)

    link = section.locator(f'{FOOTER_LINK}[href^="/"]').first
    href = link.get_attribute("href") or ""
    link.tap()

    expect(page).to_have_url(re.compile(re.escape(href) + r"/?$"), timeout=30_000)
    expect(page.locator("h1").first).to_be_visible(timeout=20_000)


# ===========================================================================
# Корзина прямо с главной
# ===========================================================================
def test_add_to_cart_from_homepage_shows_notification(page: Page):
    """«В корзину» на карточке главной показывает плашку с переходом в корзину.

    Как десктопный, но карточку сначала пролистываем в видимую часть
    карусели, а жмём тапом.
    """
    card = _first_card_matching(page, CARD_PRICES, BTN_ADD_CART)
    _bring_card_into_view(page, card)

    card.locator(BTN_ADD_CART).first.tap()

    toast = page.locator(NOTIFICATION)
    expect(toast).to_be_visible(timeout=15_000)
    expect(toast).to_contain_text(re.compile("добавлен.* в корзину", re.I))
    expect(page.locator(NOTIFICATION_BTN)).to_contain_text(
        re.compile("открыть корзину", re.I)
    )

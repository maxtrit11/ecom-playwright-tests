"""Тесты главной страницы (stage.ecom.md, локаль /ru)

Главная — точка входа сайта, а до сих пор она использовалась в суите только
как площадка: зайти и открыть поп-ап логина или меню каталога. Сами блоки не
проверялись ни разу. Этот файл закрывает витрину: слайдер, карусели товаров,
блоки «Акции», «Бренды» и «Видео-обзоры».

Разметка проверена вживую 2026-08-18 на stage.ecom.md/ru:

- Страница собрана из `.homepage-blocks__item` (27 штук). Состав и порядок
  задаются в админке, поэтому тесты НЕ привязываются ни к номеру блока, ни к
  его заголовку — ищут блок по структуре (класс контейнера, вид ссылок).

- ВАЖНО: часть блоков ведёт на ПРОД (`jblstore.md`), а не на стенд — ссылки
  проставлены контент-менеджером в админке, это не баг. Такие блоки есть в
  главном слайдере (6 ссылок из 8), в блоке категорий (все 8) и в баннерах
  (1 из 3). Переходы по ним не проверяем: тест увёл бы браузер с стенда на
  прод. Проверяем только блоки со ссылками в пределах stage: карусели
  товаров, «Акции», «Бренды», «Видео-обзоры».

- ЛЕНИВЫЙ МОНТАЖ. Карусели наполняются, только когда попадают во вьюпорт, и
  строго ПО ПОРЯДКУ. Сразу после загрузки `.products__wrapper` = 4, а
  `.product__item` = 0; после прокрутки к первому блоку — 11 карточек. Прыжок
  сразу к третьему блоку оставляет его пустым, поэтому хелпер `_reveal`
  прокручивает карусели последовательно. Считать карточки без прокрутки
  нельзя: получишь честный ноль и тест либо упадёт, либо молча уйдёт в skip.

- У товара БЕЗ СТОКА на витрине нет блока цены вообще: вместо
  `.product__prices` выводится «Нет в наличии». Это штатное поведение. Отсюда
  два следствия: (1) проверять цену надо на карточке, у которой этот блок
  есть; (2) кнопка «В корзину» у такого товара ведёт в предзаказ и плашки
  добавления не даёт — тесты корзины тоже требуют карточку со стоком.
  В верхних лентах («Подарочные сертификаты», «Популярные») на 2026-08-18
  первые карточки как раз без стока, так что `.first` тут обманчив.

- Карусель товаров — `.products__wrapper`: заголовок `.product__title`,
  карточки `.product__item` (они же `.swiper-slide`), активная —
  `.swiper-slide-active`. Стрелки лежат в `.swiper__arrows`, и суффикс класса
  у них СВОЙ для каждой карусели (`slider-arrow-next-4`), поэтому цепляем по
  `.arr[class*="next"]` внутри конкретного блока, а не по полному классу.

- Главный слайдер `.main-main-slider` — с автоплеем: индекс активного слайда
  сам ползёт, пока в него не ткнули. Поэтому исходный индекс не фиксируем, а
  считаем от текущего. После клика по буллету автоплей останавливается
  (проверено: индекс держался 4+ секунды), так что ассерт стабилен.

- Карточка на главной — как в листинге: `.product__name`, цены в
  `.product__prices`, кнопка `button.btn__add_cart`. Добавление показывает ту
  же плашку `.notification.cart.show`, что и в листинге (живёт ~3 секунды).
  Кнопки «Сравнить» на карточке главной нет — только избранное и корзина.
"""

import re

import pytest
from playwright.sync_api import Page, expect

HOME_URL = "/ru"

# Каркас страницы
BLOCKS = ".homepage-blocks__item"

# Главный слайдер
SLIDER = ".main-main-slider"
SLIDER_SLIDE = f"{SLIDER} .swiper-slide"
SLIDER_BULLET = f"{SLIDER} .swiper-pagination-bullet"
BULLET_ACTIVE_CLASS = "swiper-pagination-bullet-active"

# Карусели товаров
CAROUSEL = ".products__wrapper"
CAROUSEL_TITLE = ".product__title"
CARD = ".product__item"
CARD_NAME = ".product__name"
# В лентах попадаются слайды-баннеры (`.image-banner`) — это тот же
# `.product__item`, но без названия, цены и кнопок. Для проверок карточки
# берём только слайды с названием, иначе `.first` цепляет баннер.
PRODUCT_CARD = f"{CARD}:has({CARD_NAME})"
CARD_PRICES = ".product__prices"
CARD_ACTIVE = ".swiper-slide-active"
ARROW_NEXT = '.swiper__arrows .arr[class*="next"]'
BTN_SEE_ALL = "a.btn__secondary"

# Корзина и плашка добавления
BTN_ADD_CART = "button.btn__add_cart"
NOTIFICATION = ".notification.cart.show"
NOTIFICATION_BTN = f"{NOTIFICATION} button.btn__ntf"

# Тематические блоки
PROMO = ".promo"
PROMO_ITEM = ".promo__item"
VIDEO_BLOCK = ".top-video-checkpoint"

PRICE_RE = re.compile(r"\d[\d\s.,]*\s*MDL")


@pytest.fixture(autouse=True)
def open_homepage(page: Page):
    """Открыть главную в десктопном вьюпорте и дождаться сборки блоков.

    Ширину фиксируем: число карточек в видимой части карусели и наличие
    стрелок зависят от ширины окна.
    """
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(BLOCKS).first).to_be_visible(timeout=30_000)
    yield


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _reveal(block) -> int:
    """Проскроллить карусель во вьюпорт и дождаться её карточек.

    Карусели на главной монтируются ЛЕНИВО: пока блок не попал во вьюпорт,
    в DOM есть только заголовок со стрелками, а `.swiper-slide` нет вообще.
    Проверено 2026-08-18: сразу после загрузки `.products__wrapper` = 4, а
    `.product__item` = 0; после `scroll_into_view_if_needed` на первом блоке —
    11 карточек. Поэтому считать карточки без прокрутки нельзя: получишь
    честный ноль и тест либо упадёт, либо молча уйдёт в skip.
    """
    block.scroll_into_view_if_needed(timeout=20_000)
    try:
        expect(block.locator(CARD).first).to_be_visible(timeout=15_000)
    except AssertionError:
        return 0
    return block.locator(CARD).count()


def _carousel_with_cards(page: Page, min_cards: int = 1):
    """Первая карусель, где не меньше `min_cards` карточек.

    Перебираем, а не берём `.first`: состав блоков задаётся в админке, и
    верхняя карусель может оказаться полупустой.
    """
    carousels = page.locator(CAROUSEL)
    for i in range(carousels.count()):
        block = carousels.nth(i)
        if _reveal(block) >= min_cards:
            return block
    pytest.skip(f"На главной нет карусели минимум с {min_cards} карточками")


def _active_bullet_index(page: Page) -> int:
    """Индекс активного буллета главного слайдера."""
    bullets = page.locator(SLIDER_BULLET)
    for i in range(bullets.count()):
        cls = bullets.nth(i).get_attribute("class") or ""
        if BULLET_ACTIVE_CLASS in cls:
            return i
    return -1


def _first_card_matching(page: Page, *inner_selectors: str):
    """Первая карточка любой карусели, внутри которой есть всё перечисленное.

    Карусели перебираем ПО ПОРЯДКУ и каждую прокручиваем: ленивый монтаж
    последовательный, и прыжок сразу к третьему блоку оставляет его пустым.
    """
    conditions = "".join(f":has({s})" for s in inner_selectors)
    carousels = page.locator(CAROUSEL)
    for i in range(carousels.count()):
        block = carousels.nth(i)
        if _reveal(block) == 0:
            continue
        card = block.locator(f"{CARD}{conditions}").first
        if card.count():
            return card
    pytest.skip("На главной нет карточки, удовлетворяющей " + ", ".join(inner_selectors))


def _active_card_name(block) -> str:
    """Название товара в активном слайде карусели."""
    return (block.locator(f"{CARD}{CARD_ACTIVE} {CARD_NAME}").first.inner_text() or "").strip()


# ===========================================================================
# Каркас страницы
# ===========================================================================
def test_homepage_opens_with_key_blocks(page: Page):
    """Главная открывается и отдаёт слайдер, карусели товаров и футер."""
    assert page.locator(BLOCKS).count() > 1, (
        f"На главной собрался только {page.locator(BLOCKS).count()} блок — "
        f"страница отрисовалась не полностью"
    )
    expect(page.locator(SLIDER)).to_be_visible(timeout=20_000)
    assert page.locator(CAROUSEL).count() >= 1, "На главной нет ни одной карусели товаров"
    expect(page.locator("footer").first).to_be_attached(timeout=20_000)


# ===========================================================================
# Главный слайдер
# ===========================================================================
def test_main_slider_shows_slides_with_bullets(page: Page):
    """В слайдере есть слайды, и число буллетов совпадает с числом слайдов."""
    slides = page.locator(SLIDER_SLIDE).count()
    bullets = page.locator(SLIDER_BULLET).count()

    assert slides >= 2, f"В главном слайдере {slides} слайд(ов) — переключать нечего"
    assert bullets == slides, (
        f"Буллетов {bullets}, а слайдов {slides} — навигация не соответствует содержимому"
    )
    assert _active_bullet_index(page) >= 0, "Ни один буллет слайдера не отмечен активным"


def test_slider_bullet_switches_active_slide(page: Page):
    """Клик по буллету делает активным именно его.

    Отсчитываем цель от текущего индекса, а не берём фиксированный: у слайдера
    автоплей, и к моменту клика активным может быть любой слайд.
    """
    total = page.locator(SLIDER_BULLET).count()
    if total < 2:
        pytest.skip("В слайдере меньше двух слайдов — переключать нечего")

    target = (_active_bullet_index(page) + total // 2) % total
    page.locator(SLIDER_BULLET).nth(target).click()

    expect(page.locator(SLIDER_BULLET).nth(target)).to_have_class(
        re.compile(BULLET_ACTIVE_CLASS), timeout=15_000
    )


# ===========================================================================
# Карусели товаров
# ===========================================================================
def test_product_carousels_have_title_and_cards(page: Page):
    """У каждой карусели есть непустой заголовок и хотя бы одна карточка."""
    carousels = page.locator(CAROUSEL)
    total = carousels.count()
    assert total >= 1, "На главной нет ни одной карусели товаров"

    empty = []
    for i in range(total):
        block = carousels.nth(i)
        cards = _reveal(block)
        title = (block.locator(CAROUSEL_TITLE).first.inner_text() or "").strip()
        if not title or cards == 0:
            empty.append(f"#{i}: заголовок={title!r}, карточек={cards}")

    assert not empty, "Карусели без заголовка или без товаров: " + "; ".join(empty)


def test_carousel_next_arrow_scrolls_products(page: Page):
    """Стрелка «вперёд» листает карусель — активный товар меняется."""
    block = _carousel_with_cards(page, min_cards=2)
    arrow = block.locator(ARROW_NEXT).first
    if not arrow.count():
        pytest.skip("У карусели нет стрелок навигации (все товары помещаются в ряд)")
    # Swiper гасит стрелку классом, а не атрибутом disabled — на краю ленты
    # клик по ней ничего не сделает.
    if "swiper-button-disabled" in (arrow.get_attribute("class") or ""):
        pytest.skip("Стрелка «вперёд» неактивна — листать нечего")

    before = _active_card_name(block)
    arrow.click()

    expect(block.locator(f"{CARD}{CARD_ACTIVE} {CARD_NAME}").first).not_to_have_text(
        before, timeout=15_000
    )


def test_product_card_shows_name_and_price(page: Page):
    """Карточка товара со стоком показывает название и цену в MDL.

    Берём карточку с блоком цен намеренно: у товара без стока цены на витрине
    нет вообще (`.product__prices` отсутствует, вместо неё «Нет в наличии») —
    это штатное поведение, а не потерянная цена.
    """
    card = _first_card_matching(page, CARD_NAME, CARD_PRICES)

    name = (card.locator(CARD_NAME).first.inner_text() or "").strip()
    assert name, "У карточки товара на главной пустое название"

    prices = (card.locator(CARD_PRICES).first.inner_text() or "").strip()
    assert PRICE_RE.search(prices), (
        f"В карточке «{name}» не нашли цену в MDL, в блоке цен: {prices!r}"
    )


def test_product_card_opens_product_page(page: Page):
    """Клик по карточке открывает страницу того же товара."""
    card = _first_card_matching(page, CARD_NAME)
    name = (card.locator(CARD_NAME).first.inner_text() or "").strip()
    href = card.locator('a[href*="/product/"]').first.get_attribute("href") or ""
    slug = href.split("?")[0].rstrip("/").split("/")[-1]

    card.locator('a[href*="/product/"]').first.click()

    expect(page).to_have_url(re.compile(rf"/product/{re.escape(slug)}"), timeout=30_000)
    expect(page.locator("h1")).to_contain_text(name[:25], timeout=20_000)


def test_see_all_opens_selection_page(page: Page):
    """Кнопка «Смотреть все» у карусели открывает подборку с товарами."""
    link = page.locator(f"{CAROUSEL} {BTN_SEE_ALL}").first
    if not link.count():
        pytest.skip("Ни у одной карусели на главной нет кнопки «Смотреть все»")

    link.click()

    expect(page).not_to_have_url(re.compile(r"/ru/?$"), timeout=30_000)
    expect(page.locator(CARD).first).to_be_visible(timeout=30_000)


# ===========================================================================
# Тематические блоки
# ===========================================================================
def test_promo_block_links_to_all_offers(page: Page):
    """Блок «Акции» показывает акции и ведёт на страницу всех акций."""
    promo = page.locator(PROMO).first
    if not promo.count():
        pytest.skip("Блока «Акции» нет на главной")

    assert promo.locator(PROMO_ITEM).count() >= 1, "В блоке «Акции» не отрисовано ни одной акции"

    # Кнопка «Все акции» продублирована для мобильной вёрстки
    # (`.promo__button--mobile`), и на десктопе дубль скрыт — берём видимую,
    # иначе клик висит до таймаута на невидимом элементе.
    promo.locator('a[href*="/special-offers"]:visible').first.click()

    expect(page).to_have_url(re.compile(r"/special-offers"), timeout=30_000)
    expect(page.locator("h1")).to_be_visible(timeout=20_000)


def test_brands_block_opens_brand_page(page: Page):
    """Ссылка из блока «Бренды» открывает страницу бренда с товарами."""
    link = page.locator(f'{BLOCKS} a[href*="/brands/"]').last
    if not link.count():
        pytest.skip("На главной нет блока «Бренды»")

    href = link.get_attribute("href") or ""
    link.click()

    expect(page).to_have_url(re.compile(re.escape(href)), timeout=30_000)
    expect(page.locator("h1")).to_be_visible(timeout=20_000)
    assert page.locator(CARD).count() >= 1, f"На странице бренда {href} нет карточек товаров"


def test_video_block_links_to_reviews(page: Page):
    """Блок «Видео-обзоры» ведёт на страницу обзоров."""
    block = page.locator(VIDEO_BLOCK).first
    if not block.count():
        pytest.skip("Блока видео-обзоров нет на главной")

    block.locator('a[href*="/review"]').first.click()

    expect(page).to_have_url(re.compile(r"/review"), timeout=30_000)
    expect(page.locator("h1")).to_be_visible(timeout=20_000)


# ===========================================================================
# Корзина прямо с главной
# ===========================================================================
def test_add_to_cart_from_homepage_shows_notification(page: Page):
    """«В корзину» на карточке главной показывает плашку с переходом в корзину.

    Требуем у карточки блок цен, то есть наличие стока: у товара без стока
    кнопка ведёт в сценарий предзаказа, а не кладёт товар в корзину, и плашки
    не будет.
    """
    card = _first_card_matching(page, CARD_PRICES, BTN_ADD_CART)

    card.locator(BTN_ADD_CART).first.click()

    toast = page.locator(NOTIFICATION)
    expect(toast).to_be_visible(timeout=15_000)
    expect(toast).to_contain_text(re.compile("добавлен.* в корзину", re.I))
    expect(page.locator(NOTIFICATION_BTN)).to_contain_text(
        re.compile("открыть корзину", re.I)
    )

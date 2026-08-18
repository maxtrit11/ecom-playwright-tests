"""Тесты раздела «Акции» (stage.ecom.md, локаль /ro)

Покрывает два состояния акции — активную и завершённую — на листинге
`/ro/special-offers` и на детальной странице. Даты начала и конца задаются в
админке, поэтому конкретную акцию НЕ зашиваем: активную и завершённую ищем на
листинге по разметке. Если на стенде не осталось акции нужного вида, тест
честно скипается с понятным текстом, а не падает.

Локаль румынская: подписи состояний («Promoție expirată», «Promoția s-a
încheiat») приходят с сервера и в /ru другие. Диакритику в ассертах не
требуем — сверяем по корню слова, чтобы правка перевода не роняла тест.

Разметка проверена вживую 2026-08-18:

- ЛИСТИНГ. Карточка `.promo__item` — сама по себе ссылка (href на ней).
  У завершённой добавляется модификатор `.promo__item--expired`.

  ГЛАВНАЯ ЛОВУШКА: плашка `.promo__finished` («Promoție expirată») лежит в
  DOM у ОБЕИХ карточек, у активной она скрыта через `display: none`. Проверка
  «элемент есть» дала бы зелёный на активной акции, поэтому проверяем именно
  видимость. Обратный признак активной — блок отсчёта `.promo-countdown`
  («A rămas 30 zile»), которого у завершённой нет вовсе.

- ДЕТАЛЬНАЯ. Классы отличаются от листинга: там `promo__finished`, здесь
  `promo-finished` (через дефис) — легко перепутать.
  * активная: `.promo-countdown` с таймером «Până la sfârșitul promoției
    30z : 05o : 30m : 40s», блока `.promo-finished` нет, товары в наличии
    (на 2026-08-18 — 15 карточек);
  * завершённая: у отсчёта появляется модификатор `-expired` и текст
    «Expirată», добавляется блок `.promo-finished` с текстом «Promoția s-a
    încheiat» и кнопкой «Promoții active» на листинг, товаров ноль.
"""

import re

import pytest
from playwright.sync_api import Page, expect

OFFERS_URL = "/ro/special-offers"

# Листинг
PROMO_ITEM = ".promo__item"
PROMO_ACTIVE = f"{PROMO_ITEM}:not(.promo__item--expired)"
PROMO_EXPIRED = f"{PROMO_ITEM}.promo__item--expired"
CARD_BADGE_EXPIRED = ".promo__finished"
CARD_COUNTDOWN = ".promo-countdown"
CARD_NAME = ".promo__name"
CARD_DATE = ".promo__date"

# Детальная
DETAIL_COUNTDOWN = ".promo-countdown"
DETAIL_COUNTDOWN_EXPIRED = ".promo-countdown.-expired"
FINISHED_BLOCK = ".promo-finished"
FINISHED_TEXT = ".promo-finished__text"
FINISHED_BUTTON = ".promo-finished__button"
PRODUCT_CARD = ".product__item"

# Подписи состояний. По корню слова — без диакритики и без учёта регистра.
RE_EXPIRED = re.compile(r"expirat", re.I)
RE_FINISHED = re.compile(r"[iî]ncheiat", re.I)


@pytest.fixture(autouse=True)
def open_offers(page: Page):
    """Открыть листинг акций и дождаться карточек."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(OFFERS_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(PROMO_ITEM).first).to_be_visible(timeout=30_000)
    yield


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _card(page: Page, selector: str, kind: str):
    """Первая карточка нужного вида или skip, если такой на стенде нет."""
    card = page.locator(selector).first
    if not card.count():
        pytest.skip(f"На листинге нет ни одной {kind} акции")
    return card


def _open(page: Page, card):
    """Перейти на детальную страницу акции, вернув её название с карточки."""
    name = (card.locator(CARD_NAME).first.inner_text() or "").strip()
    card.click()
    expect(page).to_have_url(re.compile(r"/special-offers/.+"), timeout=30_000)
    return name


# ===========================================================================
# Листинг акций
# ===========================================================================
def test_offers_page_lists_promotions(page: Page):
    """Страница акций открывается и показывает карточки с названием и датой."""
    expect(page.locator("h1")).to_be_visible(timeout=20_000)

    cards = page.locator(PROMO_ITEM)
    total = cards.count()
    assert total >= 1, "На странице акций не отрисовано ни одной акции"

    broken = []
    for i in range(total):
        card = cards.nth(i)
        name = (card.locator(CARD_NAME).first.inner_text() or "").strip()
        date = (card.locator(CARD_DATE).first.inner_text() or "").strip()
        href = card.get_attribute("href") or ""
        if not name or not date or "/special-offers/" not in href:
            broken.append(f"#{i}: название={name!r}, дата={date!r}, ссылка={href!r}")

    assert not broken, "Карточки акций без названия, даты или ссылки: " + "; ".join(broken)


def test_active_promo_card_shows_countdown(page: Page):
    """У активной акции виден обратный отсчёт, плашка «истекла» скрыта."""
    card = _card(page, PROMO_ACTIVE, "активной")

    expect(card.locator(CARD_COUNTDOWN)).to_be_visible(timeout=15_000)
    # Плашка лежит в DOM и у активной карточки — проверяем именно скрытость,
    # иначе ассерт «её нет» был бы ложно-зелёным.
    expect(card.locator(CARD_BADGE_EXPIRED)).to_be_hidden(timeout=15_000)


def test_expired_promo_card_shows_expired_badge(page: Page):
    """У завершённой акции видна плашка «Promoție expirată» и нет отсчёта."""
    card = _card(page, PROMO_EXPIRED, "завершённой")

    badge = card.locator(CARD_BADGE_EXPIRED)
    expect(badge).to_be_visible(timeout=15_000)
    expect(badge).to_have_text(RE_EXPIRED)
    expect(card.locator(CARD_COUNTDOWN)).to_have_count(0)


def test_promo_card_opens_matching_promo_page(page: Page):
    """Клик по карточке открывает страницу именно этой акции."""
    card = page.locator(PROMO_ITEM).first
    name = _open(page, card)

    expect(page.locator("h1")).to_have_text(name, timeout=20_000)


# ===========================================================================
# Детальная страница: активная акция
# ===========================================================================
def test_active_promo_page_shows_countdown_and_products(page: Page):
    """Страница активной акции показывает таймер и товары, без плашки о конце."""
    _open(page, _card(page, PROMO_ACTIVE, "активной"))

    countdown = page.locator(DETAIL_COUNTDOWN)
    expect(countdown).to_be_visible(timeout=20_000)
    expect(countdown).not_to_have_class(re.compile(r"-expired"))

    expect(page.locator(FINISHED_BLOCK)).to_have_count(0)
    assert page.locator(PRODUCT_CARD).count() >= 1, (
        "На странице активной акции нет ни одного товара"
    )


# ===========================================================================
# Детальная страница: завершённая акция
# ===========================================================================
def test_expired_promo_page_shows_finished_notice(page: Page):
    """Страница завершённой акции сообщает, что акция закончилась, и без товаров."""
    _open(page, _card(page, PROMO_EXPIRED, "завершённой"))

    expect(page.locator(FINISHED_TEXT)).to_be_visible(timeout=20_000)
    expect(page.locator(FINISHED_TEXT)).to_have_text(RE_FINISHED)

    expect(page.locator(DETAIL_COUNTDOWN_EXPIRED)).to_be_visible(timeout=15_000)
    expect(page.locator(DETAIL_COUNTDOWN_EXPIRED)).to_have_text(RE_EXPIRED)

    assert page.locator(PRODUCT_CARD).count() == 0, (
        "На странице завершённой акции всё ещё показываются товары"
    )


def test_finished_promo_button_returns_to_offers(page: Page):
    """Кнопка из блока о завершении возвращает к списку активных акций."""
    _open(page, _card(page, PROMO_EXPIRED, "завершённой"))

    button = page.locator(FINISHED_BUTTON)
    expect(button).to_be_visible(timeout=20_000)
    button.click()

    expect(page).to_have_url(re.compile(r"/special-offers/?$"), timeout=30_000)
    expect(page.locator(PROMO_ITEM).first).to_be_visible(timeout=20_000)

"""Страница товара — мобильная версия (зеркало tests/test_product_page.py).

Что на телефоне иначе (проверено 30.09.2026 в эмуляции Pixel 7,
/ru/product/jbl-partybox-on-the-go-2):
  * ссылок «Сравнение N» / «Избранное N» в шапке нет (в DOM остаются скрытыми
    и тоже обновляются — читать их было бы пустышкой). Счётчики — в нижнем
    баре: `.mobile__bar .bar__item-compare` / `.bar__item-favorites`, число в
    `span`, при нуле `display: none`. На время тестов десктопные хелперы
    `_header_compare_count`/`_header_favorite_count` подменяются чтением бара
    (monkeypatch в десктопном модуле — импортированные тесты берут их оттуда);
  * ленты мини-фото `.slider__thumbs` нет (скрыта) — фото листаются свайпом,
    под ними буллеты `.swiper-pagination-bullet`, по одному на фото.
    Автоплея нет. Кейс 72 переписан на буллеты и свайп;
  * лайтбокс (Fancybox) открывается тапом по фото на ТОМ ЖЕ фото, что было
    на экране; Escape на телефоне нет — закрывается крестиком тулбара
    `[data-fancybox-close]`. Кейс «фото во весь экран» переписан под это;
  * корзина в шапке — `.header__mobile_ecom .btn__cart`, в DOM она ПЕРВАЯ из
    `button.btn__action.btn__cart`, поэтому десктопный `_header_cart_sum`
    (`.first`) на телефоне читает именно её — тесты сумм импортированы как есть;
  * «Купить в 1 клик» — `button.btn__buy_click` под ценой, тоже первая в DOM;
  * у липкой нижней панели `.bottom-buy-bar` своя «В корзину» — она берёт
    количество из счётчика под ценой; на это отдельный тест.

Не перенесены кейсы 68/69 (hover на «Сравнение»/«Избранное»): на телефоне
наведения нет (`hover: none`).
"""

import re

import pytest
from playwright.sync_api import Page, expect

import test_product_page
from conftest import wait_until
from mobile.test_homepage_mobile import _swipe_left, _swipe_right
from test_product_page import (  # noqa: F401 — тесты собирает pytest
    BTN_ADD_CART,
    BTN_QTY_PLUS,
    H1,
    INPUT_QTY,
    LIGHTBOX,
    PRICE_NEW,
    _bani,
    _header_cart_sum,
    open_product_page,
    test_add_to_compare_increments_header_counter,
    test_add_to_favorites_increments_header_counter,
    test_remove_from_favorites_decrements_counter,
    test_expand_description,
    test_collapse_description,
    test_open_credit_popup,
    test_open_one_click_popup,
    test_quantity_change_with_buttons,
    test_quantity_minus_disabled_at_one,
    test_add_to_cart_updates_header_sum,
    test_open_cart_from_header,
    test_add_to_cart_with_quantity,
    test_product_price_matches_cart_header_sum,
)

BAR_COMPARE = ".mobile__bar .bar__item-compare"
BAR_FAVORITES = ".mobile__bar .bar__item-favorites"

SLIDER = ".product__slider .slider__images-swiper"
BULLET = ".product__slider .swiper-pagination-bullet"
BULLET_ACTIVE_CLASS = "swiper-pagination-bullet-active"
LIGHTBOX_CLOSE = "[data-fancybox-close]"
# Лента миниатюр внутри лайтбокса; выбранная — фото, открытое сейчас
LIGHTBOX_THUMB = ".f-thumbs__slide"

# Фото, показанное сейчас. Десктопный `_main_slider_image` не годится: он ждёт
# видимости первого `.slider__image`, а первые в DOM — скрытые на телефоне мини-фото.
ACTIVE_IMAGE = f"{SLIDER} .swiper-slide-active .slider__image"

BOTTOM_BAR = ".bottom-buy-bar"
BOTTOM_BAR_ADD = f"{BOTTOM_BAR} button.btn__add_cart"
HEADER_CART_BTN = ".header__mobile_ecom .btn__cart"

_BAR_COUNT_JS = """
    (sel) => {
        const s = document.querySelector(sel + ' span');
        if (!s || getComputedStyle(s).display === 'none') return 0;
        const m = (s.textContent || '').match(/\\d+/);
        return m ? parseInt(m[0]) : 0;
    }
"""


def _bar_count(page: Page, item: str) -> int:
    """Число на пункте нижнего бара (0, если счётчик скрыт)."""
    expect(page.locator(item)).to_be_visible()
    return page.evaluate(_BAR_COUNT_JS, item)


@pytest.fixture(autouse=True)
def _counters_from_bottom_bar(monkeypatch):
    monkeypatch.setattr(
        test_product_page, "_header_compare_count", lambda page: _bar_count(page, BAR_COMPARE)
    )
    monkeypatch.setattr(
        test_product_page, "_header_favorite_count", lambda page: _bar_count(page, BAR_FAVORITES)
    )


def _active_bullet(page: Page) -> int:
    return page.evaluate(
        "([sel, cls]) => [...document.querySelectorAll(sel)]"
        ".findIndex(b => b.classList.contains(cls))",
        [BULLET, BULLET_ACTIVE_CLASS],
    )


def _wait_active_bullet(page: Page, expected: int) -> int:
    """Дождаться активного буллета и вернуть фактический (падать — ассерту)."""
    try:
        expect(page.locator(BULLET).nth(expected)).to_have_class(
            re.compile(BULLET_ACTIVE_CLASS), timeout=5_000
        )
    except AssertionError:
        pass
    return _active_bullet(page)


# ===========================================================================
# Кейс 72 (моб.): Галерея — несколько фото, листаются свайпом
# ===========================================================================
def test_gallery_swipes_between_photos(page: Page):
    """Под фото по буллету на каждое фото (больше одного); свайп влево
    показывает следующее фото, свайп вправо — возвращает предыдущее."""
    slider = page.locator(SLIDER)
    expect(slider).to_be_visible(timeout=10_000)
    bullets = page.locator(BULLET)
    count = bullets.count()
    assert count > 1, f"В галерее товара {count} фото — листать нечего"
    assert _active_bullet(page) == 0, "Галерея открылась не на первом фото"

    _swipe_left(page, slider)
    assert _wait_active_bullet(page, 1) == 1, "Свайп влево не перелистнул на 2-е фото"

    _swipe_left(page, slider)
    assert _wait_active_bullet(page, 2) == 2, "Второй свайп влево не перелистнул на 3-е фото"

    _swipe_right(page, slider)
    assert _wait_active_bullet(page, 1) == 1, "Свайп вправо не вернул на 2-е фото"


# ===========================================================================
# Кейс 72 (моб.): Тап по буллету галереи переключает фото
# ===========================================================================
def test_gallery_bullet_tap_switches_photo(page: Page):
    """Тап по буллету показывает соответствующее фото."""
    bullets = page.locator(BULLET)
    expect(bullets.first).to_be_visible(timeout=10_000)
    target = bullets.count() - 1
    assert target > 0, "В галерее одно фото — переключать нечего"

    bullets.nth(target).tap()
    assert _wait_active_bullet(page, target) == target, (
        f"Тап по буллету {target + 1} не переключил фото"
    )
    # Показано действительно это фото, а не только подсвечен буллет
    active_slide = page.locator(f"{SLIDER} .swiper-slide-active")
    expect(active_slide).to_be_in_viewport(ratio=0.9)


# ===========================================================================
# Кейс 68 (моб.): Открытие изображения в полном размере
# ===========================================================================
def test_open_image_full_size(page: Page):
    """Тап по фото открывает лайтбокс с этим же фото крупнее, с затемнением и
    блокировкой прокрутки; крестик закрывает его и возвращает страницу."""
    main_image = page.locator(ACTIVE_IMAGE)
    expect(main_image).to_be_visible(timeout=15_000)
    main_image.scroll_into_view_if_needed()
    inline_width = main_image.bounding_box()["width"]

    main_image.tap()
    page.wait_for_selector(LIGHTBOX, timeout=10_000)
    lightbox = page.locator(LIGHTBOX).last  # см. десктопный тест: их бывает два
    expect(lightbox).to_be_visible(timeout=10_000)

    full_image = lightbox.locator("img.fancybox-image").first
    expect(full_image).to_be_visible(timeout=10_000)
    # Ждём конца zoom-анимации — первые кадры фото того же размера, что на странице
    try:
        page.wait_for_function(
            "([el, w]) => el.getBoundingClientRect().width > w",
            arg=[full_image.element_handle(), inline_width],
            timeout=10_000,
        )
    except Exception:
        pass
    full_width = full_image.bounding_box()["width"]
    assert full_width > inline_width, (
        f"Фото в лайтбоксе не крупнее, чем на странице: {full_width}px против {inline_width}px"
    )
    expect(lightbox.locator(".fancybox__backdrop")).to_be_visible()
    expect(page.locator("body")).to_have_css("overflow", "hidden")

    # Escape на телефоне нет — закрываем крестиком (по одному на экземпляр галереи)
    for _ in range(3):
        opened = page.locator(LIGHTBOX).count()
        if opened == 0:
            break
        page.locator(f"{LIGHTBOX} {LIGHTBOX_CLOSE}").last.tap()
        # Ждём, пока закроется этот экземпляр (анимация закрытия), а не 700 мс
        wait_until(
            page,
            lambda: page.locator(LIGHTBOX).count(),
            lambda value: value < opened,
            timeout_ms=5_000,
        )
    expect(page.locator(LIGHTBOX)).to_have_count(0, timeout=10_000)
    expect(page.locator("body")).to_have_css("overflow", "visible", timeout=10_000)
    expect(page.locator(H1)).to_be_visible()


# ===========================================================================
# Кейс 68 (моб.): Лайтбокс открывается на текущем фото галереи
# ===========================================================================
def test_lightbox_opens_on_current_photo(page: Page):
    """Пролистали галерею до другого фото — лайтбокс открывается на нём, а
    не на первом."""
    bullets = page.locator(BULLET)
    expect(bullets.first).to_be_visible(timeout=10_000)
    target = min(3, bullets.count() - 1)
    assert target > 0, "В галерее одно фото — проверять нечего"
    bullets.nth(target).tap()
    assert _wait_active_bullet(page, target) == target, "Фото в галерее не переключилось"

    active_image = page.locator(ACTIVE_IMAGE)
    active_image.scroll_into_view_if_needed()
    active_image.tap()
    lightbox = page.locator(LIGHTBOX).last
    expect(lightbox).to_be_visible(timeout=10_000)

    thumbs = lightbox.locator(LIGHTBOX_THUMB)
    expect(thumbs.nth(target)).to_have_class(re.compile(r"\bis-nav-selected\b"), timeout=10_000)
    selected = thumbs.evaluate_all(
        "els => els.findIndex(e => e.classList.contains('is-nav-selected'))"
    )
    assert selected == target, (
        f"На странице было фото {target + 1}, а лайтбокс открылся на {selected + 1}"
    )


# ===========================================================================
# Кейс 315 (моб.): «В корзину» из нижней панели — с выбранным количеством
# ===========================================================================
def test_bottom_bar_add_to_cart_uses_selected_quantity(page: Page):
    """Количество 3 в счётчике под ценой → «В корзину» в липкой нижней
    панели → в шапке сумма цена × 3."""
    price = _bani(page.locator(PRICE_NEW).first.text_content())
    assert price > 0, "Не удалось прочитать цену товара"

    plus = page.locator(BTN_QTY_PLUS).first
    plus.tap()
    plus.tap()
    expect(page.locator(INPUT_QTY).first).to_have_value("3")

    # Панель появляется по событию прокрутки (scrollTo не годится)
    add = page.locator(BOTTOM_BAR_ADD)
    for _ in range(10):
        page.mouse.wheel(0, 400)
        try:
            expect(add).to_be_visible(timeout=1_000)
            break
        except AssertionError:
            continue
    expect(add).to_be_visible()

    # Контекст у теста свежий — корзина пуста, суммы в шапке до добавления нет
    header_cart = page.locator(HEADER_CART_BTN)
    add.tap()
    expect(header_cart).to_contain_text("MDL", timeout=10_000)

    cart_sum = _header_cart_sum(page)
    assert cart_sum == price * 3, (
        f"После «В корзину» из нижней панели сумма {cart_sum / 100:.2f} MDL, "
        f"ожидали 3 × {price / 100:.2f} = {price * 3 / 100:.2f} MDL"
    )

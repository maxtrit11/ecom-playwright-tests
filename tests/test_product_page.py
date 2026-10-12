"""Тесты страницы Товара ECOM (Qase suite 14: Страница Товар ECOM)

Адаптировано под реальную реализацию сайта stage.ecom.md (проверено через MCP):
- На сайте НЕТ toast-плашек для добавления в сравнение/избранное/корзину.
  Подтверждение действия — через счётчик в шапке и active-стиль кнопки.
- У товара с коротким описанием кнопка «Читать больше» не показывается —
  кейсы 77/78 корректно скипаются.
- Lightbox при клике на главное фото ОТКРЫВАЕТСЯ (Fancybox) — проверено
  вживую 2026-08-17, см. Кейс 68. Прежняя заметка «не открывается» устарела.
"""

import re

import pytest
from playwright.sync_api import Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from conftest import CART_VIEW_POPUP, wait_until


# Товар используется как эталонный для всех тестов
PRODUCT_SLUG = "jbl-partybox-on-the-go-2"
PRODUCT_URL = f"/ru/product/{PRODUCT_SLUG}"

# Заголовок и базовые элементы
H1 = "h1"
DESCRIPTION = ".description__section"

# Кнопки на странице товара (НЕ путать с одноимёнными ссылками в шапке)
BTN_COMPARE = "button.compare__product"           # «Сравнение» под фото
BTN_FAVORITE = "button.save__product"             # «Избранное» под фото
BTN_ADD_CART = "button.btn__add_cart"             # «В корзину» (есть 2 копии — desktop/mobile)
BTN_CREDIT = "button.btn__credit"                 # «В кредит»
# «Купить в 1 клик»: на узком вьюпорте (<1024) видна иконка .btn__buy_click,
# на десктопе ≥1920 — кнопка .btn-one-click; берём union, первый видимый из них
BTN_ONE_CLICK = "button.btn-one-click, button.btn__buy_click"

# Количество товара
BTN_QTY_PLUS = "button.product-counter__button-plus"
BTN_QTY_MINUS = "button.product-counter__button-minus"
INPUT_QTY = "input.product-counter__input"

# Цена
PRICE_NEW = ".price.new__price"
PRICE_OLD = ".price.old__price"

# Шапка — счётчики
HEADER_COMPARE_LINK = "a.btn__action.compare__btn"     # «Сравнение N» в шапке
HEADER_FAVORITE_LINK = "a.btn__action.favorite__link"  # «Избранное N» в шапке
HEADER_CART_BTN = "button.btn__action.btn__cart"       # «Корзина / 6 999 MDL» в шапке

# Строка товара в открытой корзине: Вид 1 — поп-ап `.modal__cart.show`,
# Вид 2 — страница /cart (`.plank-card`; `.plank-card-mobile` сюда не попадает).
CART_ROW = ".modal__cart.show .cart__product, .page-cart .plank-card"

# Галерея фото
GALLERY_THUMBS = ".slider__thumbs.newType"
# Слайдер фото: и мини-фото, и главное фото лежат в одинаковых `.slider__image`,
# отличаются только размером — главное берём по ширине (см. `_main_slider_image`).
SLIDER_IMAGE = ".product__slider .slider__image"
# Лайтбокс полноразмерного фото — Fancybox. Контейнеров на странице может
# оказаться больше одного (см. `test_open_image_full_size`), поэтому искать
# фото нужно ВНУТРИ конкретного контейнера, а не общим селектором по странице.
LIGHTBOX = ".fancybox__container"

# Попапы (точные селекторы найдены через MCP)
MODAL_CREDIT = ".modal__credit.show"
MODAL_ONE_CLICK = ".modal__buy_onclick.show"


# Суммы на стенде дробные и с пробелом-разделителем тысяч: «6 649.05 MDL».
# Считаем всё в банях (копейках) целыми числами — так сравнение точное и не
# зависит от округления float.
#
# Прежний `_digits` просто вырезал всё, кроме цифр, и превращал «6 649.05 MDL»
# в 664905, а `_header_cart_sum` регуляркой `(\d[\d\s]*)\s*MDL` цеплялся к
# хвосту «05 MDL» и возвращал 5. Тесты падали на ассерте `5 == 0 + 664905`, хотя
# сайт показывал корректную сумму (проверено в браузере 2026-07-30).
_AMOUNT_RE = re.compile(r"(\d[\d\s ]*(?:[.,]\d{1,2})?)\s*MDL")


def _bani(text: str) -> int:
    """'6 649.05 MDL' → 664905 (бани). Без суммы в MDL — 0."""
    m = _AMOUNT_RE.search(text or "")
    if not m:
        return 0
    raw = re.sub(r"[\s ]", "", m.group(1)).replace(",", ".")
    whole, _, frac = raw.partition(".")
    return int(whole) * 100 + int((frac or "0").ljust(2, "0")[:2])


def _header_compare_count(page: Page) -> int:
    """Прочитать счётчик '... N' из ссылки 'Сравнение' в шапке."""
    text = page.locator(HEADER_COMPARE_LINK).first.text_content() or ""
    nums = re.findall(r"\d+", text)
    return int(nums[0]) if nums else 0


def _header_favorite_count(page: Page) -> int:
    text = page.locator(HEADER_FAVORITE_LINK).first.text_content() or ""
    nums = re.findall(r"\d+", text)
    return int(nums[0]) if nums else 0


def _header_cart_sum(page: Page) -> int:
    """Сумма в шапке корзины в банях, либо 0 если корзина пустая.

    В пустой корзине кнопка содержит только слово «Корзина» — суммы нет.
    """
    text = page.locator(HEADER_CART_BTN).first.text_content() or ""
    return _bani(text)


# Фон и цвет текста кнопки — то, что меняется при наведении.
_BTN_STYLE_JS = "el => [getComputedStyle(el).backgroundColor, getComputedStyle(el).color]"


@pytest.fixture(autouse=True)
def open_product_page(page: Page):
    """Открыть страницу товара перед каждым тестом."""
    page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(H1)).to_be_visible(timeout=15_000)
    expect(page.locator(BTN_ADD_CART).first).to_be_visible(timeout=15_000)


# ===========================================================================
# Кейс 68: Hover на кнопку Сравнение меняет визуальный стиль
# ===========================================================================
def test_compare_button_hover_changes_style(page: Page):
    """При наведении на кнопку Сравнение меняется фон или цвет."""
    btn = page.locator(BTN_COMPARE).first
    expect(btn).to_be_visible()

    style_before = btn.evaluate(_BTN_STYLE_JS)
    btn.hover()

    # Ждём конца CSS-перехода по факту, а не 500 мс. Раньше при неизменном
    # стиле тест уходил в skip — то есть покраснеть не мог в принципе. На
    # стенде hover меняет фон белый → чёрный и цвет текста (замер 12.10.2026),
    # так что «стиль не изменился» — это поломка, а не особенность сайта.
    style_after = wait_until(
        page,
        lambda: btn.evaluate(_BTN_STYLE_JS),
        lambda value: value != style_before,
        timeout_ms=3_000,
    )
    assert style_after != style_before, (
        f"Hover не изменил стиль кнопки: фон/цвет {style_before} → {style_after}"
    )


# ===========================================================================
# Кейс 69: Hover на кнопку Избранное меняет визуальный стиль
# ===========================================================================
def test_favorite_button_hover_changes_style(page: Page):
    """При наведении на кнопку Избранное меняется фон или цвет."""
    btn = page.locator(BTN_FAVORITE).first
    expect(btn).to_be_visible()

    style_before = btn.evaluate(_BTN_STYLE_JS)
    btn.hover()

    # Ждём конца CSS-перехода по факту, а не 500 мс. Раньше при неизменном
    # стиле тест уходил в skip — то есть покраснеть не мог в принципе. На
    # стенде hover меняет фон белый → чёрный и цвет текста (замер 12.10.2026),
    # так что «стиль не изменился» — это поломка, а не особенность сайта.
    style_after = wait_until(
        page,
        lambda: btn.evaluate(_BTN_STYLE_JS),
        lambda value: value != style_before,
        timeout_ms=3_000,
    )
    assert style_after != style_before, (
        f"Hover не изменил стиль кнопки: фон/цвет {style_before} → {style_after}"
    )


# ===========================================================================
# Кейс 70: Клик на Сравнение — товар добавлен (счётчик в шапке + active-стиль)
# ===========================================================================
def test_add_to_compare_increments_header_counter(page: Page):
    """Клик на Сравнение увеличивает счётчик в шапке и меняет стиль кнопки."""
    count_before = _header_compare_count(page)

    btn = page.locator(BTN_COMPARE).first

    btn.click()
    count_after = wait_until(
        page,
        lambda: _header_compare_count(page),
        lambda value: value != count_before,
    )
    assert count_after == count_before + 1, (
        f"Счётчик сравнения не увеличился: {count_before} → {count_after}"
    )

    # Активное состояние кнопки выражается классом is-active (а не сменой
    # background-color: у активной кнопки фон остаётся белым, active-стиль даёт
    # класс/цвет иконки — проверено через MCP). Старый assert на смену bg давал
    # ложное падение.
    expect(btn).to_have_class(re.compile(r"\bis-active\b"))


# ===========================================================================
# Кейс 71: Клик на Избранное — товар добавлен (счётчик в шапке + active-стиль)
# ===========================================================================
def test_add_to_favorites_increments_header_counter(page: Page):
    """Клик на Избранное увеличивает счётчик в шапке."""
    count_before = _header_favorite_count(page)

    btn = page.locator(BTN_FAVORITE).first
    btn.click()
    count_after = wait_until(
        page,
        lambda: _header_favorite_count(page),
        lambda value: value != count_before,
    )
    assert count_after == count_before + 1, (
        f"Счётчик избранного не увеличился: {count_before} → {count_after}"
    )


# ===========================================================================
# Кейс 72: Галерея мини-фото — содержит несколько фотографий
# ===========================================================================
def test_thumbs_gallery_has_multiple_photos(page: Page):
    """Галерея мини-фото содержит более одной картинки."""
    thumbs = page.locator(GALLERY_THUMBS)
    expect(thumbs).to_be_visible(timeout=10_000)

    thumb_imgs = thumbs.locator("img")
    count = thumb_imgs.count()
    assert count > 1, f"В галерее мини-фото только {count} картинка"


# ===========================================================================
# Кейс 68: Открытие изображения в полном размере
# ===========================================================================
def _main_slider_image(page: Page):
    """Главное (большое) фото товара в слайдере.

    Отдельного класса у него нет: мини-фото и главное фото — одинаковые
    `.slider__image`, поэтому берём первое достаточно широкое. Индекс тут
    зашивать нельзя — он зависит от числа мини-фото у конкретного товара.
    """
    images = page.locator(SLIDER_IMAGE)
    expect(images.first).to_be_visible(timeout=15_000)

    for i in range(images.count()):
        box = images.nth(i).bounding_box()
        if box and box["width"] > 250:
            return images.nth(i)

    pytest.skip("У товара нет крупного фото в слайдере — открывать нечего")


def test_open_image_full_size(page: Page):
    """Клик по главному фото открывает его во весь экран и увеличивает.

    Лайтбокс на сайте — Fancybox (`.fancybox__container`). Раньше в шапке
    файла было записано, что при клике на фото лайтбокс НЕ открывается;
    на текущем стенде открывается, проверено вживую 2026-08-17.
    """
    main_image = _main_slider_image(page)
    inline_width = main_image.bounding_box()["width"]

    main_image.click()

    # Главное фото — слайд карусели, и все 8 слайдов сидят в одной fancybox-группе
    # `product-gallery`. Под нагрузкой в CI клик успевает открыть галерею дважды,
    # и в DOM оказывается два `.fancybox__container` (#fancybox-1 и #fancybox-2,
    # оба `is-opening`) — общий селектор падал на strict mode (прогон 32455950259).
    # Верхний по z-order — последний в DOM, с ним пользователь и взаимодействует.
    page.wait_for_selector(LIGHTBOX, timeout=10_000)
    lightbox = page.locator(LIGHTBOX).last
    expect(lightbox).to_be_visible(timeout=10_000)

    # Фото открылось именно В ПОЛНОМ РАЗМЕРЕ — оно шире, чем было на странице
    full_image = lightbox.locator("img.fancybox-image").first
    expect(full_image).to_be_visible(timeout=10_000)
    # Fancybox открывается zoom-анимацией от миниатюры: первые кадры фото ровно
    # того же размера, что и на странице. Под нагрузкой в CI замер попадал именно
    # туда — 543.99px против 544px (прогон 36685307738). Ждём, пока фото вырастет.
    try:
        page.wait_for_function(
            "([el, w]) => el.getBoundingClientRect().width > w",
            arg=[full_image.element_handle(), inline_width],
            timeout=10_000,
        )
    except PlaywrightTimeoutError:
        pass  # ассерт ниже покажет итоговые размеры
    full_width = full_image.bounding_box()["width"]
    assert full_width > inline_width, (
        f"Фото в лайтбоксе не крупнее, чем на странице: "
        f"{full_width}px против {inline_width}px"
    )

    # Затемнение фона и заблокированный скролл — признак модального режима
    expect(lightbox.locator(".fancybox__backdrop")).to_be_visible()
    expect(page.locator("body")).to_have_css("overflow", "hidden")

    # Escape закрывает просмотр и возвращает страницу в рабочее состояние.
    # Каждое нажатие закрывает один экземпляр галереи, поэтому жмём, пока в DOM
    # что-то остаётся: иначе при двойном открытии тест уходил бы в ложное падение.
    for _ in range(3):
        opened = page.locator(LIGHTBOX).count()
        if opened == 0:
            break
        page.keyboard.press("Escape")
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
# Кейс 77: Развернуть описание товара
# ===========================================================================
def test_expand_description(page: Page):
    """Клик «Читать больше» — описание раскрывается."""
    desc = page.locator(DESCRIPTION)
    expect(desc).to_be_visible()

    read_more = desc.get_by_text(re.compile(r"Читать больше", re.IGNORECASE))
    if read_more.count() == 0:
        pytest.skip("У товара короткое описание — кнопка «Читать больше» не появилась")

    height_before = desc.evaluate("el => el.offsetHeight")
    read_more.first.click()
    height_after = wait_until(
        page,
        lambda: desc.evaluate("el => el.offsetHeight"),
        lambda value: value > height_before,
        timeout_ms=5_000,
    )

    assert height_after > height_before, (
        f"Описание не раскрылось: высота {height_before} → {height_after}"
    )

    hide_btn = desc.get_by_text(re.compile(r"Скрыть описание", re.IGNORECASE))
    expect(hide_btn.first).to_be_visible()


# ===========================================================================
# Кейс 78: Свернуть описание товара
# ===========================================================================
def test_collapse_description(page: Page):
    """Развернуть описание → клик «Скрыть описание» — описание сворачивается."""
    desc = page.locator(DESCRIPTION)
    read_more = desc.get_by_text(re.compile(r"Читать больше", re.IGNORECASE))

    if read_more.count() == 0:
        pytest.skip("У товара короткое описание — кнопка «Читать больше» не появилась")

    height_initial = desc.evaluate("el => el.offsetHeight")
    read_more.first.click()
    # Раскрытие здесь — подготовка, а не проверка: ждём его по факту
    # («Скрыть описание» видна, высота выросла), а не 500 мс.
    hide_btn = desc.get_by_text(re.compile(r"Скрыть описание", re.IGNORECASE)).first
    expect(hide_btn).to_be_visible(timeout=5_000)
    height_expanded = wait_until(
        page,
        lambda: desc.evaluate("el => el.offsetHeight"),
        lambda value: value > height_initial,
        timeout_ms=5_000,
    )

    hide_btn.click()
    height_collapsed = wait_until(
        page,
        lambda: desc.evaluate("el => el.offsetHeight"),
        lambda value: value < height_expanded,
        timeout_ms=5_000,
    )

    assert height_collapsed < height_expanded, (
        f"Описание не свернулось: {height_expanded} → {height_collapsed}"
    )
    expect(desc.get_by_text(re.compile(r"Читать больше", re.IGNORECASE)).first).to_be_visible()


# ===========================================================================
# Кейс 80: Открыть поп-ап Купить в кредит
# ===========================================================================
def test_open_credit_popup(page: Page, credit_product: str):
    """Клик «В кредит» — открывается поп-ап с полями имя/телефон и компаниями кредитования."""
    # У эталонного товара страницы `credit.has == false` — кнопки `btn__credit`
    # в разметке просто нет, и кейс уходил в вечный skip. Товар с доступным
    # кредитом даёт сессионная фикстура `credit_product` (conftest).
    page.goto(credit_product, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(H1)).to_be_visible(timeout=15_000)

    credit_btn = page.locator(BTN_CREDIT).first
    expect(credit_btn).to_be_visible(timeout=10_000)

    # Первый клик после гидрации регулярно теряется — кликаем с повтором.
    modal = page.locator(MODAL_CREDIT)
    for _ in range(3):
        credit_btn.click()
        try:
            expect(modal).to_be_visible(timeout=5_000)
            break
        except AssertionError:
            continue
    expect(modal).to_be_visible(timeout=10_000)

    # Заголовок «Купить в кредит»
    expect(modal.get_by_text("Купить в кредит").first).to_be_visible()

    # Карточка товара внутри попапа — название и цена
    expect(modal.locator(":text-matches('JBL', 'i')").first).to_be_visible()

    # Блок «Выбери компанию кредитования» с карточками
    expect(modal.get_by_text(re.compile(r"Выбери|компани", re.IGNORECASE)).first).to_be_visible()

    # Поля Полное имя и Телефон
    expect(modal.locator('input[placeholder*="имя" i], input[placeholder*="фамил" i]').first).to_be_visible()
    expect(modal.locator('input[type="tel"]').first).to_be_visible()

    # Кнопки «Продолжить покупки» и «Отправить заявку»
    expect(modal.get_by_text(re.compile(r"Продолжить покупки", re.IGNORECASE)).first).to_be_visible()
    expect(modal.get_by_text(re.compile(r"Отправить заявку", re.IGNORECASE)).first).to_be_visible()

    # Кнопка X
    expect(modal.locator(".btn__close, button[class*='close']").first).to_be_visible()


# ===========================================================================
# Кейс 82: Клик «В корзину» — товар добавлен (сумма в шапке)
# ===========================================================================
@pytest.mark.smoke
def test_add_to_cart_updates_header_sum(page: Page):
    """Клик «В корзину» — в шапке у иконки корзины появляется сумма товара."""
    sum_before = _header_cart_sum(page)

    price_text = page.locator(PRICE_NEW).first.text_content().strip()
    price = _bani(price_text)
    assert price > 0, f"Не удалось распарсить цену со страницы: {price_text}"

    page.locator(BTN_ADD_CART).first.click()
    # Ждём саму сумму, а не «секунду по часам»: под нагрузкой XHR корзины
    # приходит позже, и фиксированной паузы не хватало.
    sum_after = wait_until(
        page,
        lambda: _header_cart_sum(page),
        lambda value: value != sum_before,
    )
    assert sum_after == sum_before + price, (
        f"Сумма в шапке не обновилась корректно: {sum_before} + {price} ≠ {sum_after}"
    )


# ===========================================================================
# Кейс 83: Клик по иконке корзины в шапке — открывается корзина (drawer или /ru/cart)
# ===========================================================================
def test_open_cart_from_header(page: Page):
    """В корзину → клик по иконке корзины в шапке → открывается корзина с товаром."""
    product_name = page.locator(H1).first.inner_text().strip()
    sum_before = _header_cart_sum(page)
    page.locator(BTN_ADD_CART).first.click()
    # Ждём, что товар реально доехал до корзины: клик по иконке шапки раньше
    # этого момента открывает пустую корзину.
    wait_until(page, lambda: _header_cart_sum(page), lambda value: value != sum_before)

    # Кликаем по видимой иконке корзины в шапке (есть скрытый mobile-дубль)
    page.evaluate(
        """() => {
            const btns = document.querySelectorAll('button.btn__action.btn__cart');
            const visible = Array.from(btns).find(b => b.offsetParent !== null);
            visible?.click();
        }"""
    )

    # Сайт может открыть drawer/popup или перейти на /ru/cart.
    # На стейдже это side-drawer .cart__sidebar (с детьми .cart__products /
    # .cart__items-container / .cart__product) — добавляем эти селекторы.
    drawer_locator = page.locator(
        ".modal__cart, [class*='cart__modal'], [class*='cart-drawer'], "
        "[class*='basket'][class*='show'], "
        ".cart__sidebar, .cart__products, .cart__items-container"
    )

    def _cart_opened() -> bool:
        return "cart" in page.url or (
            drawer_locator.count() > 0 and drawer_locator.first.is_visible()
        )

    # Ждём открытия по факту, а не 2 с наугад: под нагрузкой дровер рисуется позже.
    wait_until(page, _cart_opened, lambda opened: opened)

    url_changed = "cart" in page.url
    drawer_visible = drawer_locator.count() > 0 and drawer_locator.first.is_visible()

    assert url_changed or drawer_visible, (
        f"Корзина не открылась: URL={page.url}, drawer={drawer_visible}"
    )

    # В корзине должен быть ИМЕННО этот товар. Прежнее `"JBL" in body` было
    # тавтологией: «JBL» есть в h1 самой страницы товара, в меню и в футере —
    # ассерт проходил и с пустой корзиной.
    expect(page.locator(CART_ROW).filter(has_text=product_name).first).to_be_visible(
        timeout=15_000
    )


# ===========================================================================
# Кейс 84: Открыть поп-ап Покупка в один клик
# ===========================================================================
def test_open_one_click_popup(page: Page):
    """Клик «Купить в один клик» — открывается поп-ап Покупка в один клик."""
    one_click_btn = page.locator(BTN_ONE_CLICK).first
    if one_click_btn.count() == 0:
        pytest.skip("Кнопка «Купить в один клик» не отображается для этого товара")

    one_click_btn.click()

    modal = page.locator(MODAL_ONE_CLICK)
    expect(modal).to_be_visible(timeout=10_000)

    # Заголовок
    expect(modal.get_by_text("Покупка в один клик").first).to_be_visible()

    # Карточка товара (название + цена)
    expect(modal.locator(":text-matches('JBL', 'i')").first).to_be_visible()
    expect(modal.locator(":text-matches('MDL', 'i')").first).to_be_visible()

    # Поле Номер телефона
    expect(modal.locator('input[type="tel"]').first).to_be_visible()

    # Кнопка Оформить заказ
    expect(modal.get_by_text(re.compile(r"Оформить заказ", re.IGNORECASE)).first).to_be_visible()

    # Кнопка X
    expect(modal.locator(".btn__close, button[class*='close']").first).to_be_visible()


# ===========================================================================
# Кейс 85: Удалить товар из избранного — счётчик в шапке падает
# ===========================================================================
def test_remove_from_favorites_decrements_counter(page: Page):
    """Сначала добавить в избранное, затем повторный клик → счётчик уменьшается."""
    btn = page.locator(BTN_FAVORITE).first

    count_before = _header_favorite_count(page)
    btn.click()
    count_after_add = wait_until(
        page,
        lambda: _header_favorite_count(page),
        lambda value: value > count_before,
    )
    assert count_after_add >= 1, "Товар не добавился в избранное"

    btn.click()
    count_after_remove = wait_until(
        page,
        lambda: _header_favorite_count(page),
        lambda value: value < count_after_add,
    )
    assert count_after_remove == count_after_add - 1, (
        f"Счётчик избранного не уменьшился: {count_after_add} → {count_after_remove}"
    )


# ===========================================================================
# Кейс 313: Изменение количества кнопками
# ===========================================================================
def test_quantity_change_with_buttons(page: Page):
    """+ x2 → значение 3; − x1 → значение 2."""
    qty_input = page.locator(INPUT_QTY).first
    expect(qty_input).to_have_value("1", timeout=5_000)

    plus = page.locator(BTN_QTY_PLUS).first
    plus.click()
    plus.click()
    expect(qty_input).to_have_value("3")

    page.locator(BTN_QTY_MINUS).first.click()
    expect(qty_input).to_have_value("2")


# ===========================================================================
# Кейс 314: При qty=1 — кнопка − неактивна
# ===========================================================================
def test_quantity_minus_disabled_at_one(page: Page):
    """qty=1 — кнопка − имеет атрибут disabled."""
    qty_input = page.locator(INPUT_QTY).first
    expect(qty_input).to_have_value("1", timeout=5_000)

    minus = page.locator(BTN_QTY_MINUS).first
    expect(minus).to_be_disabled()


# ===========================================================================
# Кейс 315: Добавление в корзину с выбранным количеством
# ===========================================================================
def test_add_to_cart_with_quantity(page: Page, cart_view: str):
    """qty=3 → В корзину → в шапке сумма = price × 3."""
    product_name = page.locator(H1).first.inner_text().strip()
    price_text = page.locator(PRICE_NEW).first.text_content().strip()
    price = _bani(price_text)
    assert price > 0

    plus = page.locator(BTN_QTY_PLUS).first
    plus.click()
    plus.click()
    expect(page.locator(INPUT_QTY).first).to_have_value("3")

    page.locator(BTN_ADD_CART).first.click()
    sum_in_header = wait_until(
        page,
        lambda: _header_cart_sum(page),
        lambda value: value == price * 3,
    )
    assert sum_in_header == price * 3, (
        f"Сумма в шапке ({sum_in_header}) ≠ price * 3 ({price * 3})"
    )

    # Открыть корзину через клик на иконку в шапке (не goto — сохранит сессию)
    # Кликаем по видимой иконке корзины в шапке (есть скрытый mobile-дубль)
    page.evaluate(
        """() => {
            const btns = document.querySelectorAll('button.btn__action.btn__cart');
            const visible = Array.from(btns).find(b => b.offsetParent !== null);
            visible?.click();
        }"""
    )

    # Товар ищем строкой корзины. Прежний подсчёт названия по всему `body`
    # был тавтологией: название стоит в h1 самой страницы товара.
    row = page.locator(CART_ROW).filter(has_text=product_name).first
    expect(row, f"Товар «{product_name}» не найден в корзине").to_be_visible(
        timeout=15_000
    )

    # В корзине должно быть указано кол-во товара = 3. Прежняя проверка искала
    # «3» среди ВСЕХ counter-input страницы (да ещё под `if count() > 0`) и
    # находила счётчик самой карточки товара, который тест только что накрутил.
    if cart_view == CART_VIEW_POPUP:
        expect(row.locator("input.item__current--input")).to_have_value("3")
    else:
        expect(row.locator(".plank-card__btns")).to_contain_text(re.compile(r"\b3\b"))


# ===========================================================================
# Кейс 316: Цена на странице товара == цена в шапке корзины
# ===========================================================================
def test_product_price_matches_cart_header_sum(page: Page):
    """Цена на странице товара равна сумме в шапке после добавления в корзину."""
    price_text = page.locator(PRICE_NEW).first.text_content().strip()
    price = _bani(price_text)
    assert price > 0, f"Не удалось распарсить цену со страницы: {price_text}"

    sum_before = _header_cart_sum(page)
    page.locator(BTN_ADD_CART).first.click()
    sum_after = wait_until(
        page,
        lambda: _header_cart_sum(page),
        lambda value: value != sum_before,
    )

    assert sum_after == sum_before + price, (
        f"Сумма в шапке не отражает цену товара: было {sum_before}, "
        f"добавили {price}, стало {sum_after}"
    )

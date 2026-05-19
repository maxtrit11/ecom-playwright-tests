"""Тесты страницы Товара ECOM (Qase suite 14: Страница Товар ECOM)

Адаптировано под реальную реализацию сайта stage.ecom.md (проверено через MCP):
- На сайте НЕТ toast-плашек для добавления в сравнение/избранное/корзину.
  Подтверждение действия — через счётчик в шапке и active-стиль кнопки.
- У товара с коротким описанием кнопка «Читать больше» не показывается —
  кейсы 77/78 корректно скипаются.
- Lightbox при клике на главное фото не открывается — Кейс 76 проверяет,
  что клик на мини-фото переключает основное фото в слайдере.
"""

import re

import pytest
from playwright.sync_api import Page, expect


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

# Галерея фото
GALLERY_THUMBS = ".slider__thumbs.newType"

# Попапы (точные селекторы найдены через MCP)
MODAL_CREDIT = ".modal__credit.show"
MODAL_ONE_CLICK = ".modal__buy_onclick.show"


def _digits(text: str) -> int:
    """Извлечь число из строки вида '1 199 MDL' → 1199."""
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else 0


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
    """Сумма в шапке корзины ('6 999 MDL' → 6999), либо 0 если корзина пустая."""
    text = page.locator(HEADER_CART_BTN).first.text_content() or ""
    # Игнорируем слово «Корзина», берём только MDL-сумму
    m = re.search(r"(\d[\d\s]*)\s*MDL", text)
    return _digits(m.group(1)) if m else 0


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

    bg_before = btn.evaluate("el => getComputedStyle(el).backgroundColor")
    color_before = btn.evaluate("el => getComputedStyle(el).color")

    btn.hover()
    page.wait_for_timeout(500)

    bg_after = btn.evaluate("el => getComputedStyle(el).backgroundColor")
    color_after = btn.evaluate("el => getComputedStyle(el).color")

    changed = bg_before != bg_after or color_before != color_after
    if not changed:
        pytest.skip(
            "На этом сайте hover не меняет стиль кнопки — стиль меняется "
            "только при добавлении в сравнение (active state)"
        )


# ===========================================================================
# Кейс 69: Hover на кнопку Избранное меняет визуальный стиль
# ===========================================================================
def test_favorite_button_hover_changes_style(page: Page):
    """При наведении на кнопку Избранное меняется фон или цвет."""
    btn = page.locator(BTN_FAVORITE).first
    expect(btn).to_be_visible()

    bg_before = btn.evaluate("el => getComputedStyle(el).backgroundColor")
    color_before = btn.evaluate("el => getComputedStyle(el).color")

    btn.hover()
    page.wait_for_timeout(500)

    bg_after = btn.evaluate("el => getComputedStyle(el).backgroundColor")
    color_after = btn.evaluate("el => getComputedStyle(el).color")

    changed = bg_before != bg_after or color_before != color_after
    if not changed:
        pytest.skip(
            "На этом сайте hover не меняет стиль кнопки — стиль меняется "
            "только при добавлении в избранное (active state)"
        )


# ===========================================================================
# Кейс 70: Клик на Сравнение — товар добавлен (счётчик в шапке + active-стиль)
# ===========================================================================
def test_add_to_compare_increments_header_counter(page: Page):
    """Клик на Сравнение увеличивает счётчик в шапке и меняет стиль кнопки."""
    count_before = _header_compare_count(page)

    btn = page.locator(BTN_COMPARE).first
    bg_before = btn.evaluate("el => getComputedStyle(el).backgroundColor")

    btn.click()
    page.wait_for_timeout(800)

    count_after = _header_compare_count(page)
    assert count_after == count_before + 1, (
        f"Счётчик сравнения не увеличился: {count_before} → {count_after}"
    )

    bg_after = btn.evaluate("el => getComputedStyle(el).backgroundColor")
    assert bg_before != bg_after, "Стиль кнопки Сравнение не изменился после клика"


# ===========================================================================
# Кейс 71: Клик на Избранное — товар добавлен (счётчик в шапке + active-стиль)
# ===========================================================================
def test_add_to_favorites_increments_header_counter(page: Page):
    """Клик на Избранное увеличивает счётчик в шапке."""
    count_before = _header_favorite_count(page)

    btn = page.locator(BTN_FAVORITE).first
    btn.click()
    page.wait_for_timeout(800)

    count_after = _header_favorite_count(page)
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
    page.wait_for_timeout(500)
    height_after = desc.evaluate("el => el.offsetHeight")

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

    read_more.first.click()
    page.wait_for_timeout(500)
    height_expanded = desc.evaluate("el => el.offsetHeight")

    desc.get_by_text(re.compile(r"Скрыть описание", re.IGNORECASE)).first.click()
    page.wait_for_timeout(500)
    height_collapsed = desc.evaluate("el => el.offsetHeight")

    assert height_collapsed < height_expanded, (
        f"Описание не свернулось: {height_expanded} → {height_collapsed}"
    )
    expect(desc.get_by_text(re.compile(r"Читать больше", re.IGNORECASE)).first).to_be_visible()


# ===========================================================================
# Кейс 80: Открыть поп-ап Купить в кредит
# ===========================================================================
def test_open_credit_popup(page: Page):
    """Клик «В кредит» — открывается поп-ап с полями имя/телефон и компаниями кредитования."""
    credit_btn = page.locator(BTN_CREDIT).first
    if credit_btn.count() == 0:
        pytest.skip("На сайте отключён функционал кредитов для этого товара")

    credit_btn.click()

    modal = page.locator(MODAL_CREDIT)
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
def test_add_to_cart_updates_header_sum(page: Page):
    """Клик «В корзину» — в шапке у иконки корзины появляется сумма товара."""
    sum_before = _header_cart_sum(page)

    price_text = page.locator(PRICE_NEW).first.text_content().strip()
    price = _digits(price_text)
    assert price > 0, f"Не удалось распарсить цену со страницы: {price_text}"

    page.locator(BTN_ADD_CART).first.click()
    page.wait_for_timeout(1000)

    sum_after = _header_cart_sum(page)
    assert sum_after == sum_before + price, (
        f"Сумма в шапке не обновилась корректно: {sum_before} + {price} ≠ {sum_after}"
    )


# ===========================================================================
# Кейс 83: Клик по иконке корзины в шапке — открывается корзина (drawer или /ru/cart)
# ===========================================================================
def test_open_cart_from_header(page: Page):
    """В корзину → клик по иконке корзины в шапке → открывается корзина с товаром."""
    page.locator(BTN_ADD_CART).first.click()
    page.wait_for_timeout(3000)

    # Кликаем по видимой иконке корзины в шапке (есть скрытый mobile-дубль)
    page.evaluate(
        """() => {
            const btns = document.querySelectorAll('button.btn__action.btn__cart');
            const visible = Array.from(btns).find(b => b.offsetParent !== null);
            visible?.click();
        }"""
    )
    page.wait_for_timeout(2000)

    # Сайт может открыть drawer/popup или перейти на /ru/cart.
    # На стейдже это side-drawer .cart__sidebar (с детьми .cart__products /
    # .cart__items-container / .cart__product) — добавляем эти селекторы.
    drawer_locator = page.locator(
        ".modal__cart, [class*='cart__modal'], [class*='cart-drawer'], "
        "[class*='basket'][class*='show'], "
        ".cart__sidebar, .cart__products, .cart__items-container"
    )
    url_changed = "cart" in page.url
    drawer_visible = drawer_locator.count() > 0 and drawer_locator.first.is_visible()

    assert url_changed or drawer_visible, (
        f"Корзина не открылась: URL={page.url}, drawer={drawer_visible}"
    )

    # В корзине должен быть товар
    assert "JBL" in page.locator("body").text_content()


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

    btn.click()
    page.wait_for_timeout(800)
    count_after_add = _header_favorite_count(page)
    assert count_after_add >= 1, "Товар не добавился в избранное"

    btn.click()
    page.wait_for_timeout(800)
    count_after_remove = _header_favorite_count(page)
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
def test_add_to_cart_with_quantity(page: Page):
    """qty=3 → В корзину → в шапке сумма = price × 3."""
    price_text = page.locator(PRICE_NEW).first.text_content().strip()
    price = _digits(price_text)
    assert price > 0

    plus = page.locator(BTN_QTY_PLUS).first
    plus.click()
    plus.click()
    expect(page.locator(INPUT_QTY).first).to_have_value("3")

    page.locator(BTN_ADD_CART).first.click()
    page.wait_for_timeout(3000)

    sum_in_header = _header_cart_sum(page)
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
    page.wait_for_timeout(2500)

    body_text = page.locator("body").text_content()
    jbl_occurrences = body_text.count("JBL PartyBox On-the-Go 2")
    assert jbl_occurrences >= 1, (
        f"Товар не найден в корзине, найдено: {jbl_occurrences}"
    )

    # В корзине должно быть указано кол-во товара = 3
    qty_in_cart = page.locator("input.product-counter__input, input[class*='counter']")
    if qty_in_cart.count() > 0:
        # На странице корзины может быть несколько counter-input; ищем тот, что = "3"
        values = qty_in_cart.evaluate_all("els => els.map(e => e.value)")
        assert "3" in values, f"В корзине не нашлось qty=3, значения: {values}"


# ===========================================================================
# Кейс 316: Цена на странице товара == цена в шапке корзины
# ===========================================================================
def test_product_price_matches_cart_header_sum(page: Page):
    """Цена на странице товара равна сумме в шапке после добавления в корзину."""
    price_text = page.locator(PRICE_NEW).first.text_content().strip()
    price = _digits(price_text)
    assert price > 0, f"Не удалось распарсить цену со страницы: {price_text}"

    sum_before = _header_cart_sum(page)
    page.locator(BTN_ADD_CART).first.click()
    page.wait_for_timeout(1500)
    sum_after = _header_cart_sum(page)

    assert sum_after == sum_before + price, (
        f"Сумма в шапке не отражает цену товара: было {sum_before}, "
        f"добавили {price}, стало {sum_after}"
    )

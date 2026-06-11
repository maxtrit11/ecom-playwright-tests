"""Тесты товара без стока (режим «Предзаказ») — stage.ecom.md

Эталонный товар: jbl-tune-530bt-purple. У него НЕТ остатка, поэтому сайт
переключает карточку в режим предзаказа. Поведение проверено вживую через MCP:

- Активная цена `.price.new__price` НЕ отображается (нечего продавать — нет стока).
  Эталонная цена «1 199 MDL» остаётся в DOM (`.product__prices`/`.no-discount`),
  но кнопки покупки её не используют.
- Вместо «В корзину» показывается кнопка «Предзаказ»
  (`button.btn__add_cart.btn__add_cart_preorder`, есть desktop/mobile-дубли).
- Счётчик количества заблокирован: обе кнопки − и + имеют disabled
  (для предзаказа количество не выбирается, всегда 1).
- Сопутствующие способы покупки выключены: «Покупка в один клик» и «В кредит»
  отрисованы как disabled.
- Клик «Предзаказ» открывает поп-ап. Технически это та же модалка, что и
  «Покупка в один клик» (`.modal__buy_onclick.show`), но с заголовком h4
  «Предзаказ» и подзаголовком про звонок в течение 15 минут. Внутри: карточка
  товара (название + цена), поле телефона с выбором страны (+373),
  кнопка «Оформить заказ» (`button.request`), крестик `.btn__close`.
- Валидация телефона АСИНХРОННАЯ: после клика «Оформить заказ» с пустым полем
  класс `error` и текст «Это обязательное поле» появляются не мгновенно —
  поэтому проверяем через expect (auto-retry).
- Реальный сабмит с валидным телефоном создаёт заявку: поп-ап предзаказа
  закрывается и показывается экран успеха
  `.modal__checkout_success.show` с заголовком «Заявка отправлена успешно».
  ВНИМАНИЕ: этот тест отправляет РЕАЛЬНУЮ заявку в админку при каждом прогоне
  (помечен @pytest.mark.real_submit — можно отключить `-m "not real_submit"`).
"""

import re

import pytest
from playwright.sync_api import Page, expect


# Товар БЕЗ стока — карточка в режиме предзаказа
PRODUCT_SLUG = "jbl-tune-530bt-purple"
PRODUCT_URL = f"/ru/product/{PRODUCT_SLUG}"
PRODUCT_NAME = "JBL Tune 530BT Purple"

H1 = "h1"

# Кнопка «Предзаказ» (заменяет «В корзину»); :visible отсеивает mobile-дубль
BTN_PREORDER = "button.btn__add_cart_preorder:visible"
# Обычная активная «В корзину» (для товара СО стоком) — НЕ должна присутствовать
BTN_ADD_CART_REAL = "button.btn__add_cart:not(.btn__add_cart_preorder)"

# Активная цена (есть только у товара со стоком)
PRICE_NEW = ".price.new__price"

# Счётчик количества
BTN_QTY_PLUS = "button.product-counter__button-plus"
BTN_QTY_MINUS = "button.product-counter__button-minus"

# Прочие способы покупки (для предзаказа — disabled)
BTN_ONE_CLICK = "button.btn-one-click, button.btn__buy_click"
BTN_CREDIT = "button.btn__credit"

# Поп-ап предзаказа (переиспользует модалку one-click)
MODAL_PREORDER = ".modal__buy_onclick.show"
MODAL_SUBMIT = "button.request"          # «Оформить заказ»
MODAL_PHONE = "input.phone"
MODAL_CLOSE = ".btn__close"
# Экран успеха после реальной отправки заявки
MODAL_SUCCESS = ".modal__checkout_success.show"

# Валидный молдавский мобильный для сабмита (intl-tel-input форматирует сам)
TEST_PHONE = "69123456"

# Шапка — корзина
HEADER_CART_BTN = "button.btn__action.btn__cart"


def _digits(text: str) -> int:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else 0


def _header_cart_sum(page: Page) -> int:
    """Сумма у иконки корзины в шапке ('15 097 MDL' → 15097), 0 если пусто."""
    text = page.locator(HEADER_CART_BTN).first.text_content() or ""
    m = re.search(r"(\d[\d\s]*)\s*MDL", text)
    return _digits(m.group(1)) if m else 0


def _open_preorder_modal(page: Page):
    """Кликнуть видимую кнопку «Предзаказ» и дождаться поп-апа.

    :visible берёт нужный из desktop/mobile-дублей; нативный клик Playwright
    ждёт actionability. Иногда первый клик уходит до гидрации Vue-обработчика —
    поэтому ретраим клик, пока модалка не появится.
    """
    btn = page.locator(BTN_PREORDER).first
    expect(btn).to_be_enabled(timeout=15_000)
    modal = page.locator(MODAL_PREORDER)
    for _ in range(3):
        btn.click()
        try:
            expect(modal).to_be_visible(timeout=4_000)
            return modal
        except AssertionError:
            page.wait_for_timeout(500)
    expect(modal).to_be_visible(timeout=4_000)
    return modal


def _fill_phone(modal, number: str):
    """Ввести телефон так, чтобы intl-tel-input отформатировал и провалидировал.

    ВАЖНО: `fill()` ломает маску intl-tel-input — значение остаётся без пробелов
    («69123456»), плагин считает номер невалидным и сабмит ловит ошибку.
    Нужен посимвольный ввод с фокусом: click → press_sequentially. Тогда номер
    форматируется в «691 23 456» и проходит валидацию.
    """
    phone = modal.locator(MODAL_PHONE).first
    phone.click()
    phone.press_sequentially(number, delay=60)
    return phone


@pytest.fixture(autouse=True)
def open_product_page(page: Page):
    """Открыть страницу товара-предзаказа перед каждым тестом."""
    page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator(H1)).to_be_visible(timeout=15_000)
    expect(page.locator(BTN_PREORDER)).to_be_visible(timeout=15_000)


# ===========================================================================
# Состояние страницы товара без стока
# ===========================================================================
def test_preorder_button_shown_instead_of_add_cart(page: Page):
    """У товара без стока показана «Предзаказ», обычной «В корзину» нет."""
    preorder = page.locator(BTN_PREORDER)
    expect(preorder).to_be_visible()
    expect(preorder).to_have_text(re.compile(r"Предзаказ", re.IGNORECASE))

    # Не должно быть активной кнопки «В корзину» (без preorder-модификатора)
    assert page.locator(BTN_ADD_CART_REAL).count() == 0, (
        "У товара без стока не должно быть обычной кнопки «В корзину»"
    )


def test_price_not_displayed(page: Page):
    """Без стока активная цена `.price.new__price` не отображается."""
    assert page.locator(PRICE_NEW).count() == 0, (
        "У товара-предзаказа не должно быть активной цены .price.new__price"
    )


def test_quantity_controls_disabled(page: Page):
    """Для предзаказа количество не выбирается: − и + заблокированы."""
    expect(page.locator(BTN_QTY_MINUS).first).to_be_disabled()
    expect(page.locator(BTN_QTY_PLUS).first).to_be_disabled()


def test_one_click_and_credit_disabled(page: Page):
    """«Покупка в один клик» и «В кредит» для предзаказа — disabled."""
    one_click = page.locator(BTN_ONE_CLICK).first
    if one_click.count() > 0:
        expect(one_click).to_be_disabled()

    credit = page.locator(BTN_CREDIT).first
    if credit.count() > 0:
        expect(credit).to_be_disabled()


# ===========================================================================
# Поп-ап «Предзаказ»
# ===========================================================================
def test_open_preorder_popup(page: Page):
    """Клик «Предзаказ» открывает поп-ап со всеми ключевыми элементами."""
    modal = _open_preorder_modal(page)

    # Заголовок «Предзаказ»
    expect(modal.locator("h4").filter(has_text=re.compile(r"Предзаказ", re.I)).first).to_be_visible()

    # Подзаголовок про звонок в течение 15 минут
    expect(modal.get_by_text(re.compile(r"15 минут", re.I)).first).to_be_visible()

    # Карточка товара: название + цена
    expect(modal.get_by_text(PRODUCT_NAME).first).to_be_visible()
    expect(modal.get_by_text(re.compile(r"MDL", re.I)).first).to_be_visible()

    # Поле телефона и выбор страны (+373)
    expect(modal.locator(MODAL_PHONE).first).to_be_visible()
    expect(modal.get_by_text(re.compile(r"\+373", re.I)).first).to_be_visible()

    # Кнопка «Оформить заказ» и крестик
    expect(modal.locator(MODAL_SUBMIT).first).to_be_visible()
    expect(modal.locator(MODAL_CLOSE).first).to_be_visible()


def test_preorder_popup_empty_phone_validation(page: Page):
    """Сабмит с пустым телефоном → ошибка валидации, поп-ап не закрывается."""
    modal = _open_preorder_modal(page)

    modal.locator(MODAL_SUBMIT).first.click()

    # Валидация асинхронная — expect сам дождётся появления ошибки.
    phone = modal.locator(MODAL_PHONE).first
    expect(phone).to_have_class(re.compile(r"\berror\b"), timeout=5_000)
    expect(modal.get_by_text(re.compile(r"обязательное поле", re.I)).first).to_be_visible()

    # Поп-ап остаётся открытым (заявка не ушла)
    expect(modal).to_be_visible()


def test_preorder_popup_accepts_valid_phone(page: Page):
    """Валидный телефон принимается и форматируется, ошибки нет."""
    modal = _open_preorder_modal(page)

    phone = _fill_phone(modal, TEST_PHONE)

    # intl-tel-input форматирует номер группами с пробелами: «691 23 456»
    expect(phone).to_have_value(re.compile(r"\d{3}\s\d{2}\s\d{3}"))
    # Класс ошибки на корректном номере не висит
    expect(phone).not_to_have_class(re.compile(r"\berror\b"))


def test_close_preorder_popup(page: Page):
    """Крестик закрывает поп-ап предзаказа."""
    modal = _open_preorder_modal(page)

    modal.locator(MODAL_CLOSE).first.click()
    expect(modal).to_be_hidden(timeout=10_000)


def test_preorder_does_not_add_to_cart(page: Page):
    """Открытие предзаказа не добавляет товар в корзину (сумма в шапке не растёт)."""
    sum_before = _header_cart_sum(page)

    _open_preorder_modal(page)

    sum_after = _header_cart_sum(page)
    assert sum_after == sum_before, (
        f"Предзаказ не должен менять корзину: было {sum_before}, стало {sum_after}"
    )


# ===========================================================================
# Реальная отправка заявки предзаказа (создаёт лид в админке!)
# ===========================================================================
@pytest.mark.real_submit
def test_preorder_real_submit_succeeds(page: Page, pytestconfig):
    """Валидный телефон + «Оформить заказ» → заявка уходит, экран успеха.

    ВНИМАНИЕ: реально отправляет заявку на stage при каждом прогоне
    (POST stage.admin.ecom.md/general/v3/preorder/ → создаёт лид).
    Отключить совсем: pytest -m "not real_submit".

    ПОЧЕМУ ТОЛЬКО --headed: проверено вживую — в headless-Chromium stage
    отклоняет сабмит предзаказа (бот-защита на POST в админку), экран успеха
    не появляется. В headed (и через MCP) заявка проходит штатно. Чтобы не
    плодить ложные падения в обычном headless-прогоне, в headless скипаемся.
    """
    if not pytestconfig.getoption("--headed"):
        pytest.skip("Реальный сабмит предзаказа stage пропускает только в headed — запусти с --headed")

    modal = _open_preorder_modal(page)

    phone = _fill_phone(modal, TEST_PHONE)
    expect(phone).to_have_value(re.compile(r"\d{3}\s\d{2}\s\d{3}"))

    modal.locator(MODAL_SUBMIT).first.click()

    # Поп-ап предзаказа закрывается, появляется экран «Заявка отправлена успешно»
    success = page.locator(MODAL_SUCCESS)
    expect(success).to_be_visible(timeout=20_000)
    expect(success.get_by_text(re.compile(r"Заявка отправлена успешно", re.I)).first).to_be_visible()
    expect(modal).to_be_hidden()

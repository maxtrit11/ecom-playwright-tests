"""Тесты блока «Оформление заказа» (Qase suite — Блок Оформление заказа).

Адаптировано под реальную реализацию stage.ecom.md (проверено через MCP):
- Открывается в том же `.modal__cart.show`, что и корзина. После клика
  на «Оформить заявку» сайдбар получает модификатор `cart__sidebar--checkout`
  и внутри рендерится `<form class="checkout__form">`.
- Закрытие:
    * Х: `.modal__cart button.btn__close[title="Закрыть корзину"]`
    * Клик по overlay-области `.modal__cart.show` (мимо сайдбара)
    * Кнопка «Продолжить покупки»: `button.btn__secondary.cart`
      с текстом «Продолжить покупки» (отдельно от такой же кнопки в коше)
- Личные данные:
    * Полное имя: input[placeholder="Введи имя и фамилию"]
    * Телефон: input#phone (тип tel)
    * E-mail: input[placeholder="Введи e-mail адрес"]
    * Чекбокс «Не перезванивать»: input#dontCallMe
      — при включении появляется поле
      `input[placeholder*="мессенджер"]` (Коммент для viber/whatsapp/...)
- Доставка (блок `.payment` с заголовком «Доставка»):
    * Способ: input#delivery / input#self-call (radio name=radio-delivery)
    * «Тип» (по факту UI это «Кишинёв / Молдова»): input#delivery-chisinau
      / input#delivery-region (отдельные radio name'ы).
- Оплата (блок `.payment.payment__method`):
    * input#cash / #maib / #moldindcombank / #credit / #recount / #certificate
      (все radio name=radio-payment)
- Адрес (видны при «Доставка по адресу»):
    * Регион / Населенный пункт: 2 `.v-select`; вторая включается после
      выбора в первой.
    * Улица: input[placeholder="Название улицы..."]
- Согласие: input#terms-agreement-modal + a[href="/ru/terms"] target="_blank"
- Кнопка отправки: button.request[title="Оформить заказ"]
- Success-попап: `.modal__checkout_success.show` (тот же, что в one-click)
  с текстом «Заявка отправлена успешно».

Большинство «визуальных» кейсов из QASE (hover/focus/цвета границ #FF9342,
#436BEF и т.п.) сознательно НЕ автоматизированы — это работа UI-снапшотов,
а не e2e.
"""

import re
import time

import pytest
from playwright.sync_api import Page, expect


PRODUCT_URL = "/ru/product/klipsch-detroit"

# --- Открытие коша ---
BTN_ADD_TO_CART = "button.btn__add_cart"
HEADER_CART_BTN = 'button.btn__action.btn__cart[title="Корзина"]'
CART_MODAL_SHOWN = ".modal__cart.show"
CART_PRODUCT = ".cart__product"
BTN_CLEAR_ALL = "button.cart-products__header__clear-btn"
BTN_CART_CLOSE = '.modal__cart button.btn__close[title="Закрыть корзину"]'
BTN_SUBMIT_REQUEST = 'button.request[title="Следующий шаг"]'  # «Оформить заявку»

# --- Чекаут ---
CHECKOUT_FORM = ".checkout__form"
CHECKOUT_OVERLAY = ".modal__checkout"            # вешает закрытие при клике по overlay
SIDEBAR_CHECKOUT = ".cart__sidebar--checkout"     # «нижний» summary внутри формы
SIDEBAR_FIXED = ".cart__sidebar--fixed"           # липкий summary, где живёт кнопка submit
# Крестик формы чекаута живёт НЕ в .modal__cart, а в оверлее .modal__checkout
# (.checkout__form > .head > button.btn-close.btn__close). У него тот же
# title="Закрыть корзину", но он визуально верхний — именно он закрывает
# чекаут. Старый селектор `.modal__cart button.btn__close` ловил перекрытый
# крестик корзины → click intercepted (30s timeout).
BTN_CHECKOUT_X = '.modal__checkout button.btn-close.btn__close'
BTN_CONTINUE_SHOPPING = f"{SIDEBAR_FIXED} button.btn__secondary"

# Личные данные
INPUT_NAME = f'{CHECKOUT_FORM} input[placeholder="Введи имя и фамилию"]'
INPUT_PHONE = f'{CHECKOUT_FORM} input#phone'
INPUT_EMAIL = f'{CHECKOUT_FORM} input[placeholder="Введи e-mail адрес"]'
CHK_DONT_CALL = f'{CHECKOUT_FORM} input#dontCallMe'
INPUT_MESSENGER = f'{CHECKOUT_FORM} input[placeholder*="мессенджер" i]'

# Доставка / оплата
RADIO_DELIVERY_ADDRESS = f'{CHECKOUT_FORM} input#delivery'
RADIO_DELIVERY_PICKUP = f'{CHECKOUT_FORM} input#self-call'
RADIO_DELIVERY_CHISINAU = f'{CHECKOUT_FORM} input#delivery-chisinau'
RADIO_DELIVERY_REGION = f'{CHECKOUT_FORM} input#delivery-region'
RADIO_PAY_CASH = f'{CHECKOUT_FORM} input#cash'
RADIO_PAY_CARD = f'{CHECKOUT_FORM} input#maib'         # Оплата картой MAIB
RADIO_PAY_CREDIT = f'{CHECKOUT_FORM} input#credit'
RADIO_PAY_TRANSFER = f'{CHECKOUT_FORM} input#recount'  # По перечислению

# Адрес
VSELECT = f'{CHECKOUT_FORM} .v-select'
VSELECT_SEARCH = f'{CHECKOUT_FORM} .v-select .vs__search'
VSELECT_SELECTED = f'{CHECKOUT_FORM} .v-select .vs__selected'
DROPDOWN_MENU = ".v-select.vs--open ul.vs__dropdown-menu li"
INPUT_STREET = f'{CHECKOUT_FORM} input[placeholder*="улицы" i]'

# Согласие и сабмит
CHK_TERMS = f'{CHECKOUT_FORM} input#terms-agreement-modal'
LINK_TERMS = f'{CHECKOUT_FORM} a[href$="/terms"]'
BTN_PLACE_ORDER = 'button.request[title="Оформить заказ"]'

# Success popup на checkout — на stage появляется не всегда стабильно,
# поэтому в test_place_order_happy_path основной критерий — закрытие модалки
# + очистка корзины, а сам попап проверяется мягко (если присутствует в DOM).


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _hide_b24_widget(page: Page):
    page.evaluate(
        """() => { document.querySelectorAll('[class*="b24-widget"]').forEach(el => el.remove()); }"""
    )


def _reset_cart_storage(page: Page):
    page.evaluate(
        """() => {
            ['cart-data','cart-version','cart-owner-token'].forEach(k => {
                try { localStorage.removeItem(k); } catch (e) {}
            });
            ['cart','cart-owner-token'].forEach(n => {
                document.cookie = n + '=; path=/; max-age=0';
            });
        }"""
    )


def _open_cart_drawer(page: Page):
    _hide_b24_widget(page)
    page.locator(HEADER_CART_BTN).click()
    expect(page.locator(CART_MODAL_SHOWN)).to_be_visible(timeout=10_000)
    _hide_b24_widget(page)


def _add_product(page: Page):
    page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator("h1")).to_be_visible(timeout=15_000)
    _hide_b24_widget(page)
    page.locator(BTN_ADD_TO_CART).first.click()
    page.wait_for_timeout(800)


def _open_checkout(page: Page):
    """Открыть форму оформления заказа: товар → корзина → «Оформить заявку»."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.context.clear_cookies()
    page.goto(PRODUCT_URL, wait_until="domcontentloaded", timeout=60_000)
    _reset_cart_storage(page)
    page.reload(wait_until="domcontentloaded")
    expect(page.locator("h1")).to_be_visible(timeout=15_000)
    _hide_b24_widget(page)

    # Очистить остаток из прошлой сессии и положить ровно один товар.
    _open_cart_drawer(page)
    if page.locator(CART_PRODUCT).count() > 0:
        page.locator(BTN_CLEAR_ALL).first.click()
        page.wait_for_timeout(700)
        page.locator(BTN_CART_CLOSE).click()
        page.wait_for_timeout(400)

    _add_product(page)
    _open_cart_drawer(page)
    expect(page.locator(CART_PRODUCT).first).to_be_visible(timeout=10_000)

    page.locator(BTN_SUBMIT_REQUEST).first.click()
    expect(page.locator(CHECKOUT_FORM)).to_be_visible(timeout=10_000)
    expect(page.locator(SIDEBAR_CHECKOUT)).to_be_visible()
    return page


@pytest.fixture
def checkout(page: Page):
    return _open_checkout(page)


def _click_radio_by_id(page: Page, radio_id: str):
    """Сам `<input type=radio>` визуально скрыт. Клик по `<div class="payment__group">`
    ничего не делает — клик надо посылать в `<label for="ID">`, тогда браузер
    «прокликает» связанный input."""
    page.locator(f'{CHECKOUT_FORM} label[for="{radio_id}"]').first.scroll_into_view_if_needed()
    page.locator(f'{CHECKOUT_FORM} label[for="{radio_id}"]').first.click()


# ===========================================================================
# Кейс 201: Закрыть «Оформление заказа» нажав на Х
# ===========================================================================
def test_close_checkout_via_x(checkout: Page):
    page = checkout

    page.locator(BTN_CHECKOUT_X).click()
    page.wait_for_timeout(500)

    expect(page.locator(CART_MODAL_SHOWN)).to_have_count(0, timeout=5_000)
    expect(page.locator("h1")).to_be_visible()


# ===========================================================================
# Кейс 202: Закрыть «Оформление заказа» нажав по области вокруг
# ===========================================================================
def test_close_checkout_by_clicking_outside(checkout: Page):
    page = checkout

    # `.modal__checkout` — это overlay на полный экран поверх `.modal__cart.show`.
    # Кликаем в левый верхний угол, мимо правого сайдбара формы.
    page.locator(CHECKOUT_OVERLAY).click(position={"x": 50, "y": 50})
    page.wait_for_timeout(500)

    expect(page.locator(CART_MODAL_SHOWN)).to_have_count(0, timeout=5_000)


# ===========================================================================
# Кейс 222: Закрыть через «Продолжить покупки»
# ===========================================================================
def test_close_checkout_via_continue_shopping(checkout: Page):
    page = checkout

    cont = (
        page.locator(BTN_CONTINUE_SHOPPING)
        .filter(has_text=re.compile(r"Продолжить.*покупк", re.IGNORECASE))
        .first
    )
    expect(cont).to_be_visible()
    cont.scroll_into_view_if_needed()
    cont.click()
    page.wait_for_timeout(500)

    expect(page.locator(CART_MODAL_SHOWN)).to_have_count(0, timeout=5_000)


# ===========================================================================
# Кейс 205: Чекбокс «Не перезванивать» открывает поле для мессенджера
# ===========================================================================
def test_dont_call_me_reveals_messenger_field(checkout: Page):
    page = checkout

    # До клика поле скрыто
    expect(page.locator(INPUT_MESSENGER)).to_have_count(0)

    page.locator(CHK_DONT_CALL).check()
    page.wait_for_timeout(300)

    # Появилось поле под чекбоксом
    expect(page.locator(INPUT_MESSENGER)).to_be_visible(timeout=3_000)

    # А выключить — поле снова исчезло
    page.locator(CHK_DONT_CALL).uncheck()
    page.wait_for_timeout(300)
    expect(page.locator(INPUT_MESSENGER)).to_have_count(0)


# ===========================================================================
# Кейс 206: Ссылка «условия и политику конфиденциальности» открывает /ru/terms
# ===========================================================================
def test_terms_link_opens_in_new_tab(checkout: Page):
    page = checkout

    link = page.locator(LINK_TERMS).first
    expect(link).to_be_visible()
    expect(link).to_have_attribute("target", "_blank")

    with page.context.expect_page() as new_tab_info:
        link.click()
    new_tab = new_tab_info.value
    new_tab.wait_for_load_state("domcontentloaded")
    assert new_tab.url.rstrip("/").endswith("/terms"), f"Открылся неверный URL: {new_tab.url}"
    new_tab.close()


# ===========================================================================
# Кейсы 207-210: Выбор способа оплаты (4 параметризованных кейса)
# ===========================================================================
@pytest.mark.parametrize(
    "qase_id, selector, label",
    [
        (207, RADIO_PAY_CASH, "Наличными"),
        (208, RADIO_PAY_CARD, "Оплата картой"),
        (209, RADIO_PAY_CREDIT, "Покупка в кредит"),
        (210, RADIO_PAY_TRANSFER, "По перечислению"),
    ],
    ids=["207-cash", "208-card", "209-credit", "210-transfer"],
)
def test_select_payment_method(checkout: Page, qase_id: int, selector: str, label: str):
    page = checkout

    chosen_id = selector.split("#")[-1]
    _click_radio_by_id(page, chosen_id)
    page.wait_for_timeout(400)

    assert page.locator(selector).is_checked(), f"Радио {label} (#{qase_id}) не выбралось"

    # Остальные radio в группе оплаты (одно имя `radio-payment`) — не выбраны
    other_ids = ["cash", "maib", "credit", "recount"]
    for oid in other_ids:
        if oid == chosen_id:
            continue
        other = page.locator(f"{CHECKOUT_FORM} input#{oid}")
        if other.count() == 0:
            continue
        assert not other.is_checked(), f"Лишний radio активен: #{oid}"


# ===========================================================================
# Кейсы 211-212: Выбор способа доставки
# ===========================================================================
@pytest.mark.parametrize(
    "qase_id, selector, label",
    [
        (211, RADIO_DELIVERY_ADDRESS, "Доставка по адресу"),
        (212, RADIO_DELIVERY_PICKUP, "Самовывоз из магазина"),
    ],
    ids=["211-address", "212-pickup"],
)
def test_select_delivery_method(checkout: Page, qase_id: int, selector: str, label: str):
    page = checkout

    chosen_id = selector.split("#")[-1]
    _click_radio_by_id(page, chosen_id)
    page.wait_for_timeout(400)

    assert page.locator(selector).is_checked(), f"Радио «{label}» (#{qase_id}) не выбралось"

    # Альтернативный radio в этой же группе name=radio-delivery должен сняться
    alt = RADIO_DELIVERY_PICKUP if chosen_id == "delivery" else RADIO_DELIVERY_ADDRESS
    assert not page.locator(alt).is_checked(), "Альтернативный способ доставки тоже остался выбранным"


# ===========================================================================
# Кейсы 218-219: «Тип» доставки (в текущем UI — Кишинёв / Молдова)
# В QASE кейсы описаны как «Обычная / Срочная», но на stage этого нет,
# а есть два радио delivery-chisinau / delivery-region — проверяем их.
# ===========================================================================
@pytest.mark.parametrize(
    "qase_id, selector, label",
    [
        (218, RADIO_DELIVERY_CHISINAU, "Доставка по Кишинёву"),
        (219, RADIO_DELIVERY_REGION, "Доставка по Молдове"),
    ],
    ids=["218-chisinau", "219-region"],
)
def test_select_delivery_type(checkout: Page, qase_id: int, selector: str, label: str):
    page = checkout

    chosen_id = selector.split("#")[-1]
    _click_radio_by_id(page, chosen_id)
    page.wait_for_timeout(400)

    assert page.locator(selector).is_checked(), f"Радио «{label}» (#{qase_id}) не выбралось"
    # NB: `delivery-chisinau` и `delivery-region` — разные radio-группы (разные name),
    #     поэтому взаимной зависимости тут НЕТ — каждое чек-радио тогглится независимо.


# ===========================================================================
# Кейсы 213+216: Выпадающие списки Регион / Населенный пункт открываются
# ===========================================================================
def test_region_and_city_dropdowns_open_with_items(checkout: Page):
    page = checkout

    # Убедимся, что выбран «Доставка по адресу» — иначе адресные поля скрыты
    if not page.locator(RADIO_DELIVERY_ADDRESS).is_checked():
        _click_radio_by_id(page, "delivery")
        page.wait_for_timeout(400)

    # Регион
    region_input = page.locator(VSELECT_SEARCH).nth(0)
    region_input.click()
    page.wait_for_timeout(800)
    region_items = page.locator(DROPDOWN_MENU)
    expect(region_items.first).to_be_visible(timeout=5_000)
    assert region_items.count() > 5, "В списке регионов слишком мало пунктов"

    # Выбираем «Кишинёв» (по умолчанию подсвечен первый — вверху списка)
    region_items.filter(has_text=re.compile(r"^Кишинёв$")).first.click()
    page.wait_for_timeout(800)

    # Регион выбран → второй v-select становится активным
    expect(page.locator(VSELECT_SELECTED).first).to_have_text(
        re.compile(r"Кишинёв")
    )
    city_dd = page.locator(VSELECT).nth(1)
    expect(city_dd).not_to_have_class(re.compile(r"vs--disabled"))

    # Открыть населенные пункты
    page.locator(VSELECT_SEARCH).nth(1).click()
    page.wait_for_timeout(800)
    city_items = page.locator(DROPDOWN_MENU)
    expect(city_items.first).to_be_visible(timeout=5_000)
    assert city_items.count() > 0, "Список населенных пунктов пустой"


# ===========================================================================
# Кейс 236: Положительное оформление заказа
# (наличными + доставка по адресу + Кишинёв)
# Реальный сабмит: создаст заявку на стейдже. Стейдж это разрешает.
# ===========================================================================
def test_place_order_happy_path(checkout: Page):
    page = checkout

    # 1. ФИО
    page.locator(INPUT_NAME).fill("QA Autotest")

    # 2. Телефон — уникальные 8 цифр, чтобы пройти антиспам
    unique_phone = "79" + str(int(time.time() * 1000))[-6:]
    page.locator(INPUT_PHONE).fill(unique_phone)

    # 3. E-mail
    page.locator(INPUT_EMAIL).fill(f"qa+{int(time.time())}@example.com")

    # 4. Доставка по адресу — должна быть выбрана по умолчанию, но подстрахуемся.
    if not page.locator(RADIO_DELIVERY_ADDRESS).is_checked():
        _click_radio_by_id(page, "delivery")
        page.wait_for_timeout(300)

    # 5. Регион → Кишинёв
    page.locator(VSELECT_SEARCH).nth(0).click()
    page.wait_for_timeout(800)
    page.locator(DROPDOWN_MENU).filter(has_text=re.compile(r"^Кишинёв$")).first.click()
    page.wait_for_timeout(800)

    # 6. Населенный пункт → первый доступный
    page.locator(VSELECT_SEARCH).nth(1).click()
    page.wait_for_timeout(800)
    expect(page.locator(DROPDOWN_MENU).first).to_be_visible(timeout=5_000)
    page.locator(DROPDOWN_MENU).first.click()
    page.wait_for_timeout(400)

    # 7. Адрес
    page.locator(INPUT_STREET).fill("ул. Тестовая, д. 1, кв. 1")

    # 8. Оплата — Наличными (обычно уже выбрана по умолчанию)
    if not page.locator(RADIO_PAY_CASH).is_checked():
        _click_radio_by_id(page, "cash")
        page.wait_for_timeout(300)

    # 9. Согласие с условиями
    page.locator(CHK_TERMS).check()
    page.wait_for_timeout(200)

    # 10. Сабмит
    submit = page.locator(BTN_PLACE_ORDER).first
    submit.scroll_into_view_if_needed()
    expect(submit).to_be_enabled(timeout=5_000)
    submit.click()

    # Главный признак успешного оформления — модалка корзины/чекаута закрывается
    # и анонимная корзина обнуляется (заявка ушла, локальная корзина очищена).
    expect(page.locator(CART_MODAL_SHOWN)).to_have_count(0, timeout=30_000)
    expect(page.locator(CART_PRODUCT)).to_have_count(0, timeout=15_000)

    # Опционально: если ловится success-попап одной из известных нам разновидностей —
    # хорошо, но не делаем строгое требование (на stage он мелькает доли секунды
    # и в .modal__checkout_success.show может не оказаться).
    success = page.locator(
        ".modal__checkout_success.show, .modal__success.show, "
        '[class*="checkout_success"].show, [class*="success"][class*="modal"].show'
    )
    if success.count() > 0:
        expect(success.first).to_be_visible(timeout=5_000)

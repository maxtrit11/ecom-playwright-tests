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


# Товар выбирается динамически фикстурой `in_stock_product` (conftest.py):
# если у товара нет стока — берётся следующий доступный, без залипания на одном.

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

# --- Валидация обязательных полей (кейс 376) ---
# Проверено probe-скриптом на живом stage. При сабмите пустой формы:
#   * обёртка телефона (`.phone`) получает класс `error`;
#   * v-select Населенный пункт рисует `.g-select-search-error`;
#   * блок согласия получает `.terms_error`;
#   * под обязательными полями появляются ВИДИМЫЕ `span.validation`
#     с текстом «Это обязательное поле» (в DOM они есть всегда, но скрыты,
#     пока поле не отвалидировано — поэтому фильтруем по `:visible`).
REQUIRED_MSG = "Это обязательное поле"
VIS_VALIDATION = f"{CHECKOUT_FORM} span.validation:visible"

# --- Блок итогов (стоимость товара / доставка / итог) ---
# Сводка живёт в липком сайдбаре `.cart__sidebar--fixed` строками `.list__item`.
# Стоимость доставки динамическая: Кишинёв ≠ Молдова, а при самовывозе строка
# доставки из итогов исчезает (проверено probe-скриптом на stage).
SUMMARY_ITEMS = ".cart__sidebar .list__items .list__item"
ERR_REQUIRED = f"{CHECKOUT_FORM} .g-select-search-error"
ERR_PHONE = f"{CHECKOUT_FORM} .phone.error"
ERR_TERMS = f"{CHECKOUT_FORM} .terms.terms_error"
CHK_DONT_CALL_LABEL = f'{CHECKOUT_FORM} label[for="dontCallMe"]'

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


def _add_product(page: Page, product_url: str):
    page.goto(product_url, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator("h1")).to_be_visible(timeout=15_000)
    _hide_b24_widget(page)
    page.locator(BTN_ADD_TO_CART).first.click()
    page.wait_for_timeout(800)


def _open_checkout(page: Page, product_url: str):
    """Открыть форму оформления заказа: товар → корзина → «Оформить заявку»."""
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.context.clear_cookies()
    page.goto(product_url, wait_until="domcontentloaded", timeout=60_000)
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

    _add_product(page, product_url)
    _open_cart_drawer(page)
    expect(page.locator(CART_PRODUCT).first).to_be_visible(timeout=10_000)

    page.locator(BTN_SUBMIT_REQUEST).first.click()
    expect(page.locator(CHECKOUT_FORM)).to_be_visible(timeout=10_000)
    expect(page.locator(SIDEBAR_CHECKOUT)).to_be_visible()
    return page


@pytest.fixture
def checkout(page: Page, in_stock_product: str):
    return _open_checkout(page, in_stock_product)


def _click_radio_by_id(page: Page, radio_id: str):
    """Сам `<input type=radio>` визуально скрыт. Клик по `<div class="payment__group">`
    ничего не делает — клик надо посылать в `<label for="ID">`, тогда браузер
    «прокликает» связанный input."""
    page.locator(f'{CHECKOUT_FORM} label[for="{radio_id}"]').first.scroll_into_view_if_needed()
    page.locator(f'{CHECKOUT_FORM} label[for="{radio_id}"]').first.click()


def _require_option(page: Page, radio_id: str, human: str):
    """Набор способов оплаты/доставки зависит от товара (настраивается в админке).
    Если у выбранного товара такой опции нет — корректно пропускаем тест,
    а не падаем по таймауту."""
    if page.locator(f'{CHECKOUT_FORM} label[for="{radio_id}"]').count() == 0:
        pytest.skip(f"Опция «{human}» недоступна для выбранного товара")


def _sector_vselect_index(page: Page) -> int:
    """Индекс v-select сектора/населённого пункта внутри формы.

    После выбора типа доставки «Кишинёв» регион предзаполняется («мун. Кишинёв»),
    а в форме остаётся и ЛИШНИЙ задизейбленный v-select (вариант «Молдова»),
    поэтому брать `.last`/`.nth(1)` нельзя. Сектор — это единственный активный
    (`не vs--disabled`) v-select без уже выбранного значения. Возвращает -1,
    если такого нет (например, населённый пункт предустановлен).
    """
    return page.evaluate(
        """() => {
            const vs = [...document.querySelectorAll('.checkout__form .v-select')];
            for (let i = 0; i < vs.length; i++) {
                const disabled = vs[i].className.includes('vs--disabled');
                const sel = vs[i].querySelector('.vs__selected');
                const hasSel = sel && sel.innerText.trim().length > 0;
                if (!disabled && !hasSel) return i;
            }
            return -1;
        }"""
    )


def _setup_chisinau_address(page: Page) -> bool:
    """Настроить адрес доставки по Кишинёву.

    ВАЖНО про модель UI (проверено через MCP на живом stage):
    «Кишинёв» — это НЕ пункт выпадающего списка региона, а отдельный radio
    типа доставки `#delivery-chisinau`. При его выборе:
      * первый v-select автозаполняется «мун. Кишинёв» (регион проставляется сам);
      * активный пустой v-select становится выбором СЕКТОРА
        (Ботаника / Буюканы / Рышкановка / Скулянка / Центр / Чеканы);
      * рядом остаётся задизейбленный v-select варианта «Молдова» — его игнорируем.
    Список же `#delivery-region` («Молдова») содержит 36 районов и Кишинёва там нет.

    Возвращает True, если адрес настроен; False — если тип «Кишинёв» недоступен
    для товара (вызывающий код сам решает, скипать или нет).
    """
    # Доставка по адресу (обычно выбрана по умолчанию)
    _require_option(page, "delivery", "Доставка по адресу")
    if not page.locator(RADIO_DELIVERY_ADDRESS).is_checked():
        _click_radio_by_id(page, "delivery")
        page.wait_for_timeout(400)

    # Тип доставки = Кишинёв (radio сам проставляет регион «мун. Кишинёв»)
    if page.locator(f'{CHECKOUT_FORM} label[for="delivery-chisinau"]').count() == 0:
        return False
    _click_radio_by_id(page, "delivery-chisinau")
    page.wait_for_timeout(800)

    # Выбрать сектор в активном пустом v-select. У части товаров сектор/город
    # уже предустановлен (активного пустого v-select нет, idx == -1) — тогда
    # адрес и так валиден, выбирать нечего.
    idx = _sector_vselect_index(page)
    if idx >= 0:
        page.locator(VSELECT_SEARCH).nth(idx).click()
        page.wait_for_timeout(800)
        sector_items = page.locator(DROPDOWN_MENU)
        expect(sector_items.first).to_be_visible(timeout=5_000)
        sector_items.first.click()
        page.wait_for_timeout(400)
    return True


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

    # Сам input#dontCallMe визуально скрыт — кликаем по связанному label
    page.locator(CHK_DONT_CALL_LABEL).first.click()
    page.wait_for_timeout(300)

    # Появилось поле под чекбоксом
    expect(page.locator(INPUT_MESSENGER)).to_be_visible(timeout=3_000)

    # А выключить — поле снова исчезло
    page.locator(CHK_DONT_CALL_LABEL).first.click()
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
    _require_option(page, chosen_id, label)
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
    _require_option(page, chosen_id, label)
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
    _require_option(page, chosen_id, label)
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
    _require_option(page, "delivery", "Доставка по адресу")
    if not page.locator(RADIO_DELIVERY_ADDRESS).is_checked():
        _click_radio_by_id(page, "delivery")
        page.wait_for_timeout(400)

    # «Кишинёв» — это radio типа доставки, а не пункт списка региона. До его
    # выбора v-select'ы региона/сектора задизейблены. Если у товара такого типа
    # нет — корректно пропускаем.
    if page.locator(f'{CHECKOUT_FORM} label[for="delivery-chisinau"]').count() == 0:
        pytest.skip("Тип доставки «Кишинёв» недоступен для этого товара")
    _click_radio_by_id(page, "delivery-chisinau")
    page.wait_for_timeout(800)

    # Регион проставился сам → первый v-select показывает «мун. Кишинёв»
    expect(page.locator(VSELECT_SELECTED).first).to_have_text(
        re.compile(r"Кишинёв")
    )

    # Активный пустой v-select (сектор) открывается со списком пунктов.
    # У части товаров сектор/город предустановлен — выпадающего списка нет,
    # проверять нечего → корректно пропускаем.
    idx = _sector_vselect_index(page)
    if idx < 0:
        pytest.skip("Сектор/населённый пункт предустановлен — выпадающего списка нет")
    page.locator(VSELECT_SEARCH).nth(idx).click()
    page.wait_for_timeout(800)
    sector_items = page.locator(DROPDOWN_MENU)
    expect(sector_items.first).to_be_visible(timeout=5_000)
    assert sector_items.count() > 0, "Список секторов/населенных пунктов пустой"


# ---------------------------------------------------------------------------
# Хелпер сабмита формы
# ---------------------------------------------------------------------------
OUT_OF_STOCK = ".cart__error-stock, .cart__product--out-of-stock"


def _skip_if_out_of_stock(page: Page):
    """Кнопки «Следующий шаг»/«Оформить заказ» становятся disabled при нулевом
    остатке (корзина рисует `.cart__error-stock` / `.cart__product--out-of-stock`).
    Остаток на stage волатилен и может обнулиться уже ПОСЛЕ резолва товара
    фикстурой — тогда любой клик по сабмиту висит до 30s-таймаута и даёт false-fail.
    Корректно пропускаем такой кейс (документированная флакость стока)."""
    if page.locator(OUT_OF_STOCK).count() > 0:
        pytest.skip("Товар фактически вне стока (Доступное количество 0) — сабмит недоступен")


def _click_place_order(page: Page):
    """Нажать «Оформить заказ». При невалидной форме сабмит не уходит —
    модалка остаётся открытой и подсвечивает обязательные поля."""
    _skip_if_out_of_stock(page)
    btn = page.locator(BTN_PLACE_ORDER).first
    btn.scroll_into_view_if_needed()
    btn.click()
    page.wait_for_timeout(800)


def _delivery_cost_in_summary(page: Page):
    """Стоимость доставки (число) из строки «Доставка …» блока итогов.
    None — если строки доставки в итогах нет (например, самовывоз)."""
    row = page.locator(SUMMARY_ITEMS).filter(has_text=re.compile(r"Доставка"))
    if row.count() == 0:
        return None
    m = re.search(r"(\d[\d\s]*)\s*MDL", row.first.inner_text())
    return int(re.sub(r"\D", "", m.group(1))) if m else None


# ===========================================================================
# Кейс 376 (шаг 1): сабмит пустой формы подсвечивает обязательные поля
# ===========================================================================
def test_required_fields_errors_on_empty_submit(checkout: Page):
    page = checkout

    # До сабмита ошибок обязательных полей нет
    expect(page.locator(ERR_PHONE)).to_have_count(0)
    expect(page.locator(ERR_TERMS)).to_have_count(0)

    _click_place_order(page)

    # Форма не закрылась (сабмит заблокирован валидацией)
    expect(page.locator(CHECKOUT_FORM)).to_be_visible()

    # Обёртка телефона и блок согласия подсвечены ошибкой (стабильные сигналы)
    expect(page.locator(ERR_PHONE)).to_have_count(1, timeout=5_000)
    expect(page.locator(ERR_TERMS)).to_have_count(1)

    # Под обязательными полями виден текст «Это обязательное поле»
    # (v-select Населенный пункт грузится асинхронно — даём expect авто-ретраить)
    req_msg = page.locator(VIS_VALIDATION).filter(has_text=REQUIRED_MSG)
    expect(req_msg.first).to_be_visible(timeout=10_000)


# ===========================================================================
# Кейс 376 (шаг 8): оплата «По перечислению» добавляет обязательные поля юрлица
# ===========================================================================
def test_transfer_payment_reveals_required_legal_fields(checkout: Page):
    page = checkout

    # Число видимых ошибок обязательных полей до выбора перечисления
    _click_place_order(page)
    errors_before = page.locator(VIS_VALIDATION).count()

    # Выбираем «По перечислению»
    _click_radio_by_id(page, "recount")
    page.wait_for_timeout(500)

    # Появились поля юрлица
    for label in ["Название фирмы", "Фискальный код", "Юридический адрес", "IBAN"]:
        expect(page.locator(CHECKOUT_FORM).get_by_text(label, exact=False).first).to_be_visible(
            timeout=5_000
        )

    # Повторный сабмит — обязательных ошибок стало больше (добавились поля юрлица)
    _click_place_order(page)
    errors_after = page.locator(VIS_VALIDATION).count()
    assert errors_after > errors_before, (
        f"После «По перечислению» число обязательных ошибок не выросло: "
        f"{errors_before} → {errors_after}"
    )


# ===========================================================================
# Кейс 376 (шаг 9): «Не перезванивать» открывает поле мессенджера
# и снимает обязательность телефона
# ===========================================================================
def test_dont_call_makes_phone_optional(checkout: Page):
    page = checkout

    # Сначала убеждаемся, что без галочки телефон обязателен
    _click_place_order(page)
    expect(page.locator(ERR_PHONE)).to_have_count(1, timeout=5_000)

    # Включаем «Не перезванивать» (клик по label — сам input скрыт)
    page.locator(CHK_DONT_CALL_LABEL).first.click()
    page.wait_for_timeout(400)

    # Появилось поле мессенджера
    expect(page.locator(INPUT_MESSENGER)).to_be_visible(timeout=3_000)

    # Повторный сабмит: телефон больше НЕ обязательный — класс error снят
    _click_place_order(page)
    expect(page.locator(ERR_PHONE)).to_have_count(0, timeout=5_000)


# ===========================================================================
# Доп. к 376: стоимость доставки в итогах меняется при смене типа/способа
# (Кишинёв ≠ Молдова; самовывоз убирает доставку из суммы)
# ===========================================================================
def test_delivery_cost_updates_in_summary(checkout: Page):
    page = checkout

    # Доставка по адресу выбрана по умолчанию — подстрахуемся
    if not page.locator(RADIO_DELIVERY_ADDRESS).is_checked():
        _click_radio_by_id(page, "delivery")
        page.wait_for_timeout(500)

    # Тип доставки = Кишинёв → есть ненулевая стоимость доставки
    _click_radio_by_id(page, "delivery-chisinau")
    page.wait_for_timeout(1_000)
    chisinau = _delivery_cost_in_summary(page)
    assert chisinau and chisinau > 0, (
        f"В итогах нет стоимости доставки по Кишинёву: {chisinau}"
    )

    # Тип доставки = Молдова → стоимость доставки изменилась
    _click_radio_by_id(page, "delivery-region")
    page.wait_for_timeout(1_000)
    region = _delivery_cost_in_summary(page)
    assert region and region != chisinau, (
        f"Стоимость доставки не изменилась при смене Кишинёв→Молдова: "
        f"{chisinau} → {region}"
    )

    # Способ = Самовывоз → строка доставки исчезает из итогов
    _click_radio_by_id(page, "self-call")
    expect(
        page.locator(SUMMARY_ITEMS).filter(has_text=re.compile(r"Доставка"))
    ).to_have_count(0, timeout=5_000)


# ===========================================================================
# Кейс 236: Положительное оформление заказа
# (наличными + доставка по адресу + Кишинёв)
# Реальный сабмит: создаст заявку на стейдже. Стейдж это разрешает.
#
# ВАЖНО — этот тест ОФОРМЛЯЕТ настоящий заказ и тем самым РАСХОДУЕТ остаток
# выбранного товара. Поэтому он намеренно объявлен ПОСЛЕДНИМ в файле: pytest
# гонит тесты в порядке определения, и happy_path тратит сток уже после всех
# остальных submit-кейсов (376-я серия кликает «Оформить заказ» для проверки
# валидации — этой кнопки не будет, если сток упадёт до 0). Не переносите его
# выше валидационных тестов.
# ===========================================================================
def test_place_order_happy_path(checkout: Page):
    page = checkout

    # 0. Реальный сток. Фикстура `_has_stock` отсеивает товары с нулевым остатком,
    #    но остаток на stage волатилен и мог обнулиться между резолвом и сабмитом
    #    (в т.ч. этим же тестом при ретрае) — тогда сабмит disabled, корректно скипаем.
    _skip_if_out_of_stock(page)

    # 1. ФИО
    page.locator(INPUT_NAME).fill("QA Autotest")

    # 2. Телефон — уникальные 8 цифр, чтобы пройти антиспам
    unique_phone = "79" + str(int(time.time() * 1000))[-6:]
    page.locator(INPUT_PHONE).fill(unique_phone)

    # 3. E-mail
    page.locator(INPUT_EMAIL).fill(f"qa+{int(time.time())}@example.com")

    # 4-6. Доставка по адресу + тип «Кишинёв» (регион проставляется сам) + сектор.
    #      На stage «Кишинёв» — это radio типа доставки, а не пункт списка региона
    #      (подробности в _setup_chisinau_address). Если тип «Кишинёв» недоступен
    #      для товара — сценарий неприменим, корректно пропускаем.
    if not _setup_chisinau_address(page):
        pytest.skip("Тип доставки «Кишинёв» недоступен для выбранного товара")

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

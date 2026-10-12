"""Тесты блока «Оформление заказа» (Qase suite — Блок Оформление заказа).

Адаптировано под реальную реализацию stage.ecom.md (проверено через MCP):
- Открывается в том же `.modal__cart.show`, что и корзина. После клика
  на «Оформить заявку» сайдбар получает модификатор `cart__sidebar--checkout`
  и внутри рендерится `<form class="checkout__form">`.
- Закрытие:
    * Х: `.modal__cart button.btn__close[title="Закрыть корзину"]`
    * Клик по overlay-области `.modal__cart.show` (мимо сайдбара)
    * Кнопки «Продолжить покупки» в форме больше нет (убрана разработчиком
      10.2026) — Кейс 222 удалён вместе с ней
- Личные данные:
    * Полное имя: input[placeholder="Введи имя и фамилию"]
    * Телефон: единственный input[type="tel"] в форме (id плавает: был
      `phone`, стал `checkout-phone` — см. комментарий у INPUT_PHONE)
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

from conftest import CART_VIEW_POPUP, wait_until
from test_cart_block import _click_add_to_cart, _click_until


@pytest.fixture(autouse=True)
def only_popup_cart_view(require_cart_view):
    """Чекаут этого файла живёт внутри поп-апа корзины — только Вид 1.

    При Виде 2 оформление идёт формой на странице /cart (её проверяет
    test_cart_page.py), поп-апа нет, и все 19 тестов файла падали с
    «.modal__cart.show не найден» вместо честного скипа (ночь 2026-08-20).
    """
    require_cart_view(CART_VIEW_POPUP, "корзина поп-апом")


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

# Личные данные
INPUT_NAME = f'{CHECKOUT_FORM} input[placeholder="Введи имя и фамилию"]'
# Телефон ищем по типу поля, а НЕ по id: 01.09.2026 фронт переименовал
# `id="phone"` → `id="checkout-phone"`, и прогон встал на 45-секундном
# таймауте клика. В форме ровно один `input[type="tel"]` (проверено в
# браузере на свежей загрузке с cache-buster), так что селектор однозначный
# и переживёт следующее переименование. Поп-апы one-click/кредита/предзаказа
# уже искали телефон именно так — они этим изменением и не сломались.
INPUT_PHONE = f'{CHECKOUT_FORM} input[type="tel"]'
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
# Подтверждение заказа. Видимый узел — `.checkout__success_content`; обёртка
# `.modal__checkout_success.show` при этом offsetParent === null, поэтому
# ждать надо именно контент (проверено через MCP 2026-08-20).
SUCCESS_POPUP = ".checkout__success_content"
# Поля, подсвеченные формой как незаполненные. Класс `unvalid`, НЕ `invalid`.
INVALID_FIELD = f"{CHECKOUT_FORM} .unvalid"

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
# На странице ТРИ сайдбара `.cart__sidebar` (проверено вживую 2026-08-12):
#   [0] `.cart__sidebar`            — конфигурация корзины (товары/скидка/итог);
#   [1] `.cart__sidebar--checkout`  — сводка формы оформления: товары, ДОСТАВКА,
#       скидка и прогресс-строка «Бесплатная доставка» (`.--proggress-bar`);
#   [2] `.cart__sidebar--fixed`     — липкая строка «Итог».
# Поэтому широкий `.cart__sidebar .list__item` собирает строки из всех трёх и
# `.first` цепляет не тот блок — читаем сводку строго из `--checkout`, а итог
# из `--fixed`.
SUMMARY_ITEMS = ".cart__sidebar .list__items .list__item"
CHECKOUT_SUMMARY = ".cart__sidebar--checkout"
CHECKOUT_SUMMARY_ROWS = f"{CHECKOUT_SUMMARY} .list__item"
SUMMARY_TOTAL = ".cart__sidebar--fixed .list__total.sum"
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
    # Ждём смены надписи корзины в шапке («Корзина» → сумма), а не 800 мс:
    # пауза не ловила потерянный клик, и форма открывалась с пустой корзиной.
    _click_add_to_cart(page)


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
        _click_until(
            page,
            page.locator(BTN_CLEAR_ALL).first,
            lambda: page.locator(CART_PRODUCT).count() == 0,
        )
        _click_until(
            page,
            page.locator(BTN_CART_CLOSE),
            lambda: page.locator(CART_MODAL_SHOWN).count() == 0,
        )

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
    «прокликает» связанный input.

    Докручиваем подпись к СЕРЕДИНЕ экрана, а не «до края» (scroll_into_view_if_needed):
    на телефоне к низу формы прилип блок итога с кнопками (~290px), и подпись,
    доведённая до нижнего края, оказывалась под ним — клик приходился в ссылку
    «условия…», радио не переключалось (мобильная суита, 29.09.2026). На
    десктопе от этого ничего не меняется."""
    label = page.locator(f'{CHECKOUT_FORM} label[for="{radio_id}"]').first
    label.evaluate("el => el.scrollIntoView({block: 'center'})")
    label.click()


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


def _wait_sector_vselect(page: Page, timeout: int = 10_000) -> int:
    """Дождаться, пока после выбора «Кишинёв» появится v-select сектора.

    Блок адреса перерисовывается не мгновенно — секунду-две. Фиксированной
    паузы тут мало: если не дождаться, `_sector_vselect_index` вернёт -1, что
    неотличимо от честного «сектор предустановлен», и тест уйдёт сабмитить
    форму без обязательного поля. Наблюдаемо это выглядит хуже некуда —
    POST на создание заказа не уходит ВООБЩЕ, форма ничего не подсвечивает,
    а тест падает много позже с «нет подтверждения» (прогон 32338373909).
    """
    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        idx = _sector_vselect_index(page)
        if idx >= 0:
            return idx
        page.wait_for_timeout(300)
    return -1


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
        expect(page.locator(RADIO_DELIVERY_ADDRESS)).to_be_checked(timeout=5_000)

    # Тип доставки = Кишинёв (radio сам проставляет регион «мун. Кишинёв»)
    if page.locator(f'{CHECKOUT_FORM} label[for="delivery-chisinau"]').count() == 0:
        return False
    _click_radio_by_id(page, "delivery-chisinau")
    expect(page.locator(RADIO_DELIVERY_CHISINAU)).to_be_checked(timeout=5_000)

    # Выбрать сектор в активном пустом v-select. У части товаров сектор/город
    # уже предустановлен (активного пустого v-select нет, idx == -1) — тогда
    # адрес и так валиден, выбирать нечего.
    idx = _wait_sector_vselect(page)
    if idx < 0:
        return True

    # Адресуем сам v-select и кликаем его внутренний `.vs__search`, а НЕ
    # `.vs__search` по общему индексу: индекс считался среди `.v-select`, а
    # применялся к другому набору узлов. Наборы совпадают не всегда (у
    # задизейбленного v-select своя структура), и тогда открывался соседний
    # список — сектор оставался пустым.
    sector = page.locator(f"{CHECKOUT_FORM} .v-select").nth(idx)

    # Две попытки: список рендерится асинхронно, и первый клик иногда уходит
    # в пустоту (та же гонка, что и с поп-апом корзины).
    for _ in range(2):
        sector.locator(".vs__search").click()
        items = page.locator(DROPDOWN_MENU)
        try:
            expect(items.first).to_be_visible(timeout=5_000)
        except AssertionError:
            continue
        items.first.click()
        # Ждём, что значение реально проставилось, а не 400 мс наугад.
        try:
            expect(sector.locator(".vs__selected")).to_have_text(
                re.compile(r"\S"), timeout=5_000
            )
            return True
        except AssertionError:
            continue

    # Молча возвращать True нельзя: сабмит без сектора не уходит ВООБЩЕ, и
    # тест падал бы позже с невнятным «модалка не закрылась» вместо причины
    # (прогон 32338373909).
    raise AssertionError(
        "Не удалось выбрать сектор доставки: выпадающий список не открылся "
        "или значение не проставилось. Без сектора заказ не отправляется."
    )


# ===========================================================================
# Кейс 201: Закрыть «Оформление заказа» нажав на Х
# ===========================================================================
def test_close_checkout_via_x(checkout: Page):
    page = checkout

    page.locator(BTN_CHECKOUT_X).click()

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

    # Появилось поле под чекбоксом
    expect(page.locator(INPUT_MESSENGER)).to_be_visible(timeout=3_000)

    # А выключить — поле снова исчезло
    page.locator(CHK_DONT_CALL_LABEL).first.click()
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

    expect(
        page.locator(selector), f"Радио {label} (#{qase_id}) не выбралось"
    ).to_be_checked(timeout=5_000)

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

    expect(
        page.locator(selector), f"Радио «{label}» (#{qase_id}) не выбралось"
    ).to_be_checked(timeout=5_000)

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

    expect(
        page.locator(selector), f"Радио «{label}» (#{qase_id}) не выбралось"
    ).to_be_checked(timeout=5_000)
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
        expect(page.locator(RADIO_DELIVERY_ADDRESS)).to_be_checked(timeout=5_000)

    # «Кишинёв» — это radio типа доставки, а не пункт списка региона. До его
    # выбора v-select'ы региона/сектора задизейблены. Если у товара такого типа
    # нет — корректно пропускаем.
    if page.locator(f'{CHECKOUT_FORM} label[for="delivery-chisinau"]').count() == 0:
        pytest.skip("Тип доставки «Кишинёв» недоступен для этого товара")
    _click_radio_by_id(page, "delivery-chisinau")
    expect(page.locator(RADIO_DELIVERY_CHISINAU)).to_be_checked(timeout=5_000)

    # Регион проставился сам → первый v-select показывает «мун. Кишинёв»
    expect(page.locator(VSELECT_SELECTED).first).to_have_text(
        re.compile(r"Кишинёв")
    )

    # Активный пустой v-select (сектор) открывается со списком пунктов.
    # Сектор дорисовывается через ~5 с после выбора «Кишинёв» — мгновенная
    # проверка давала ложный skip в каждом прогоне (до 09.10.2026). Если и
    # после ожидания его нет — сектор/город предустановлен, проверять нечего.
    idx = _wait_sector_vselect(page, timeout=15_000)
    if idx < 0:
        pytest.skip("Сектор/населённый пункт предустановлен — выпадающего списка нет")
    # Индекс посчитан среди `.v-select` — и применяем его к ним же, как в
    # `_setup_chisinau_address`. Прежний `VSELECT_SEARCH.nth(idx)` брал индекс
    # из другого набора узлов и мог открыть соседний список (регион), и тест
    # зеленел, не открыв сектор вовсе.
    page.locator(VSELECT).nth(idx).locator(".vs__search").click()
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
    модалка остаётся открытой и подсвечивает обязательные поля.

    Паузы после клика нет: результат (подсветка полей) каждый тест ждёт сам
    через `expect`, а не 800 мс по часам."""
    _skip_if_out_of_stock(page)
    btn = page.locator(BTN_PLACE_ORDER).first
    btn.scroll_into_view_if_needed()
    btn.click()


def _money_to_bani(text: str):
    """«5 499 MDL» / «6 649.05 MDL» → сумма в бани (копейках).

    Считаем в бани, а не в леях: суммы бывают дробными, и «съедание» точки
    даёт мусор вроде 664905 вместо 6649.05.
    """
    m = re.search(r"(\d[\d\s ]*(?:[.,]\d{1,2})?)\s*MDL", text)
    if not m:
        return None
    raw = re.sub(r"[\s ]", "", m.group(1)).replace(",", ".")
    return round(float(raw) * 100)


def _checkout_summary(page: Page) -> dict:
    """Сводка формы оформления в бани: goods / delivery / discount / total.

    `delivery` = None, если строки «Доставка» в сводке нет (самовывоз).
    Если товары набрали порог бесплатной доставки, вместо суммы в строке
    стоит «—» (не «0 MDL») — это `delivery` = 0 и `delivery_free` = True.
    Прогресс-строка «Бесплатная доставка» — не сумма заказа, а порог
    («29 596 / 1 200 MDL»): из неё берём только `free_threshold`.
    """
    rows = page.evaluate(
        """() => {
            const box = document.querySelector('.cart__sidebar--checkout');
            if (!box) return null;
            return [...box.querySelectorAll('.list__item')]
                .map(r => ({
                    progress: r.className.includes('proggress'),
                    name: (r.querySelector('.list__name')?.innerText || '').trim(),
                    // в прогресс-строке ДВА .list__sum («29 596 /» и «1 200 MDL»),
                    // берём их общий контейнер, иначе порог теряется
                    sum: (r.querySelector('.list__item__info__prices, .list__sum')
                          ?.innerText || '').trim(),
                }));
        }"""
    )
    assert rows is not None, "Блок сводки .cart__sidebar--checkout не найден"

    out = {"goods": None, "delivery": None, "discount": 0,
           "delivery_free": False, "free_threshold": None}
    for row in rows:
        name = row["name"]
        if row["progress"]:
            # «29 596 / 1 200 MDL» — порог стоит после косой черты
            out["free_threshold"] = _money_to_bani(row["sum"].split("/")[-1])
        elif re.match(r"^\s*Стоимость товаров", name):
            out["goods"] = _money_to_bani(row["sum"])
        elif re.match(r"^\s*Доставка", name):
            if row["sum"] in ("—", "–", "-"):
                out["delivery"], out["delivery_free"] = 0, True
            else:
                out["delivery"] = _money_to_bani(row["sum"])
        elif re.match(r"^\s*Скидка", name):
            out["discount"] = _money_to_bani(row["sum"]) or 0

    out["total"] = _money_to_bani(page.locator(SUMMARY_TOTAL).first.inner_text())
    return out


def _settled_summary(page: Page) -> dict:
    """Сводка после пересчёта: строка «Доставка» есть и два чтения подряд
    (~200 мс) совпали.

    Пересчёт идёт на клиенте после смены типа доставки; раньше здесь стояла
    пауза 800 мс. Ждём именно покоя, а не «пока итог сойдётся»: ожидание
    правильного итога — это ассерт, вывернутый в ожидание, оно замаскировало
    бы кратковременно неверную сводку. Не дождались — ассерты теста покажут
    последние прочитанные цифры.
    """
    previous = [None]

    def settled(value: dict) -> bool:
        same = value == previous[0]
        previous[0] = value
        return same and value["delivery"] is not None

    return wait_until(
        page, lambda: _checkout_summary(page), settled, timeout_ms=5_000, poll_ms=200
    )


def _select_delivery_type(page: Page, radio_id: str) -> None:
    """Выбрать тип доставки и дождаться, что радио реально переключилось."""
    _click_radio_by_id(page, radio_id)
    expect(page.locator(f"{CHECKOUT_FORM} input#{radio_id}")).to_be_checked(timeout=5_000)


# ===========================================================================
# Кейс 376 (шаг 1): сабмит пустой формы подсвечивает обязательные поля
# ===========================================================================
def test_required_fields_errors_on_empty_submit(checkout: Page):
    page = checkout

    # До сабмита ошибок обязательных полей нет
    expect(page.locator(ERR_PHONE)).to_have_count(0)
    expect(page.locator(ERR_TERMS)).to_have_count(0)

    _click_place_order(page)

    # Обёртка телефона и блок согласия подсвечены ошибкой (стабильные сигналы)
    expect(page.locator(ERR_PHONE)).to_have_count(1, timeout=5_000)
    expect(page.locator(ERR_TERMS)).to_have_count(1)

    # Форма не закрылась (сабмит заблокирован валидацией). Проверяем ПОСЛЕ
    # подсветки: сразу за кликом форма видна в любом случае — сабмит ещё не
    # обработан, и проверка прошла бы вхолостую.
    expect(page.locator(CHECKOUT_FORM)).to_be_visible()

    # Под обязательными полями виден текст «Это обязательное поле»
    # (v-select Населенный пункт грузится асинхронно — даём expect авто-ретраить)
    req_msg = page.locator(VIS_VALIDATION).filter(has_text=REQUIRED_MSG)
    expect(req_msg.first).to_be_visible(timeout=10_000)


# ===========================================================================
# Кейс 376 (шаг 8): оплата «По перечислению» добавляет обязательные поля юрлица
# ===========================================================================
def test_transfer_payment_reveals_required_legal_fields(checkout: Page):
    page = checkout

    # Число видимых ошибок обязательных полей до выбора перечисления.
    # Считаем только после того, как валидация отработала (подсветка телефона
    # и текст «Это обязательное поле»): мгновенный count() сразу за кликом
    # даёт заниженное «до», и рост «после» засчитывался бы вхолостую.
    _click_place_order(page)
    expect(page.locator(ERR_PHONE)).to_have_count(1, timeout=5_000)
    expect(
        page.locator(VIS_VALIDATION).filter(has_text=REQUIRED_MSG).first
    ).to_be_visible(timeout=10_000)
    errors_before = page.locator(VIS_VALIDATION).count()

    # Выбираем «По перечислению»
    _click_radio_by_id(page, "recount")
    expect(page.locator(RADIO_PAY_TRANSFER)).to_be_checked(timeout=5_000)

    # Появились поля юрлица
    for label in ["Название фирмы", "Фискальный код", "Юридический адрес", "IBAN"]:
        expect(page.locator(CHECKOUT_FORM).get_by_text(label, exact=False).first).to_be_visible(
            timeout=5_000
        )

    # Повторный сабмит — обязательных ошибок стало больше (добавились поля юрлица)
    _click_place_order(page)
    errors_after = wait_until(
        page,
        lambda: page.locator(VIS_VALIDATION).count(),
        lambda value: value > errors_before,
        timeout_ms=5_000,
    )
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

    # Появилось поле мессенджера
    expect(page.locator(INPUT_MESSENGER)).to_be_visible(timeout=3_000)

    # Повторный сабмит: телефон больше НЕ обязательный — класс error снят.
    # Пауза здесь намеренная: проверяем, что ошибка НЕ вернётся после
    # сабмита. `to_have_count(0)` прошёл бы сразу, ещё до того как сабмит
    # отработал, — отдельного сигнала «валидация завершилась» у формы нет.
    _click_place_order(page)
    page.wait_for_timeout(800)
    expect(page.locator(ERR_PHONE)).to_have_count(0, timeout=5_000)


# ===========================================================================
# Доп. к 376: итог пересчитывается при смене типа/способа доставки
#
# Раньше тест требовал «стоимость доставки по Кишинёву > 0» и «Кишинёв ≠
# Молдова». Это привязка к настройкам цен: у магазина есть порог бесплатной
# доставки (строка «Бесплатная доставка 5 199 / 600 MDL» в сводке), и как
# только заказ его перебивает, доставка становится 0 MDL для ОБОИХ типов —
# тест падал на исправном продукте (e2e run 31595555992, товар за 5 499 MDL).
#
# Поэтому проверяем не величины, а инварианты, которые верны при любых ценах:
#   • при доставке по адресу строка «Доставка» в сводке есть, сумма ≥ 0;
#   • Итог == Стоимость товаров − Скидка + Доставка;
#   • самовывоз убирает строку доставки, и Итог == товары − скидка.
# ===========================================================================
def test_delivery_cost_updates_in_summary(checkout: Page):
    page = checkout

    # Доставка по адресу выбрана по умолчанию — подстрахуемся
    if not page.locator(RADIO_DELIVERY_ADDRESS).is_checked():
        _click_radio_by_id(page, "delivery")
        expect(page.locator(RADIO_DELIVERY_ADDRESS)).to_be_checked(timeout=5_000)

    for radio_id, human in (("delivery-chisinau", "Кишинёв"), ("delivery-region", "Молдова")):
        _select_delivery_type(page, radio_id)
        s = _settled_summary(page)

        assert s["delivery"] is not None, (
            f"При доставке по адресу ({human}) в сводке нет строки «Доставка»"
        )
        assert s["delivery"] >= 0, (
            f"Отрицательная стоимость доставки ({human}): {s['delivery']} бани"
        )
        # «—» вместо суммы = бесплатная доставка; честна она, только если
        # товары действительно набрали порог (для региона он выше, чем для
        # Кишинёва: 1 200 против 600 MDL на 21.09.2026)
        if s["delivery_free"]:
            assert s["free_threshold"] is not None, (
                f"Доставка «—» ({human}), но строки с порогом бесплатной доставки нет"
            )
            assert s["goods"] >= s["free_threshold"], (
                f"Доставка бесплатная ({human}), хотя товары {s['goods']} "
                f"не набрали порог {s['free_threshold']} (в бани)"
            )
        expected = s["goods"] - s["discount"] + s["delivery"]
        assert s["total"] == expected, (
            f"Итог не сходится ({human}): товары {s['goods']} − скидка "
            f"{s['discount']} + доставка {s['delivery']} = {expected}, "
            f"а в сводке {s['total']} (в бани)"
        )

    # Способ = Самовывоз → строка доставки исчезает из сводки, итог без неё
    _click_radio_by_id(page, "self-call")
    expect(
        page.locator(CHECKOUT_SUMMARY_ROWS).filter(has_text=re.compile(r"Доставка"))
    ).to_have_count(0, timeout=5_000)

    s = _checkout_summary(page)
    assert s["delivery"] is None
    expected = s["goods"] - s["discount"]
    assert s["total"] == expected, (
        f"При самовывозе итог не равен товары − скидка: {s['goods']} − "
        f"{s['discount']} = {expected}, а в сводке {s['total']} (в бани)"
    )


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

    # 2. Телефон — уникальные 8 цифр, чтобы пройти антиспам.
    #    ТОЛЬКО `press_sequentially`: поле обёрнуто в intl-tel-input, который
    #    собирает значение из событий клавиатуры. После `fill()` цифры видны в
    #    инпуте, но во внутреннюю модель не попадают — сабмит тихо не уходит,
    #    и форма при этом НИЧЕГО не подсвечивает (поле-то заполнено на вид).
    #    Ровно так тест и падал с «модалка не закрылась»: вручную тот же
    #    сценарий проходит и создаёт заказ (проверено через MCP 2026-08-20,
    #    заказы 225476 и 225477).
    unique_phone = "79" + str(int(time.time() * 1000))[-6:]
    phone = page.locator(INPUT_PHONE)
    phone.click()
    phone.press_sequentially(unique_phone, delay=50)
    page.wait_for_timeout(300)

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
        expect(page.locator(RADIO_PAY_CASH)).to_be_checked(timeout=5_000)

    # 9. Согласие с условиями (`check()` сам убеждается, что галочка стоит)
    page.locator(CHK_TERMS).check()

    # 10. Сабмит. Заодно слушаем сам запрос создания заказа: без этого
    #     «подтверждения нет» неразличимо в трёх разных случаях — форма не
    #     отправила запрос, запрос ушёл и упал, запрос прошёл, а попап не
    #     отрисовался. Эндпоинт подсмотрен в живом успешном заказе (MCP,
    #     2026-08-20): POST .../general/v3/order/.
    order_calls: list[str] = []
    page.on(
        "response",
        lambda r: order_calls.append(f"{r.status} {r.url}")
        if "/order/" in r.url and r.request.method == "POST"
        else None,
    )

    submit = page.locator(BTN_PLACE_ORDER).first
    submit.scroll_into_view_if_needed()
    expect(submit).to_be_enabled(timeout=5_000)
    submit.click()

    # Признак успеха — попап с НОМЕРОМ заказа. Проверено вживую через MCP
    # 2026-08-20: на Виде 1 он есть и держится («Ваш заказ успешно оформлен.
    # Номер вашего заказа: 225476»), так что мягкое «если попался — проверим»
    # больше не нужно. Номер важен: он доказывает, что заявка создана, а не
    # что просто очистилась локальная корзина.
    success = page.locator(SUCCESS_POPUP)
    try:
        expect(success).to_be_visible(timeout=45_000)
    except AssertionError:
        # Подтверждения нет. Самая частая причина — незаполненное обязательное
        # поле: форма молча не отправляется, подсвечивая поля классом `unvalid`
        # уже ПОСЛЕ попытки. Показываем их, иначе останется загадочное
        # «модалка не закрылась» (ровно так и выглядел фейл прогона
        # 32338373909, и причина по нему не читалась).
        blocking = [
            (page.locator(INVALID_FIELD).nth(i).inner_text() or "").replace("\n", " ").strip()
            for i in range(min(page.locator(INVALID_FIELD).count(), 5))
        ]
        raise AssertionError(
            "Заказ не оформился: подтверждения с номером нет. "
            + (f"Форма подсветила поля: {', '.join(blocking)}. "
               if blocking else "Незаполненных полей форма не показывает. ")
            + (f"Запросы создания заказа: {order_calls}"
               if order_calls else "POST на создание заказа вообще не ушёл.")
        ) from None

    assert re.search(r"\d{4,}", success.inner_text()), (
        f"В подтверждении нет номера заказа: {success.inner_text()!r}"
    )

    # И только потом — что корзина действительно опустела.
    expect(page.locator(CART_MODAL_SHOWN)).to_have_count(0, timeout=30_000)
    expect(page.locator(CART_PRODUCT)).to_have_count(0, timeout=15_000)

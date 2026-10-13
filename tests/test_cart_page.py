"""Тесты корзины «Вид 2 — отдельная страница» (stage.ecom.md, локаль /ru)

Вид корзины задаётся в админке (Настройки сайта → «Вид страницы Корзины») и
общий для всего сайта. Виды взаимоисключающие: при Виде 1 корзина открывается
поп-апом и страницы `/ru/cart` НЕ существует, при Виде 2 — наоборот, есть
страница и нет поп-апа. Поэтому эти тесты и тесты `test_cart_block.py` никогда
не проходят в одном прогоне: активные скипаются по `require_cart_view`.

Переключением занимается CI отдельным шагом (`tools/cart_view.py`), тесты вид
не меняют — это глобальная настройка, общая с ручной работой на стенде.

Разметка снята вживую 2026-08-18 при активном Виде 2:

- страница `/ru/cart`, корень `.page-cart`;
- товары: `.cart-products__items` → `.plank-card` (десктоп). ВНИМАНИЕ: рядом
  лежит `.plank-card-mobile` с почти теми же классами — он в DOM всегда, но на
  десктопе скрыт, поэтому берём именно `.plank-card` и не используем поиск по
  общему префиксу;
- в строке: `.plank-card__group__title`, `__price`, `__oldPrice`,
  кнопки `.plank-card__delete-btn` («Удалить»),
  `.plank-card__btns__decrease` / `__increase`;
- «Очистить корзину» — `.cart-products__header__clear-btn` (единственный
  селектор, совпадающий с Видом 1);
- пустое состояние — `.cart-products__items__empty`;
- форма заказа на той же странице: `.order-form`, итоги в
  `.order-form__content__footer` («Итого», «Доставка», «Скидка»,
  «Общая сумма»), кнопка «Разместить заказ» в
  `.order-form__content__footer__submit`, согласие — `.terms__checkbox`;
- доставка и оплата — не радио-кнопки, а табы `.ui-action-tab-btn`.

Заказы отсюда НЕ отправляем: сабмит создаёт реальную заявку на стенде. Тесты
проверяют состав, пересчёт и арифметику, но не жмут «Разместить заказ».
"""

import re
import time

import pytest
from playwright.sync_api import Locator, Page, expect
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from admin_orders import assert_order_matches
from conftest import CART_VIEW_JS, CART_VIEW_PAGE, wait_until

CART_URL = "/ru/cart"

# Страница корзины
PAGE_CART = ".page-cart"
ITEMS = ".cart-products__items"
ROW = ".plank-card"
ROW_TITLE = ".plank-card__group__title"
ROW_PRICE = ".plank-card__group__price"
BTN_DELETE = ".plank-card__delete-btn"
BTN_MINUS = ".plank-card__btns__decrease"
BTN_PLUS = ".plank-card__btns__increase"
QTY = ".plank-card__btns"
BTN_CLEAR = "button.cart-products__header__clear-btn"
EMPTY = ".cart-products__items__empty"

# Форма заказа
ORDER_FORM = ".order-form"
FOOTER = ".order-form__content__footer"
SUBMIT_AREA = ".order-form__content__footer__submit"
TERMS_CHECKBOX = ".terms__checkbox"
# Табы: активный помечается классом `selected` (не `active`).
DELIVERY_TABS = ".order-form__content__segment__content__tabs .ui-action-tab-btn"
# Табы оплаты и доставки лежат в одинаковых обёртках, отличаются только
# подписями — поэтому отбираем по тексту, а не по позиции сегмента.
ALL_TABS = ".order-form .ui-action-tab-btn"
RE_PAYMENT = re.compile(r"наличн|кредит|перевод|онлайн", re.I)
PROMOCODE = ".order-form__content__promocode"
PROMO_FEEDBACK = ".promo-code-feedback"
FREE_DELIVERY = ".order-form__free-delivery-info"

# Поля заказа
INPUT_NAME = 'input[placeholder="Введите имя и фамилию"]'
# По типу поля, а не по id: 01.09.2026 фронт переименовал `id="phone"`
# (в модалке чекаута стал `checkout-phone`), и оба happy-path теста встали
# на таймауте. Тип `tel` переживёт следующее переименование.
INPUT_PHONE = 'input[type="tel"]'
INPUT_EMAIL = 'input[placeholder="example@email.com"]'
INPUT_STREET = 'input[placeholder="например: Авиатор"]'
BTN_PLACE_ORDER = f"{SUBMIT_AREA} button"
# «Сектор» — обязательный выпадающий список, без него заказ молча не уходит.
SECTOR_SELECT = '.order-form .ui-select:has(label:text-matches("Сектор", "i"))'
DROPDOWN_OPTION = ".vs__dropdown-menu li"
# Незаполненное обязательное поле помечается классом `unvalid` (именно так,
# не `invalid`) — по нему видно, что именно блокирует оформление.
INVALID_FIELD = ".unvalid"
SUCCESS_POPUP = ".checkout__success_content"

# Каталог — откуда кладём товар
CATEGORY_URL = "/ru/acustica-portabila"
CARD = ".product__item"
CARD_PRICES = ".product__prices"
BTN_ADD_CART = "button.btn__add_cart"

HEADER_CART_BTN = "button.btn__action.btn__cart:visible"

_AMOUNT_RE = re.compile(r"(\d[\d\s ]*(?:[.,]\d{1,2})?)\s*MDL")


def _bani(text: str) -> int:
    """Сумма в банах. Дробные цены («14 449.15 MDL») иначе разъезжаются."""
    match = _AMOUNT_RE.search(text or "")
    assert match, f"В строке {text!r} не нашли суммы в MDL"
    return int(round(float(match.group(1).replace(" ", "").replace(" ", "").replace(",", ".")) * 100))


def _footer_amount(page: Page, label: str) -> int | None:
    """Сумма из строки итогов по её подписи («Итого», «Скидка», …)."""
    row = page.locator(f"{FOOTER} >> text={label}").first
    if not row.count():
        return None
    text = row.locator("xpath=..").inner_text()
    match = _AMOUNT_RE.search(text)
    return _bani(match.group(0)) if match else None


def _appears(locator: Locator, timeout: int = 10_000) -> bool:
    """Появился ли элемент за отведённое время.

    Мгновенный `count()` тут даёт ложное «поля нет»: блок доставки
    перерисовывается секунду-две после открытия формы, и обязательные
    «Сектор» с «Улицей» в этот момент ещё не в DOM. Тест считал их
    отсутствующими, пропускал заполнение и падал много позже на «нет
    подтверждения» — а форма после сабмита подсвечивала ровно эти два поля
    (прогон 32338373909, отчёт Вида 2). Та же грабля, что с фильтрами
    категории.
    """
    try:
        expect(locator.first).to_be_visible(timeout=timeout)
        return True
    except AssertionError:
        return False


@pytest.fixture(autouse=True)
def only_cart_page_view(require_cart_view):
    """Весь файл имеет смысл только при активном Виде 2."""
    require_cart_view(CART_VIEW_PAGE, "корзина отдельной страницей")


@pytest.fixture
def cart_with_product(page: Page, in_stock_product: str) -> Page:
    """Положить товар в корзину и открыть страницу корзины.

    Товар берём фикстурой `in_stock_product`: она подтверждает остаток по
    `__NUXT__`, а не по наличию цены и кнопки. Разница принципиальна — у
    товара «под заказ» цена и кнопка «В корзину» на месте, но заказ с ним не
    оформляется, и тест оформления падал бы с невнятным «нет подтверждения».
    """
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.context.clear_cookies()

    # Кладём товар с повтором. Кнопка «В корзину» видна раньше, чем Vue вешает
    # на неё обработчик, и первый клик после `domcontentloaded` регулярно
    # теряется. Молча: исключения нет, корзина просто остаётся пустой — и
    # падает не сам тест, а фикстура, с невнятным «.plank-card не найден»
    # (прогон 32462281373, Кейс «Вкладки способов оплаты»). Проверяем результат
    # по самой корзине, а не по факту клика.
    for _ in range(3):
        page.goto(in_stock_product, wait_until="domcontentloaded", timeout=60_000)
        expect(page.locator("h1")).to_be_visible(timeout=20_000)
        add = page.locator(BTN_ADD_CART).first
        expect(add).to_be_visible(timeout=20_000)
        add.click()
        # Признак добавления — сумма на кнопке корзины в шапке (у пустой там
        # «Корзина»). Не дождались — не страшно: ниже результат всё равно
        # проверяется по самой корзине, и цикл повторит добавление.
        try:
            expect(page.locator(HEADER_CART_BTN).first).to_contain_text(
                "MDL", timeout=5_000
            )
        except AssertionError:
            pass

        page.goto(CART_URL, wait_until="domcontentloaded", timeout=60_000)
        if _appears(page.locator(ROW), timeout=15_000):
            break

    expect(page.locator(f"{ROW}").first).to_be_visible(timeout=30_000)
    yield page

    # Прибираем за собой: корзина живёт в cookie и протекает в другие тесты.
    try:
        if page.locator(BTN_CLEAR).count():
            page.locator(BTN_CLEAR).first.click()
            expect(page.locator(ROW)).to_have_count(0, timeout=10_000)
    except Exception:
        pass


# ===========================================================================
# Состав корзины
# ===========================================================================
def test_cart_opens_as_page_not_popup(cart_with_product: Page):
    """Корзина — отдельная страница, поп-апа при этом виде нет."""
    page = cart_with_product
    expect(page).to_have_url(re.compile(r"/cart"), timeout=20_000)
    expect(page.locator(PAGE_CART)).to_be_visible(timeout=20_000)
    expect(page.locator(".modal__cart")).to_have_count(0)


def test_header_cart_leads_to_cart_page(cart_with_product: Page):
    """Кнопка корзины в шапке ведёт на страницу корзины."""
    page = cart_with_product
    page.goto(CATEGORY_URL, wait_until="domcontentloaded", timeout=60_000)

    # Единственный тест файла, который заходит на КЭШИРУЕМУЮ страницу: всё
    # остальное живёт на /cart, а его nginx не кэширует. Вид корзины приезжает
    # в SSR-разметке, поэтому страница, снятая в кэш до переключения, ведёт
    # себя по Виду 1 — кнопка открывает поп-ап `.modal__cart` вместо перехода
    # на /cart. Проверено вживую 2026-08-21: при активном Виде 2
    # `/ru/product/...` (X-Cache: MISS) отдавал `casadeltabaco`, а эта категория
    # (X-Cache: HIT, возраст 319 c) — `default`, и клик открывал поп-ап.
    # Обойти кэш из теста нечем: лишний query-параметр на категории даёт 404.
    # Гонять проверку по чужой конфигурации бессмысленно — честнее скипнуть с
    # внятной причиной, чем красить прогон в красный из-за кэша стенда.
    rendered_view = page.evaluate(CART_VIEW_JS)
    if rendered_view != CART_VIEW_PAGE:
        pytest.skip(
            f"страница категории отдана из кэша со старым видом корзины "
            f"({rendered_view!r} вместо {CART_VIEW_PAGE!r}) — кнопка на ней "
            f"работает по прошлой конфигурации, проверять нечего"
        )

    # Клик повторяем: первый после `domcontentloaded` регулярно теряется —
    # обработчик вешается только на гидрации, а её мы не ждём (ждать
    # `networkidle` на этом стенде бесполезно, сеть не затихает). Одиночный
    # клик давал «URL не сменился за 30 с» на исправном продукте
    # (прогон 32338373909, отчёт Вида 2).
    #
    # Каждой попытке даём короткий срок. С дефолтными 45 с на действие цикл был
    # бесполезен: кнопку временно накрывала шапка формы заказа
    # (`<div class="head">`), первый же клик висел все 45 с и валил тест, так и
    # не дойдя до второй попытки (прогон 32462281373). Последняя попытка идёт
    # через `force`: если перекрытие никуда не делось, пусть тест падает на
    # осмысленной проверке URL, а не на таймауте клика.
    for attempt in range(3):
        try:
            page.locator(HEADER_CART_BTN).first.click(
                timeout=10_000, force=(attempt == 2)
            )
        except PlaywrightTimeoutError:
            continue
        try:
            expect(page).to_have_url(re.compile(r"/cart"), timeout=10_000)
            break
        except AssertionError:
            continue

    expect(page).to_have_url(re.compile(r"/cart"), timeout=30_000)
    expect(page.locator(PAGE_CART)).to_be_visible(timeout=20_000)


def test_added_product_shown_with_title_and_price(cart_with_product: Page):
    """Положенный товар виден в корзине с названием и ценой."""
    page = cart_with_product
    row = page.locator(ROW).first

    title = (row.locator(ROW_TITLE).first.inner_text() or "").strip()
    assert title, "У товара в корзине пустое название"

    price = row.locator(ROW_PRICE).first.inner_text()
    assert _AMOUNT_RE.search(price), f"У товара «{title}» не видно цены: {price!r}"


# ===========================================================================
# Изменение количества
# ===========================================================================
def test_increase_quantity_raises_total(cart_with_product: Page):
    """Плюс увеличивает количество, и общая сумма растёт."""
    page = cart_with_product
    before = _footer_amount(page, "Общая сумма")
    assert before, "Не нашли «Общая сумма» в итогах"

    page.locator(BTN_PLUS).first.click()
    # Ждём пересчёта итога по факту, а не 2.5 с
    after = wait_until(
        page,
        lambda: _footer_amount(page, "Общая сумма"),
        lambda value: value != before,
    )
    assert after and after > before, (
        f"После нажатия «+» общая сумма не выросла: было {before / 100:.2f}, "
        f"стало {(after or 0) / 100:.2f} MDL"
    )


def test_decrease_quantity_lowers_total(cart_with_product: Page):
    """Минус после плюса возвращает сумму обратно."""
    page = cart_with_product
    base = _footer_amount(page, "Общая сумма")

    page.locator(BTN_PLUS).first.click()
    raised = wait_until(
        page,
        lambda: _footer_amount(page, "Общая сумма"),
        lambda value: value != base,
    )
    assert raised and raised > base, "Подготовка не удалась: «+» не увеличил сумму"

    page.locator(BTN_MINUS).first.click()
    lowered = wait_until(
        page,
        lambda: _footer_amount(page, "Общая сумма"),
        lambda value: value != raised,
    )

    assert lowered == base, (
        f"После «−» общая сумма не вернулась к исходной: было {base}, стало {lowered}"
    )


# ===========================================================================
# Удаление и очистка
# ===========================================================================
def test_delete_product_removes_row(cart_with_product: Page):
    """«Удалить» убирает товар из корзины."""
    page = cart_with_product
    before = page.locator(ROW).count()

    page.locator(BTN_DELETE).first.click()

    expect(page.locator(ROW)).to_have_count(before - 1, timeout=20_000)


def test_clear_cart_empties_page(cart_with_product: Page):
    """«Очистить корзину» убирает все товары и показывает пустое состояние."""
    page = cart_with_product

    page.locator(BTN_CLEAR).first.click()

    expect(page.locator(ROW)).to_have_count(0, timeout=20_000)
    expect(page.locator(EMPTY)).to_be_visible(timeout=20_000)


# ===========================================================================
# Форма заказа на странице корзины
# ===========================================================================
def test_order_form_on_same_page(cart_with_product: Page):
    """Оформление живёт на той же странице: форма, согласие и кнопка заказа."""
    page = cart_with_product

    expect(page.locator(ORDER_FORM)).to_be_visible(timeout=20_000)
    expect(page.locator(TERMS_CHECKBOX)).to_be_attached(timeout=20_000)
    expect(page.locator(SUBMIT_AREA)).to_contain_text(
        re.compile("разместить заказ", re.I), timeout=20_000
    )


def test_order_totals_are_consistent(cart_with_product: Page):
    """Общая сумма = Итого − Скидка + Доставка.

    Проверяем инвариант, а не конкретные величины: цены на стенде меняются,
    и ассерт на числа давал бы ложные падения (этим уже обжигались в чекауте
    Вида 1).
    """
    page = cart_with_product

    goods = _footer_amount(page, "Итого")
    total = _footer_amount(page, "Общая сумма")
    assert goods is not None and total is not None, (
        "В итогах не нашли строк «Итого» и «Общая сумма»"
    )

    discount = _footer_amount(page, "Скидка") or 0
    delivery = _footer_amount(page, "Доставка") or 0

    assert total == goods - discount + delivery, (
        f"Итоги не сходятся: {goods / 100:.2f} − {discount / 100:.2f} + "
        f"{delivery / 100:.2f} = {(goods - discount + delivery) / 100:.2f}, "
        f"а показано {total / 100:.2f} MDL"
    )


def test_payment_method_tabs_switch(cart_with_product: Page):
    """Способ оплаты переключается табами.

    Проверяем только переключение: реально оформляем заказ наличными, потому
    что онлайн-оплата потребовала бы настоящую карту.
    """
    page = cart_with_product
    tabs = page.locator(ALL_TABS).filter(has_text=RE_PAYMENT)
    # Форма дорисовывается после строк корзины: мгновенный count() давал
    # ложное «меньше двух способов» и молчаливый skip. Ждём второй таб.
    if not _appears(tabs.nth(1), timeout=15_000):
        pytest.skip("На форме меньше двух способов оплаты")

    other = tabs.nth(1)
    label = (other.inner_text() or "").strip()
    other.click()
    expect(other).to_have_class(re.compile(r"selected"), timeout=15_000)

    cash = tabs.filter(has_text=re.compile("наличны", re.I)).first
    if cash.count():
        cash.click()
        expect(cash).to_have_class(re.compile(r"selected"), timeout=15_000), (
            f"Не удалось вернуться к оплате наличными после выбора «{label}»"
        )


def test_invalid_promocode_shows_error(cart_with_product: Page):
    """Несуществующий промокод не применяется и показывает ошибку."""
    page = cart_with_product

    page.locator(f"{PROMOCODE} input").first.fill("QA-NEVERNYJ-KOD-12345")
    page.locator(f"{PROMOCODE} button").first.click()

    feedback = page.locator(PROMO_FEEDBACK)
    expect(feedback).to_be_visible(timeout=20_000)
    expect(feedback).to_contain_text(re.compile(r"купон|промокод|не существ", re.I))


def test_free_delivery_threshold_zeroes_delivery(cart_with_product: Page):
    """При достигнутом пороге бесплатной доставки её стоимость равна нулю.

    Порог показывается как «набрано / порог». Сравниваем эти два числа и
    смотрим на строку «Доставка» — так тест верен при любой сумме корзины и
    любом пороге, а не только при сегодняшних цифрах.
    """
    page = cart_with_product
    info = page.locator(FREE_DELIVERY)
    # Ждём, а не считаем мгновенно: блок рисуется вместе с формой, позже строк
    # корзины, и мгновенный count() уводил тест в ложный skip.
    if not _appears(info, timeout=15_000):
        pytest.skip("На форме нет блока бесплатной доставки")

    amounts = _AMOUNT_RE.findall(info.inner_text())
    raw = re.findall(r"(\d[\d\s ]*(?:[.,]\d{1,2})?)", info.inner_text())
    if len(raw) < 2:
        pytest.skip(f"Не разобрали блок бесплатной доставки: {info.inner_text()!r}")

    collected = _bani(raw[0] + " MDL")
    threshold = _bani(raw[1] + " MDL")
    delivery = _footer_amount(page, "Доставка")

    if collected >= threshold:
        assert delivery == 0, (
            f"Порог бесплатной доставки достигнут ({collected / 100:.2f} из "
            f"{threshold / 100:.2f} MDL), но доставка стоит {(delivery or 0) / 100:.2f} MDL"
        )
    else:
        assert delivery and delivery > 0, (
            f"Порог не достигнут ({collected / 100:.2f} из {threshold / 100:.2f} MDL), "
            "но доставка бесплатная"
        )


def test_delivery_type_tabs_switch(cart_with_product: Page):
    """Тип доставки выбирается табами, выбранный подсвечивается."""
    page = cart_with_product
    tabs = page.locator(DELIVERY_TABS)
    if not _appears(tabs.nth(1), timeout=15_000):
        pytest.skip("На форме меньше двух табов доставки — переключать нечего")

    second = tabs.nth(1)
    label = (second.inner_text() or "").strip()
    second.click()

    expect(second).to_have_class(re.compile(r"active|selected|checked"), timeout=15_000), (
        f"Таб «{label}» не отметился активным после клика"
    )


# ===========================================================================
# Оформление заказа. РЕАЛЬНЫЙ САБМИТ — создаёт заявку на стенде (это разрешено).
#
# Объявлен ПОСЛЕДНИМ намеренно: pytest идёт по порядку определения, а
# оформление расходует остаток товара. Если поставить его выше, остальные
# тесты могут остаться без стока. Ровно так же сделано для Вида 1
# (test_checkout_block.py::test_place_order_happy_path).
# ===========================================================================
def test_place_order_happy_path(cart_with_product: Page, admin_order):
    """Заказ наличными с доставкой оформляется, корзина после этого пуста,
    а в админке лежит ровно то, что покупатель ввёл и видел в итогах."""
    page = cart_with_product
    product_name = page.locator(ROW_TITLE).first.inner_text().strip()

    page.locator(INPUT_NAME).first.fill("QA Autotest")

    # Телефон в intl-tel-input: только посимвольный ввод. `fill` проскакивает
    # мимо маски, и поле остаётся пустым — уже проверено на предзаказе.
    phone = page.locator(INPUT_PHONE).first
    phone.click()
    unique_phone = "79" + str(int(time.time() * 1000))[-6:]
    phone.press_sequentially(unique_phone, delay=60)

    email = f"qa+{int(time.time())}@example.com"
    page.locator(INPUT_EMAIL).first.fill(email)

    # Сектор — ОБЯЗАТЕЛЕН. Без него кнопка остаётся активной, но клик молча
    # ничего не делает: запрос не уходит вообще, поле лишь подсвечивается
    # классом `unvalid`. Населённый пункт подставляется сам («мун. Кишинёв»).
    sector = page.locator(SECTOR_SELECT)
    if _appears(sector):
        sector.locator(".vs__search").first.click()
        options = page.locator(DROPDOWN_OPTION)
        expect(options.first).to_be_visible(timeout=15_000)
        options.first.click()
        # Проверяем, что значение ДЕЙСТВИТЕЛЬНО выбралось. Полагаться на класс
        # `unvalid` тут нельзя: он появляется только ПОСЛЕ неудачной попытки
        # отправки, то есть до первого клика по «Разместить заказ» его нет
        # даже у пустых полей. Из-за этого невыбранный сектор проходил
        # незамеченным, а тест падал позже и невнятно — «нет подтверждения».
        expect(sector.locator(".vs__selected")).to_have_count(1, timeout=15_000)

    street = page.locator(INPUT_STREET)
    street_text = "ул. Тестовая, д. 1, кв. 1"
    if _appears(street):
        street.first.fill(street_text)

    # Наличные и доставка по Кишинёву выбраны по умолчанию — подстраховываемся.
    cash = page.locator(ALL_TABS).filter(has_text=re.compile("наличны", re.I)).first
    if cash.count() and "selected" not in (cash.get_attribute("class") or ""):
        cash.click()
        expect(cash).to_have_class(re.compile(r"selected"), timeout=10_000)

    # `check()` сам убеждается, что галочка встала — пауза после него лишняя
    page.locator(TERMS_CHECKBOX).first.check(force=True)

    # Перед отправкой убеждаемся, что форма считает себя заполненной. Иначе
    # тест упал бы на «корзина не опустела», хотя настоящая причина — пустое
    # обязательное поле, и разбираться пришлось бы вслепую.
    invalid = page.locator(INVALID_FIELD)
    assert invalid.count() == 0, (
        "Перед отправкой остались незаполненные обязательные поля: "
        + ", ".join(
            (invalid.nth(i).locator("label").first.inner_text() or "").strip()
            for i in range(min(invalid.count(), 5))
        )
    )

    # Итоги, которые покупатель видит перед отправкой, — эталон для админки.
    # «Итого» здесь — товары ДО скидки, как «Стоимость товаров» в Виде 1.
    summary = {
        "goods": _footer_amount(page, "Итого"),
        "discount": _footer_amount(page, "Скидка") or 0,
        "delivery": _footer_amount(page, "Доставка") or 0,
        "total": _footer_amount(page, "Общая сумма"),
    }

    submit = page.locator(BTN_PLACE_ORDER).first
    submit.scroll_into_view_if_needed()
    expect(submit).to_be_enabled(timeout=10_000)
    submit.click()

    # Успех подтверждается попапом с НОМЕРОМ заказа — это признак того, что
    # заявка реально создана, а не просто очистилась локальная корзина.
    success = page.locator(SUCCESS_POPUP)
    try:
        expect(success).to_be_visible(timeout=45_000)
    except AssertionError:
        # Подтверждения нет. Самая частая причина — незаполненное обязательное
        # поле: форма молча не отправляется, а поля подсвечиваются `unvalid`
        # уже ПОСЛЕ попытки. Показываем их, иначе разбираться придётся вслепую.
        invalid = page.locator(INVALID_FIELD)
        blocking = [
            (invalid.nth(i).locator("label").first.inner_text() or "").strip()
            for i in range(min(invalid.count(), 5))
        ]
        raise AssertionError(
            "Заказ не оформился: подтверждения нет. "
            + (f"Форма подсветила поля: {', '.join(blocking)}"
               if blocking else "Незаполненных полей форма не показывает — "
                                "причина не в валидации.")
        ) from None
    expect(success).to_contain_text(re.compile(r"успешно оформлен", re.I))
    number = re.search(r"\d{4,}", success.inner_text())
    assert number, f"В подтверждении нет номера заказа: {success.inner_text()!r}"

    expect(page.locator(ROW)).to_have_count(0, timeout=20_000)

    # Заказ в админке (номер из попапа = ID). Доставка и регион — значения по
    # умолчанию формы Вида 2; так их записали все прошлые ночные заказы.
    assert_order_matches(admin_order(number.group()), {
        "name": "QA Autotest",
        "phone": unique_phone,
        "email": email,
        "pay_method": "Наличн",
        "delivery_type": "Доставка по адресу",
        "region": "Кишинёв",
        "address": street_text,
        "product": product_name,
        "summary": summary,
    })

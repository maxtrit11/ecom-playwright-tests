"""Тесты поп-апа Купить в кредит (Qase suite 15: Поп-ап Купить в кредит)"""

import re
import time

import pytest
from playwright.sync_api import Page, expect


# Товар берём из фикстуры `credit_product` (conftest): кредит доступен не для
# всего каталога, и зашитый раньше `jbl-partybox-on-the-go-2` его потерял
# (`credit.has == false` → кнопки `btn__credit` в разметке просто нет).

BTN_OPEN_CREDIT = "button.btn__credit"

MODAL_CREDIT = ".modal__credit.show"
BTN_CLOSE = f"{MODAL_CREDIT} .btn__close"
BTN_CONTINUE = f"{MODAL_CREDIT} button.btn__secondary"  # «Продолжить покупки»
BTN_SUBMIT = f"{MODAL_CREDIT} button.btn.credit"        # «Отправить заявку»
INPUT_NAME = f'{MODAL_CREDIT} input[placeholder="Введи имя и фамилию"]'
INPUT_TEL = f'{MODAL_CREDIT} input[type="tel"]'
COMPANIES = f"{MODAL_CREDIT} .list.company .credit__group"

SUCCESS_POPUP = ".modal__credit_success.show"


def _fill_phone(page: Page, number: str) -> None:
    """Ввести телефон в intl-tel-input.

    `fill()` подставляет значение одним событием, а маска intl-tel-input
    навешана на посимвольный ввод — поле остаётся невалидным, и submit
    ложно падает на валидации. Нужен только `press_sequentially`.
    """
    tel = page.locator(INPUT_TEL).first
    tel.click()
    tel.press_sequentially(number, delay=60)


@pytest.fixture
def open_credit_popup(page: Page, credit_product: str):
    """Открыть страницу товара и поп-ап Купить в кредит."""
    # Desktop viewport — на мобильной разметке отдельные обработчики submit
    page.set_viewport_size({"width": 1920, "height": 1080})
    page.goto(credit_product, wait_until="domcontentloaded", timeout=60_000)
    expect(page.locator("h1")).to_be_visible(timeout=15_000)

    credit_btn = page.locator(BTN_OPEN_CREDIT).first
    expect(credit_btn).to_be_visible(timeout=10_000)

    # Первый клик после гидрации регулярно теряется — кликаем с повтором,
    # пока модалка не откроется (см. заметку про гидрацию в conftest).
    modal = page.locator(MODAL_CREDIT)
    for _ in range(3):
        credit_btn.click()
        try:
            expect(modal).to_be_visible(timeout=5_000)
            break
        except AssertionError:
            continue
    else:
        expect(modal).to_be_visible(timeout=5_000)

    return page


# ===========================================================================
# Кейс 86: Закрыть поп-ап по кнопке X
# ===========================================================================
def test_close_credit_popup_by_x(open_credit_popup: Page):
    """Клик на X — попап закрывается, страница товара видна."""
    page = open_credit_popup

    page.locator(BTN_CLOSE).first.click()

    expect(page.locator(MODAL_CREDIT)).not_to_be_visible(timeout=5_000)
    expect(page.locator("h1")).to_be_visible()


# ===========================================================================
# Кейс 87: Закрыть поп-ап по клику вне (overlay)
# ===========================================================================
def test_close_credit_popup_by_overlay_click(open_credit_popup: Page):
    """Клик в пустую область (overlay-зону модалки) — попап закрывается."""
    page = open_credit_popup

    # Overlay — это сам .modal__credit.show (тёмный фон), клик в его углу
    # вне белой карточки .credit__content закрывает попап
    page.evaluate(
        """() => {
            const modal = document.querySelector('.modal__credit.show');
            const rect = modal.getBoundingClientRect();
            modal.dispatchEvent(new MouseEvent('click', {
                bubbles: true,
                clientX: rect.left + 10,
                clientY: rect.top + 10,
                view: window
            }));
        }"""
    )
    page.wait_for_timeout(800)

    expect(page.locator(MODAL_CREDIT)).not_to_be_visible(timeout=5_000)


# ===========================================================================
# Кейс 88: Закрыть поп-ап по кнопке «Продолжить покупки»
# ===========================================================================
def test_close_credit_popup_by_continue_button(open_credit_popup: Page):
    """Клик на «Продолжить покупки» — попап закрывается."""
    page = open_credit_popup

    btn = page.locator(BTN_CONTINUE).first
    expect(btn).to_contain_text(re.compile(r"Продолжить покупки", re.IGNORECASE))
    btn.click()

    expect(page.locator(MODAL_CREDIT)).not_to_be_visible(timeout=5_000)


# ===========================================================================
# Кейс 90: Выбрать компанию кредитования — стиль карточки меняется
# ===========================================================================
def test_select_credit_company_highlights_card(open_credit_popup: Page):
    """Клик на компанию кредитования — карточка получает выделение
    (border-color меняется на #436BEF либо bg меняется)."""
    page = open_credit_popup

    companies = page.locator(COMPANIES)
    assert companies.count() >= 2, "Ожидалось ≥2 компаний кредитования"

    # Берём вторую компанию (Easy Credit), первая может быть выбрана по умолчанию.
    # Голубой стиль выделения применяется к вложенному label.radio-credit,
    # а не к самой .credit__group
    second = companies.nth(1)
    second_label = second.locator("label.radio-credit")
    bg_before = second_label.evaluate("el => getComputedStyle(el).backgroundColor")

    second.click()
    page.wait_for_timeout(800)

    bg_after = second_label.evaluate("el => getComputedStyle(el).backgroundColor")

    # Ожидаем bg #F2F6FF = rgb(242, 246, 255) или просто изменение фона
    is_blue_bg = "rgb(242, 246, 255)" in bg_after
    style_changed = bg_before != bg_after

    assert is_blue_bg or style_changed, (
        f"Стиль карточки не изменился после выбора: bg {bg_before} → {bg_after}"
    )

    # Под карточкой раскрылся блок «Выбери тип кредитования» с вариантами сроков
    expect(page.get_by_text(re.compile(r"Выбери тип кредитования", re.IGNORECASE)).first).to_be_visible(
        timeout=5_000
    )


# ===========================================================================
# Кейс 94: Ошибка под полем «Полное имя» при пустом значении
# ===========================================================================
def test_empty_name_shows_error_on_submit(open_credit_popup: Page):
    """Заполнен только телефон → submit → у поля Имя красная рамка / ошибка."""
    page = open_credit_popup

    _fill_phone(page, "79111111")

    name_input = page.locator(INPUT_NAME).first
    border_before = name_input.evaluate("el => getComputedStyle(el).borderColor")

    page.locator(BTN_SUBMIT).first.click()
    page.wait_for_timeout(800)

    border_after = name_input.evaluate("el => getComputedStyle(el).borderColor")

    # Ожидаем красную рамку #E53935 = rgb(229, 57, 53) либо вообще изменение цвета
    is_red = "rgb(229, 57, 53)" in border_after
    changed = border_before != border_after

    # Альтернатива — наличие .validation / .error-сообщения рядом с полем
    has_validation = page.locator(f"{MODAL_CREDIT} .validation:visible").count() > 0 or \
                     page.locator(f'{MODAL_CREDIT} [class*="error"]:visible').count() > 0

    assert is_red or changed or has_validation, (
        f"Поле Имя не подсветилось ошибкой: border {border_before} → {border_after}, "
        f"validation={has_validation}"
    )

    # Поп-ап остаётся открытым
    expect(page.locator(MODAL_CREDIT)).to_be_visible()


# ===========================================================================
# Кейс 95: Ошибка под полем «Телефон» при пустом значении
# ===========================================================================
def test_empty_phone_shows_error_on_submit(open_credit_popup: Page):
    """Заполнено только имя → submit → у поля Телефон красная рамка / ошибка."""
    page = open_credit_popup

    page.locator(INPUT_NAME).first.fill("Тест Тестов")

    tel_input = page.locator(INPUT_TEL).first
    border_before = tel_input.evaluate("el => getComputedStyle(el).borderColor")

    page.locator(BTN_SUBMIT).first.click()
    page.wait_for_timeout(800)

    border_after = tel_input.evaluate("el => getComputedStyle(el).borderColor")
    is_red = "rgb(229, 57, 53)" in border_after
    changed = border_before != border_after
    has_validation = page.locator(f"{MODAL_CREDIT} .validation:visible").count() > 0 or \
                     page.locator(f'{MODAL_CREDIT} [class*="error"]:visible').count() > 0

    assert is_red or changed or has_validation, (
        f"Поле Телефон не подсветилось ошибкой: border {border_before} → {border_after}, "
        f"validation={has_validation}"
    )

    expect(page.locator(MODAL_CREDIT)).to_be_visible()


# ===========================================================================
# Кейс 96: Положительный сценарий отправки заявки
# ===========================================================================
def test_successful_credit_application(open_credit_popup: Page):
    """Заполнить имя + телефон → submit → появляется success-попап
    «Заявка на кредит отправлена успешно»."""
    page = open_credit_popup

    # Уникальный 8-значный телефон чтобы обойти антиспам на стейдже
    unique_phone = "79" + str(int(time.time() * 1000))[-6:]

    page.locator(INPUT_NAME).first.fill("Тест Тестов")
    page.wait_for_timeout(500)
    _fill_phone(page, unique_phone)
    page.wait_for_timeout(500)

    # Ждём что submit-кнопка кликабельна (форма прошла клиентскую валидацию)
    submit_btn = page.locator(BTN_SUBMIT).first
    expect(submit_btn).to_be_enabled()
    submit_btn.click()

    # Success-попап содержит текст «Заявка на кредит отправлена успешно»
    success_text = page.get_by_text(
        re.compile(r"Заявка на кредит отправлена успешно", re.IGNORECASE)
    )
    expect(success_text.first).to_be_visible(timeout=30_000)

    # Кнопка «Главная страница» внутри success-попапа
    expect(page.get_by_text(re.compile(r"Главная страница", re.IGNORECASE)).first).to_be_visible()

"""Поп-ап регистрации — мобильная версия
(зеркало tests/account/test_registration_popup.py).

Что на телефоне иначе (проверено 01.10.2026 в MCP-браузере 412×839):

- путь: «Войти» нижнего бара → «Нет аккаунта? Зарегистрироваться» (кнопка
  шапки на телефоне 0×0);
- поп-ап во весь экран, но форма ВЫШЕ экрана: у физлица 1003 px при 839, у
  юрлица ещё длиннее. Страница под поп-апом заблокирована (`body.popup-open`,
  overflow hidden), а прокручивается внутренний контейнер
  `.modal__authentification__ecom__container` (overflow-y: scroll). Кнопка
  «Зарегистрироваться» в исходном положении за нижним краем экрана.

Импортированы кейсы 2–7, 134, 141, 143 — их хелпер `open_registration_popup`
подменён autouse-фикстурой на мобильный. Кейс 1 переписан: десктопный кликает
по кнопке шапки напрямую. Кейсы 7 и 143, как и на десктопе, создают на stage
настоящие аккаунты (`testqa_*@mailinator.com`).

Своё: жестом прокрутки (колесо над формой — в эмуляции телефона оно крутит
тот же контейнер) форма юрлица докручивается до «Зарегистрироваться», и
кнопка оказывается в экране и тапается.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from conftest import AUTH_MODAL, goto_resilient
from account.test_registration_popup import (  # noqa: F401 — тесты собирает pytest
    test_empty_fields_show_validation_errors,
    test_toggle_password_visibility,
    test_password_mismatch_shows_error,
    test_duplicate_email_shows_error,
    test_switch_to_legal_entity_shows_extra_fields,
    test_successful_registration,
    test_go_to_authorization_from_registration,
    test_duplicate_phone_shows_error,
    test_double_click_creates_single_account,
)
from mobile.mobile_auth import bar_auth_item, open_auth_modal_mobile

SCROLLER = ".modal__authentification__ecom__container"
TABS = ".modal__authentification__ecom-content-form-tabs button"


def open_registration_popup_mobile(page: Page):
    """«Войти» в баре → «Зарегистрироваться» → форма регистрации."""
    modal = open_auth_modal_mobile(page)
    modal.get_by_role("button", name=re.compile("Зарегистрироваться")).tap()
    expect(page.get_by_role("heading", name="Регистрация")).to_be_visible(timeout=10_000)
    # На время анимации перехода в DOM лежат обе формы — ждём, пока останется одна.
    expect(page.locator(AUTH_MODAL)).to_have_count(1, timeout=15_000)
    return page.locator(AUTH_MODAL).first


@pytest.fixture(autouse=True)
def navigate_home(page: Page):
    """Главная и пункт «Войти» в нижнем баре — без networkidle."""
    goto_resilient(page, "/ru")
    expect(bar_auth_item(page)).to_be_visible(timeout=20_000)


@pytest.fixture(autouse=True)
def _mobile_helpers(monkeypatch):
    """Импортированные тесты берут `open_registration_popup` из глобалов
    ДЕСКТОПНОГО модуля — подменяем там, через `__globals__`."""
    monkeypatch.setitem(
        test_empty_fields_show_validation_errors.__globals__,
        "open_registration_popup",
        open_registration_popup_mobile,
    )


# ===========================================================================
# Кейс 1 (моб.): Переход на поп-ап Регистрации
# ===========================================================================
def test_open_registration_popup_with_all_elements(page: Page):
    """«Войти» в баре → «Зарегистрироваться»: по умолчанию «Физическое лицо»,
    видны имя, фамилия, e-mail, телефон и два поля пароля."""
    form = open_registration_popup_mobile(page)

    expect(form.locator(f"{TABS}.active")).to_contain_text("Физическое лицо")

    expect(form.locator('input[placeholder="Ваше имя"]')).to_be_visible()
    expect(form.locator('input[placeholder="Ваше фамилия"]')).to_be_visible()
    expect(form.locator('input[placeholder="Введи e-mail адрес"]').first).to_be_visible()
    expect(form.locator('input[type="tel"].iti__tel-input')).to_be_visible()

    password_fields = form.locator('input[type="password"]')
    expect(password_fields).to_have_count(2)
    for i in range(2):
        expect(password_fields.nth(i)).to_be_visible()


# ===========================================================================
# Моб. Длинная форма прокручивается до кнопки «Зарегистрироваться»
# ===========================================================================
def test_long_form_scrolls_to_submit_button(page: Page):
    """Форма юрлица выше экрана: кнопка сначала за нижним краем; прокрутка
    жестом над формой двигает внутренний контейнер (не страницу — она
    заблокирована), и кнопка выезжает в экран, где сверху по точке касания
    лежит она сама."""
    form = open_registration_popup_mobile(page)
    form.locator(TABS).filter(has_text="Юридическое лицо").tap()
    expect(form.locator(f"{TABS}.active")).to_contain_text("Юридическое лицо")

    vh = page.viewport_size["height"]
    submit = form.locator('button[type="submit"]').first
    scroller = page.locator(SCROLLER).first

    start = submit.bounding_box()
    assert start["y"] + start["height"] > vh, (
        f"Ожидали кнопку за нижним краем длинной формы юрлица, а она в экране: {start}"
    )

    # Жест над серединой формы — до тех пор, пока кнопка не войдёт в экран.
    page.mouse.move(page.viewport_size["width"] / 2, vh / 2)
    for _ in range(20):
        b = submit.bounding_box()
        if b["y"] >= 0 and b["y"] + b["height"] <= vh:
            break
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(150)

    assert scroller.evaluate("e => e.scrollTop") > 0, (
        "Прокручивалась не форма поп-апа: scrollTop контейнера остался 0"
    )
    b = submit.bounding_box()
    assert b["y"] >= 0 and b["y"] + b["height"] <= vh, (
        f"Кнопка «Зарегистрироваться» не докручивается в экран высотой {vh}: {b}"
    )
    on_top = submit.evaluate(
        """(el) => { const r = el.getBoundingClientRect();
            const t = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
            return (t && (t === el || el.contains(t))) ? null
                : (t ? (t.className || t.tagName).toString() : 'пусто'); }"""
    )
    assert on_top is None, f"Кнопка «Зарегистрироваться» перекрыта: {on_top}"

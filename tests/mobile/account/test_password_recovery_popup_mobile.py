"""Поп-ап восстановления пароля — мобильная версия
(зеркало tests/account/test_password_recovery_popup.py).

Что на телефоне иначе (проверено 01.10.2026 в MCP-браузере 412×839):

- путь тот же — поп-ап входа → «Забыли пароль? Восстановить», но поп-ап
  входа открывается пунктом «Войти» нижнего бара (кнопка шапки 0×0);
- восстановление, как и вход, во ВЕСЬ экран (412×839): h2 «Восстановление
  пароля», пояснение, поле e-mail, «Отправить», крестик справа сверху.

Импортированы кейсы 2, 3, 4 — их хелпер `open_recovery_popup` подменён
autouse-фикстурой на мобильный. Кейс 1 переписан: десктопный кликает по
кнопке шапки напрямую, без хелпера.

НЕ перенесён кейс 132 «закрыть кликом вне поп-апа»: поп-ап на весь экран,
кликнуть мимо некуда.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from conftest import AUTH_MODAL, EMAIL_INPUT, goto_resilient
from account.test_password_recovery_popup import (  # noqa: F401 — тесты собирает pytest
    test_empty_email_shows_validation_error,
    test_close_recovery_popup_by_x_button,
    test_successful_password_recovery,
)
from mobile.mobile_auth import bar_auth_item, open_auth_modal_mobile

RECOVERY_HEADING = "Восстановление"


def open_recovery_popup_mobile(page: Page):
    """«Войти» в баре → «Восстановить» → поп-ап восстановления. Вернуть его."""
    modal = open_auth_modal_mobile(page)
    modal.get_by_role("button", name=re.compile("Восстановить")).tap()
    expect(page.get_by_role("heading", name=RECOVERY_HEADING)).to_be_visible(timeout=10_000)
    # Переход вход → восстановление анимированный, какое-то время в DOM лежат
    # обе модалки — дожидаемся, пока останется одна.
    expect(page.locator(AUTH_MODAL)).to_have_count(1, timeout=15_000)
    return page.locator(AUTH_MODAL).first


@pytest.fixture(autouse=True)
def navigate_home(page: Page):
    """Главная и пункт «Войти» в нижнем баре — без networkidle."""
    goto_resilient(page, "/ru")
    expect(bar_auth_item(page)).to_be_visible(timeout=20_000)


@pytest.fixture(autouse=True)
def _mobile_helpers(monkeypatch):
    """Импортированные тесты берут `open_recovery_popup` из глобалов
    ДЕСКТОПНОГО модуля — подменяем там, через `__globals__`."""
    monkeypatch.setitem(
        test_empty_email_shows_validation_error.__globals__,
        "open_recovery_popup",
        open_recovery_popup_mobile,
    )


# ===========================================================================
# Кейс 1 (моб.): Открыть поп-ап Восстановление пароля
# ===========================================================================
def test_open_recovery_popup(page: Page):
    """Тап «Войти» в баре, затем «Восстановить» — открывается форма
    восстановления: заголовок, поле e-mail и «Отправить», поля пароля нет."""
    modal = open_recovery_popup_mobile(page)

    expect(modal.locator("h2")).to_contain_text("Восстановление пароля")
    expect(modal.locator(EMAIL_INPUT)).to_be_visible()
    expect(modal.get_by_role("button", name="Отправить")).to_be_visible()
    expect(modal.locator('input[type="password"]')).to_have_count(0)


# ===========================================================================
# Моб. Поп-ап на весь экран, поле и кнопки в экране и тапаются
# ===========================================================================
def test_recovery_popup_fits_screen_and_controls_tappable(page: Page):
    """Поп-ап закрывает экран целиком; e-mail, «Отправить» и крестик лежат
    внутри экрана, и в центре каждого сверху — он сам."""
    modal = open_recovery_popup_mobile(page)
    vw, vh = page.viewport_size["width"], page.viewport_size["height"]

    box = modal.bounding_box()
    assert box["width"] >= vw - 1 and box["height"] >= vh - 1, (
        f"Поп-ап восстановления не на весь экран {vw}×{vh}: {box}"
    )

    controls = {
        "e-mail": modal.locator(EMAIL_INPUT).first,
        "Отправить": modal.get_by_role("button", name="Отправить"),
        "крестик": modal.locator(".btn__close").first,
    }
    problems = []
    for label, el in controls.items():
        expect(el).to_be_visible(timeout=10_000)
        b = el.bounding_box()
        if b["x"] < 0 or b["y"] < 0 or b["x"] + b["width"] > vw + 1 or b["y"] + b["height"] > vh + 1:
            problems.append(f"«{label}» за краем экрана: {b}")
            continue
        on_top = el.evaluate(
            """(el) => { const r = el.getBoundingClientRect();
                const t = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                return (t && (t === el || el.contains(t))) ? null
                    : (t ? (t.className || t.tagName).toString() : 'пусто'); }"""
        )
        if on_top:
            problems.append(f"«{label}» перекрыт: {on_top}")

    assert not problems, "Элементы поп-апа восстановления не тапаются: " + "; ".join(problems)

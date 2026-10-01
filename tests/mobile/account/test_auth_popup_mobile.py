"""Поп-ап авторизации — мобильная версия (зеркало tests/account/test_auth_popup.py).

Что на телефоне иначе (проверено 01.10.2026 в эмуляции Pixel 7):

- открывается пунктом «Войти» нижнего бара `.mobile__bar` (кнопка шапки
  `.btn__action.btn__auth` в DOM, но 0×0 — десктопный клик с force бьёт в
  пустоту);
- поп-ап `.modal__authentification__ecom-content` во ВЕСЬ экран (412×839),
  перекрывает и нижний бар; состав формы тот же: e-mail, пароль с «глазом»,
  «Забыли пароль? Восстановить», «Войдите в аккаунт», соцсети,
  «Нет аккаунта? Зарегистрироваться», крестик справа сверху.

Импортированы кейсы 1, 2, 3, 4, 124, 125, 127. Десктопный хелпер
`open_auth_popup` подменён autouse-фикстурой на тап по бару, а фикстура
`navigate_home` своя — без `networkidle` (на мобильной главной он нестабилен).

НЕ перенесён кейс 123 «закрыть кликом вне поп-апа»: поп-ап на весь экран,
кликнуть мимо некуда.

Своё: раскладка формы на узком экране, успешный вход через бар и выход
через меню «Кабинет» бара — на десктопе вход и выход проверяют только
косвенно, фикстуры кабинета.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from conftest import AUTH_MODAL, EMAIL_INPUT, goto_resilient, load_users
from account.test_auth_popup import (  # noqa: F401 — тесты собирает pytest
    test_open_auth_popup_with_all_elements,
    test_close_auth_popup_by_x_button,
    test_invalid_credentials_show_error,
    test_empty_fields_show_validation_errors,
    test_password_is_masked,
    test_toggle_password_visibility,
    test_go_to_password_recovery,
)
from mobile.mobile_auth import (
    bar_auth_item,
    expect_logged_in,
    login_via_bar,
    open_auth_modal_mobile,
    open_cabinet_menu,
)

USERS, _USERS_SKIP = load_users()


@pytest.fixture(autouse=True)
def navigate_home(page: Page):
    """Главная и пункт «Войти» в нижнем баре — без networkidle."""
    goto_resilient(page, "/ru")
    expect(bar_auth_item(page)).to_be_visible(timeout=20_000)


@pytest.fixture(autouse=True)
def _mobile_helpers(monkeypatch):
    """Импортированные тесты зовут `open_auth_popup` из глобалов ДЕСКТОПНОГО
    модуля — подменяем там, через `__globals__` самой тест-функции."""
    monkeypatch.setitem(
        test_close_auth_popup_by_x_button.__globals__,
        "open_auth_popup",
        open_auth_modal_mobile,
    )


# ===========================================================================
# Моб. Поп-ап на весь экран, все элементы формы в экране и тапаются
# ===========================================================================
def test_auth_popup_fits_screen_and_controls_tappable(page: Page):
    """Поп-ап закрывает экран целиком (вместе с нижним баром); поля, кнопки и
    ссылки лежат внутри экрана, и в центре каждого сверху — он сам."""
    modal = open_auth_modal_mobile(page)
    vw, vh = page.viewport_size["width"], page.viewport_size["height"]

    box = modal.bounding_box()
    assert box["width"] >= vw - 1 and box["height"] >= vh - 1, (
        f"Поп-ап авторизации не на весь экран {vw}×{vh}: {box}"
    )

    controls = {
        "e-mail": page.locator(EMAIL_INPUT).first,
        "пароль": modal.locator('input[type="password"]').first,
        "глаз": modal.locator("button.show__password").first,
        "Восстановить": modal.get_by_role("button", name=re.compile("Восстановить")).first,
        "Войдите в аккаунт": modal.locator('button[type="submit"]').first,
        "Зарегистрироваться": modal.get_by_text("Зарегистрироваться").first,
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

    assert not problems, "Элементы поп-апа авторизации не тапаются: " + "; ".join(problems)


# ===========================================================================
# Моб. Успешный вход через нижний бар
# ===========================================================================
@pytest.mark.requires_auth
@pytest.mark.skipif(_USERS_SKIP is not None, reason=_USERS_SKIP or "")
def test_login_via_bottom_bar(page: Page):
    """Верные данные → поп-ап закрывается, «Войти» в баре сменяется на
    «Кабинет» и остаётся им после перезагрузки (сессия, а не только UI)."""
    user = USERS["loginUser"]
    modal = open_auth_modal_mobile(page)

    page.locator(EMAIL_INPUT).first.fill(user["email"])
    modal.locator('input[type="password"]').first.fill(user["password"])
    modal.locator('button[type="submit"]').first.tap()

    expect(page.locator(AUTH_MODAL)).to_have_count(0, timeout=20_000)
    expect_logged_in(page, timeout=20_000)

    page.reload(wait_until="domcontentloaded")
    expect_logged_in(page, timeout=20_000)


# ===========================================================================
# Моб. Выход через меню «Кабинет» нижнего бара
# ===========================================================================
@pytest.mark.requires_auth
@pytest.mark.skipif(_USERS_SKIP is not None, reason=_USERS_SKIP or "")
def test_logout_via_bottom_bar_menu(page: Page):
    """«Кабинет» в баре раскрывает над ним меню с «Выйти»; выход возвращает
    «Войти» и закрывает кабинет: /ru/account после перезагрузки уже не
    открывается (гард уводит на `?login=true`)."""
    user = USERS["loginUser"]
    assert login_via_bar(page, user["email"], user["password"]), "Не удалось войти"

    # Тап с повтором: первый после загрузки теряется (гонка с гидрацией).
    menu = open_cabinet_menu(page)
    expect(menu).to_contain_text("Личные данные")
    expect(menu).to_contain_text("История заказов")

    menu.get_by_role("button", name="Выйти", exact=True).tap()
    expect(bar_auth_item(page)).to_have_text(re.compile(r"Войти", re.I), timeout=15_000)

    goto_resilient(page, "/ru/account")
    expect(page).to_have_url(re.compile(r"login=true"), timeout=15_000)

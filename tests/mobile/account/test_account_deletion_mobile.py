"""Удаление аккаунта — мобильная версия (зеркало tests/account/test_account_deletion.py).

Как и на десктопе, кнопку «Да, хочу удалить» НЕ нажимаем никогда — stage-аккаунт
общий (кейс 155 не автоматизирован, причины в десктопном файле).

Что на телефоне иначе (проверено 01.10.2026 в эмуляции Pixel 7):

- вход — через «Войти» нижнего бара, признак сессии — «Кабинет» там же
  (хелпер mobile/mobile_auth.py); десктопная кнопка шапки 0×0;
- страница «Личные данные» та же, кнопка «Удалить аккаунт» — ниже по
  странице, под ней «Выйти со всех устройств»;
- поп-ап подтверждения во ВЕСЬ экран (412×839): кнопки «Да, хочу удалить» /
  «Отменить» в ряд, крестик справа сверху.

Импортированы 150, 154 и «закрытие крестиком». Хелперы десктопного модуля
подменены autouse-фикстурой на мобильные: открытие подтверждения — тапом,
«аккаунт жив» — по нижнему бару, а не по скрытой кнопке шапки (её текст
меняется и в скрытом виде, проверка по ней ничего не видела бы глазами
пользователя).

НЕ перенесён «закрытие кликом вне поп-апа»: поп-ап занимает весь экран,
затемнённой области вокруг нет.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from conftest import load_users, open_account_page
from account.test_account_deletion import (  # noqa: F401 — тесты собирает pytest
    test_delete_account_confirmation_opens,
    test_delete_account_cancel,
    test_delete_account_close_by_x,
)
from account.test_account_deletion import (
    BTN_CANCEL,
    BTN_CONFIRM,
    BTN_DELETE_ACCOUNT,
    MODAL,
)
from mobile.mobile_auth import expect_logged_in, login_via_bar

USERS, _USERS_SKIP = load_users()

pytestmark = [
    pytest.mark.requires_auth,
    pytest.mark.skipif(_USERS_SKIP is not None, reason=_USERS_SKIP or ""),
]

EMAIL = USERS["loginUser"]["email"]
PASSWORD = USERS["loginUser"]["password"]

ACTIONS = ".modal__authentification__ecom-content-form-actions"


@pytest.fixture
def account(page: Page):
    """Вход через нижний бар + страница «Личные данные»."""
    assert login_via_bar(page, EMAIL, PASSWORD), f"Не удалось войти под {EMAIL}"

    open_account_page(page)
    expect(page).to_have_url(re.compile(r"account"), timeout=15_000)
    expect(page.locator(BTN_DELETE_ACCOUNT).first).to_be_visible(timeout=15_000)
    return page


def open_delete_confirmation(page: Page):
    """Тапнуть «Удалить аккаунт» и дождаться поп-апа подтверждения."""
    page.locator(BTN_DELETE_ACCOUNT).first.tap()
    modal = page.locator(MODAL).first
    modal.wait_for(state="visible", timeout=15_000)
    expect(modal.locator("h2")).to_contain_text(
        re.compile("удаление аккаунта", re.I)
    )
    return modal


def assert_account_alive(page: Page) -> None:
    """После перезагрузки — кабинет открыт, в нижнем баре «Кабинет»."""
    page.reload(wait_until="domcontentloaded")
    expect(page).to_have_url(re.compile(r"account"), timeout=15_000)
    expect_logged_in(page)
    expect(page.locator('input[placeholder="Ваше имя"]')).to_be_enabled(
        timeout=15_000
    )


@pytest.fixture(autouse=True)
def _mobile_helpers(monkeypatch):
    """Импортированные тесты берут хелперы из глобалов ДЕСКТОПНОГО модуля —
    подменяем там (через `__globals__` самой тест-функции, чтобы не попасть
    во вторую копию модуля)."""
    desktop = test_delete_account_cancel.__globals__
    monkeypatch.setitem(desktop, "open_delete_confirmation", open_delete_confirmation)
    monkeypatch.setitem(desktop, "assert_account_alive", assert_account_alive)


# ===========================================================================
# Моб. Поп-ап подтверждения во весь экран, кнопки целиком видны и тапаются
# ===========================================================================
def test_delete_confirmation_fits_screen_and_buttons_tappable(account: Page):
    """Поп-ап занимает экран, «Да, хочу удалить», «Отменить» и крестик лежат
    внутри экрана, и в центре каждой кнопки сверху — сама кнопка (не нижний
    бар, не баннер). Подтверждение НЕ нажимаем — уходим по «Отменить»."""
    page = account
    modal = open_delete_confirmation(page)
    vw, vh = page.viewport_size["width"], page.viewport_size["height"]

    box = modal.bounding_box()
    assert box["width"] >= vw - 1 and box["height"] >= vh - 1, (
        f"Поп-ап подтверждения не на весь экран {vw}×{vh}: {box}"
    )

    actions = modal.locator(ACTIONS)
    buttons = {
        BTN_CONFIRM: actions.get_by_role("button", name=BTN_CONFIRM),
        BTN_CANCEL: actions.get_by_role("button", name=BTN_CANCEL),
        "крестик": modal.locator(".btn__close"),
    }
    problems = []
    for label, btn in buttons.items():
        expect(btn).to_be_visible(timeout=10_000)
        b = btn.bounding_box()
        if b["x"] < 0 or b["y"] < 0 or b["x"] + b["width"] > vw + 1 or b["y"] + b["height"] > vh + 1:
            problems.append(f"«{label}» за краем экрана: {b}")
            continue
        on_top = btn.evaluate(
            """(el) => { const r = el.getBoundingClientRect();
                const t = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                return (t && (t === el || el.contains(t))) ? null
                    : (t ? (t.className || t.tagName).toString() : 'пусто'); }"""
        )
        if on_top:
            problems.append(f"«{label}» перекрыта: {on_top}")

    # Ассерт до тапа: при перекрытой кнопке тап упал бы таймаутом без причины.
    # Поп-ап при этом остаётся открытым — не страшно, контекст одноразовый.
    assert not problems, "Кнопки подтверждения удаления не тапаются: " + "; ".join(problems)

    buttons[BTN_CANCEL].tap()
    expect(page.locator(MODAL)).to_have_count(0, timeout=20_000)

"""Личные данные — мобильная версия (зеркало tests/account/test_personal_data.py).

Что на телефоне иначе (проверено 01.10.2026 в MCP-браузере 412×839):

- вход — «Войти» нижнего бара; в «Личные данные» пользователь попадает через
  «Кабинет» бара → список над баром → «Личные данные» (на десктопе — меню
  «Кабинет» в шапке). Этим путём и идёт фикстура — он же и проверяется;
- над формой меню кабинета столбиком, кнопки «Удалить аккаунт» / «Выйти со
  всех устройств», ниже поля Имя, Фамилия, e-mail (заблокирован) столбиком на
  всю ширину; «Изменить» — внизу формы, над липким нижним баром.

Все пять десктопных кейсов импортированы: они работают с полями и кнопкой
«Изменить» напрямую, отличается только фикстура входа (десктопная — autouse,
сюда не попадает). Свой — поля и кнопка в экране и не перекрыты баром.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from conftest import load_users
from account.test_personal_data import (  # noqa: F401 — тесты собирает pytest
    test_save_without_changes,
    test_change_personal_data,
    test_empty_required_fields_show_error,
    test_change_single_field_keeps_others,
    test_email_field_is_not_editable,
)
from account.test_personal_data import NAME_INPUT, SURNAME_INPUT
from mobile.mobile_auth import login_via_bar, open_cabinet_menu

USERS, _USERS_SKIP = load_users()

pytestmark = [
    pytest.mark.requires_auth,
    pytest.mark.skipif(_USERS_SKIP is not None, reason=_USERS_SKIP or ""),
]

EMAIL_INPUT = 'input[placeholder="Введи e-mail адрес"]'


@pytest.fixture(autouse=True)
def login_and_open_personal_data(page: Page):
    """Вход через бар, затем «Кабинет» в баре → «Личные данные»."""
    user = USERS["loginUser"]
    assert login_via_bar(page, user["email"], user["password"]), (
        f"Не удалось войти под {user['email']}"
    )
    menu = open_cabinet_menu(page)
    menu.get_by_role("button", name="Личные данные").tap()
    expect(page).to_have_url(re.compile(r"/account/?$"), timeout=15_000)
    expect(page.locator(NAME_INPUT)).to_be_enabled(timeout=15_000)


# ===========================================================================
# Моб. Поля и «Изменить» в пределах экрана и не перекрыты
# ===========================================================================
def test_personal_data_form_fits_screen_and_tappable(page: Page):
    """Имя, Фамилия, e-mail и «Изменить» не выходят за край экрана, а
    докрученные к центру экрана — сверху по точке касания.
    E-mail проверяем только на ширину: он намеренно `pointer-events: none`,
    и `elementFromPoint` его не вернёт."""
    vw = page.viewport_size["width"]
    assert page.evaluate("document.documentElement.scrollWidth") <= vw + 1, (
        "Страница «Личные данные» шире экрана"
    )

    controls = {
        "Имя": (page.locator(NAME_INPUT), True),
        "Фамилия": (page.locator(SURNAME_INPUT), True),
        "e-mail": (page.locator(EMAIL_INPUT).last, False),
        "Изменить": (page.get_by_role("button", name="Изменить", exact=True), True),
    }
    problems = []
    for label, (el, tappable) in controls.items():
        expect(el).to_be_visible(timeout=10_000)
        # К центру, как докрутил бы пользователь: «если нужно» Playwright
        # оставляет элемент у нижнего края — ровно под липким баром.
        el.evaluate("e => e.scrollIntoView({block: 'center'})")
        b = el.bounding_box()
        if b["x"] < 0 or b["x"] + b["width"] > vw + 1:
            problems.append(f"«{label}» за краем экрана {vw}: {b}")
            continue
        if not tappable:
            continue
        on_top = el.evaluate(
            """(el) => { const r = el.getBoundingClientRect();
                const t = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                return (t && (t === el || el.contains(t))) ? null
                    : (t ? ((t.className && t.className.baseVal !== undefined
                            ? t.className.baseVal : t.className) || t.tagName).toString()
                        : 'пусто'); }"""
        )
        if on_top:
            problems.append(f"«{label}» перекрыт: {on_top}")

    assert not problems, "Форма «Личные данные» на телефоне не тапается: " + "; ".join(problems)

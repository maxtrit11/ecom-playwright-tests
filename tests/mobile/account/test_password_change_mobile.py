"""Смена пароля — мобильная версия (зеркало tests/account/test_password_change.py).

ВНИМАНИЕ, как и на десктопе: успешный сценарий (151) реально меняет пароль
общей stage-учётки и возвращает его — в тесте и страховкой в фикстуре
`restore_password` (импортирована из десктопного файла).

Что на телефоне иначе (проверено 01.10.2026 в MCP-браузере 412×839):

- блок пароля тот же: «Изменить пароль» раскрывает «Старый пароль» /
  «Новый пароль» столбиком на всю ширину и становится сабмитом;
- вход — «Войти» нижнего бара, ВЫХОД — «Кабинет» в баре → список над баром
  «Личные данные / История заказов / Выйти» (`.header__items__auth__list`).
  Десктопные `login_via_popup` / `logout` кликают по кнопке шапки, которая на
  телефоне 0×0, — поэтому autouse-фикстура подменяет их в глобалах
  десктопного модуля на `login_via_bar` / `logout_mobile`; этим же пользуется
  и финализатор `restore_password`.

Импортированы все четыре кейса (149, 151, 152, 153). Своё — поля и кнопка
в пределах экрана и не перекрыты (форма длинная, под ней липкий нижний бар).
"""

import pytest
from playwright.sync_api import Page, expect

from account.test_password_change import (  # noqa: F401 — тесты и фикстуру собирает pytest
    test_change_password_form_opens,
    test_change_password_empty_fields_show_errors,
    test_change_password_wrong_old_password,
    test_change_password_success,
    restore_password,
)
from account.test_password_change import (
    BTN_CHANGE_PASSWORD,
    EMAIL,
    PASSWORD,
    _USERS_SKIP,
    open_personal_data,
    password_row,
    reveal_password_fields,
)
from mobile.mobile_auth import login_via_bar, logout_mobile

pytestmark = [
    pytest.mark.requires_auth,
    pytest.mark.skipif(_USERS_SKIP is not None, reason=_USERS_SKIP or ""),
]


@pytest.fixture(autouse=True)
def _mobile_helpers(monkeypatch):
    """Импортированные тесты и `restore_password` зовут вход/выход из глобалов
    ДЕСКТОПНОГО модуля — подменяем там (через `__globals__`, чтобы не попасть
    во вторую копию модуля). Autouse → создаётся раньше `restore_password`,
    значит, и откатывается ПОСЛЕ его финализатора: восстановление пароля идёт
    мобильными хелперами."""
    desktop = test_change_password_success.__globals__
    monkeypatch.setitem(desktop, "login_via_popup", login_via_bar)
    monkeypatch.setitem(desktop, "logout", logout_mobile)


@pytest.fixture
def account(page: Page):
    """Вход через нижний бар + страница «Личные данные»."""
    assert login_via_bar(page, EMAIL, PASSWORD), (
        f"Не удалось войти в кабинет под {EMAIL}. Если предыдущий прогон упал "
        f"посреди смены пароля — проверь, не остался ли временный пароль "
        f"(loginUser.tempPassword в users.json)"
    )
    open_personal_data(page)
    return page


# ===========================================================================
# Моб. Поля пароля и кнопка в пределах экрана и тапаются
# ===========================================================================
def test_password_fields_fit_screen_and_tappable(account: Page):
    """После «Изменить пароль» оба поля и кнопка не выходят за край экрана, а
    докрученные в видимую часть — не перекрыты (нижним баром в том числе)."""
    page = account
    row = reveal_password_fields(page)
    vw = page.viewport_size["width"]

    controls = {
        "Старый пароль": row.locator('input[type="password"]').nth(0),
        "Новый пароль": row.locator('input[type="password"]').nth(1),
        "Изменить пароль": page.get_by_role("button", name=BTN_CHANGE_PASSWORD),
    }
    problems = []
    for label, el in controls.items():
        el.scroll_into_view_if_needed()
        b = el.bounding_box()
        if b["x"] < 0 or b["x"] + b["width"] > vw + 1:
            problems.append(f"«{label}» за краем экрана {vw}: {b}")
            continue
        on_top = el.evaluate(
            """(el) => { const r = el.getBoundingClientRect();
                const t = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
                return (t && (t === el || el.contains(t))) ? null
                    : (t ? (t.className || t.tagName).toString() : 'пусто'); }"""
        )
        if on_top:
            problems.append(f"«{label}» перекрыт: {on_top}")

    assert not problems, "Блок смены пароля на телефоне не тапается: " + "; ".join(problems)
    expect(password_row(page)).to_have_count(1)

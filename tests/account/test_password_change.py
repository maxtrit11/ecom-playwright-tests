"""Тесты смены пароля в кабинете (Testiny 149, 151-153)

Блок смены пароля живёт прямо в форме «Личные данные»: кнопка «Изменить
пароль» раскрывает два поля — «Старый пароль» и «Новый пароль» (поля
подтверждения нет), и та же кнопка становится сабмитом. Отправляется
`POST /auth/users/set_password/`.

ВНИМАНИЕ: тест успешной смены реально меняет пароль общей stage-учётки,
которой пользуются и остальные тесты кабинета. Поэтому пароль возвращается
на место дважды: в самом тесте и в финализаторе фикстуры — финализатор
подбирает рабочий пароль из двух, чтобы упавший на середине прогон не оставил
учётку с временным паролем и не обрушил всю остальную суиту.
"""

import re

import pytest
from playwright.sync_api import Page, expect

from conftest import login_via_popup, logout, load_users, open_account_page

USERS, _USERS_SKIP = load_users()

pytestmark = [
    pytest.mark.requires_auth,
    pytest.mark.skipif(_USERS_SKIP is not None, reason=_USERS_SKIP or ""),
]

EMAIL = USERS["loginUser"]["email"]
PASSWORD = USERS["loginUser"]["password"]
# Временный пароль теста успешной смены. Отличается от рабочего, чтобы
# «случайно подошёл» было невозможно. Лежит в users.json (loginUser.tempPassword),
# а не в коде: репозиторий публичный, а пока идёт тест — и если прогон оборвётся
# между двумя сменами — учётка пускает именно по нему. Нет значения — тест
# успешной смены скипается, остальные тесты кабинета он не нужен.
TEMP_PASSWORD = USERS["loginUser"].get("tempPassword", "")
_NO_TEMP_PASSWORD = (
    "в users.json нет loginUser.tempPassword — временного пароля для теста "
    "успешной смены (в CI — в секрете USERS_JSON)"
)

FORM = ".contact-information__form"
BTN_CHANGE_PASSWORD = "Изменить пароль"
SUCCESS_TEXT = "Пароль успешно изменен"


def password_row(page: Page):
    """Строка формы с полями «Старый пароль» / «Новый пароль».

    Ищем по содержимому, а не по `.account-form__row` + `.last`: строк в форме
    несколько (первая — Имя/Фамилия), и порядковый индекс сломается от любого
    нового поля в личных данных.
    """
    return page.locator(f"{FORM} .account-form__row").filter(
        has=page.locator('input[type="password"]')
    )


def reveal_password_fields(page: Page):
    """Раскрыть блок смены пароля и вернуть локатор строки с полями."""
    page.get_by_role("button", name=BTN_CHANGE_PASSWORD).click()
    row = password_row(page)
    expect(row.locator('input[type="password"]')).to_have_count(2, timeout=10_000)
    return row


def submit_password_change(page: Page, old: str, new: str):
    """Заполнить оба поля и нажать «Изменить пароль»."""
    row = password_row(page)
    inputs = row.locator('input[type="password"]')
    inputs.nth(0).fill(old)
    inputs.nth(1).fill(new)
    page.get_by_role("button", name=BTN_CHANGE_PASSWORD).click()


def open_personal_data(page: Page) -> None:
    """Перейти на страницу «Личные данные»."""
    open_account_page(page)
    expect(page).to_have_url(re.compile(r"account"), timeout=15_000)
    expect(page.locator(f'{FORM} input[placeholder="Ваше имя"]')).to_be_enabled(
        timeout=15_000
    )


@pytest.fixture
def account(page: Page):
    """Вход в кабинет + страница «Личные данные»."""
    assert login_via_popup(page, EMAIL, PASSWORD), (
        f"Не удалось войти в кабинет под {EMAIL}. Если предыдущий прогон упал "
        f"посреди смены пароля — проверь, не остался ли временный пароль "
        f"(loginUser.tempPassword в users.json)"
    )
    open_personal_data(page)
    return page


@pytest.fixture
def restore_password(page: Page):
    """Гарантированно вернуть учётке пароль из users.json после теста.

    Тест успешной смены возвращает пароль сам, но если он упадёт между двумя
    сменами — учётка останется с временным паролем, и посыплется ВСЯ остальная
    суита кабинета. Поэтому после теста заходим тем паролем, который сработает,
    и, если это временный, меняем обратно.
    """
    if not TEMP_PASSWORD:
        pytest.skip(_NO_TEMP_PASSWORD)
    yield

    # Тест заканчивается авторизованным, а `login_via_popup` кликает по кнопке
    # шапки — у залогиненного она открывает меню «Кабинет», а не поп-ап входа.
    # Поэтому сначала гарантированно становимся гостем.
    logout(page)

    if login_via_popup(page, EMAIL, PASSWORD):
        return  # рабочий пароль на месте — восстанавливать нечего

    logout(page)
    assert login_via_popup(page, EMAIL, TEMP_PASSWORD), (
        f"Учётка {EMAIL} не пускает ни по основному, ни по временному паролю — "
        f"восстанови вручную пароль из users.json (loginUser.password)"
    )
    open_personal_data(page)
    reveal_password_fields(page)
    submit_password_change(page, TEMP_PASSWORD, PASSWORD)
    expect(page.get_by_text(SUCCESS_TEXT)).to_be_visible(timeout=15_000)


# ===========================================================================
# Кейс 149: Личные данные — переход к изменению пароля
# ===========================================================================
def test_change_password_form_opens(account: Page):
    """Кнопка «Изменить пароль» раскрывает поля старого и нового пароля."""
    page = account

    # До нажатия полей пароля в форме нет
    expect(password_row(page)).to_have_count(0)

    row = reveal_password_fields(page)

    # Оба поля видимы и скрывают ввод
    inputs = row.locator('input[type="password"]')
    for i in range(2):
        expect(inputs.nth(i)).to_be_visible()
        expect(inputs.nth(i)).to_have_attribute("type", "password")

    # Подписи именно у полей пароля. Проверяем текст всей строки, а не
    # локатор `label`: их два, и `to_contain_text` на двух элементах уходит в
    # strict mode violation вместо осмысленной проверки.
    expect(row).to_contain_text(re.compile("старый пароль", re.I))
    expect(row).to_contain_text(re.compile("новый пароль", re.I))


# ===========================================================================
# Кейс 153: Изменение пароля — ошибка при пустых полях
# ===========================================================================
def test_change_password_empty_fields_show_errors(account: Page):
    """Сабмит с пустыми полями — под обоими ошибка «Это обязательное поле»."""
    page = account
    row = reveal_password_fields(page)

    page.get_by_role("button", name=BTN_CHANGE_PASSWORD).click()

    validations = row.locator(".validation:visible")
    expect(validations).to_have_count(2, timeout=10_000)
    expect(validations.first).to_contain_text(
        re.compile("обязательное поле", re.I)
    )

    # Поля остаются на месте — форма не отправилась
    expect(row.locator('input[type="password"]')).to_have_count(2)
    expect(page.get_by_text(SUCCESS_TEXT)).not_to_be_visible()


# ===========================================================================
# Кейс 152: Изменение пароля — ошибка при неверном старом пароле
# ===========================================================================
def test_change_password_wrong_old_password(account: Page):
    """Неверный старый пароль — ошибка «Неверный пароль», пароль не меняется."""
    page = account
    row = reveal_password_fields(page)

    submit_password_change(page, "WrongOldPass999!", "SomeNewPass123!")

    # Сервер отвечает 400, под полем старого пароля появляется «Неверный пароль»
    expect(row.locator(".validation:visible")).to_contain_text(
        re.compile("неверный пароль", re.I), timeout=15_000
    )
    expect(page.get_by_text(SUCCESS_TEXT)).not_to_be_visible()

    # Главное: пароль НЕ поменялся — вход по рабочему паролю всё ещё проходит
    logout(page)
    assert login_via_popup(page, EMAIL, PASSWORD), (
        "После неудачной смены пароля вход по рабочему паролю перестал работать"
    )


# ===========================================================================
# Кейс 151: Изменение пароля — успешный сценарий
# ===========================================================================
def test_change_password_success(account: Page, restore_password):
    """Смена пароля проходит, старый перестаёт подходить, новый — работает."""
    page = account
    reveal_password_fields(page)

    # 1. Меняем рабочий пароль на временный
    submit_password_change(page, PASSWORD, TEMP_PASSWORD)
    expect(page.get_by_text(SUCCESS_TEXT)).to_be_visible(timeout=15_000)

    logout(page)

    # 2. Старый пароль больше не подходит — иначе «успех» был только на экране
    assert not login_via_popup(page, EMAIL, PASSWORD), (
        "Вход по старому паролю всё ещё проходит — пароль фактически не сменился"
    )

    # 3. Новый пароль работает
    assert login_via_popup(page, EMAIL, TEMP_PASSWORD), (
        "Вход по новому паролю не проходит"
    )

    # 4. Возвращаем рабочий пароль (страховка — в фикстуре restore_password)
    open_personal_data(page)
    reveal_password_fields(page)
    submit_password_change(page, TEMP_PASSWORD, PASSWORD)
    expect(page.get_by_text(SUCCESS_TEXT)).to_be_visible(timeout=15_000)

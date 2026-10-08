"""Тесты поп-апа Авторизация"""

import pytest
from playwright.sync_api import Page, expect


# ---------------------------------------------------------------------------
# Хелпер: открыть поп-ап авторизации
# ---------------------------------------------------------------------------
def open_auth_popup(page: Page) -> None:
    page.locator(".btn__action.btn__auth").click(force=True)
    page.locator(".modal__authentification__ecom-content").first.wait_for(
        state="visible", timeout=10_000
    )


# ---------------------------------------------------------------------------
# Фикстура: перейти на главную перед каждым тестом
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def navigate_home(page: Page):
    page.goto("/ru")
    page.wait_for_load_state("networkidle")


# ===========================================================================
# Кейс 1: Открыть поп-ап авторизации
# ===========================================================================
@pytest.mark.smoke
def test_open_auth_popup_with_all_elements(page: Page):
    """Открытие поп-апа авторизации с проверкой всех элементов."""
    open_auth_popup(page)

    modal = page.locator(".modal__authentification__ecom-content").first

    # Отображается поле Email
    expect(page.locator('input[placeholder="Введи e-mail адрес"]').first).to_be_visible()

    # Отображается поле Password
    expect(modal.locator('input[type="password"]')).to_be_visible()

    # Отображается кнопка «Войдите в аккаунт»
    submit_btn = modal.locator('button[type="submit"]')
    expect(submit_btn).to_be_visible()
    expect(submit_btn).to_contain_text("Войдите в аккаунт")

    # Отображается кнопка «Восстановить»
    expect(modal.get_by_text("Восстановить")).to_be_visible()

    # Отображается кнопка «Зарегистрироваться»
    expect(modal.get_by_text("Зарегистрироваться")).to_be_visible()


# ===========================================================================
# Кейс 2: Закрыть поп-ап авторизации нажав на кнопку X
# ===========================================================================
def test_close_auth_popup_by_x_button(page: Page):
    """Закрытие поп-апа авторизации по клику на X."""
    open_auth_popup(page)

    modal = page.locator(".modal__authentification__ecom-content").first

    # Нажать на кнопку «X»
    modal.locator(".btn__close").click()

    # Поп-ап авторизации закрывается
    expect(
        page.locator(".modal__authentification__ecom-content").first
    ).not_to_be_visible()


# ===========================================================================
# Кейс 3: Отображение ошибки при вводе несуществующих данных
# ===========================================================================
@pytest.mark.expected_http(400)  # неверный логин: /auth/jwt/create/ отвечает 400 штатно
def test_invalid_credentials_show_error(page: Page):
    """Отображение ошибки при вводе несуществующих данных."""
    open_auth_popup(page)

    modal = page.locator(".modal__authentification__ecom-content").first

    # Ввести рандомный email и пароль
    page.locator('input[placeholder="Введи e-mail адрес"]').first.fill(
        "fakeuser_test@nonexistent.com"
    )
    modal.locator('input[type="password"]').fill("WrongPass123!")

    # Нажать на кнопку «Войдите в аккаунт»
    modal.get_by_text("Войдите в аккаунт").click()

    # Отображается ошибка авторизации. Серверная ошибка живёт НЕ в `.validation`
    # (те остаются display:none — это валидация «поле обязательно»), а в
    # отдельном блоке формы. Продукт показывает «Неверный логин или пароль».
    error = modal.locator(".modal__authentification__ecom-content-form-error")
    expect(error.first).to_be_visible(timeout=10_000)
    expect(error.first).to_contain_text("пароль", timeout=10_000)


# ===========================================================================
# Кейс 4: Отображение ошибки для пустых полей ввода
# ===========================================================================
def test_empty_fields_show_validation_errors(page: Page):
    """Отображение ошибок при пустых полях."""
    open_auth_popup(page)

    modal = page.locator(".modal__authentification__ecom-content").first

    # Нажать на кнопку «Войдите в аккаунт»
    modal.get_by_text("Войдите в аккаунт").click()

    # Отображаются сообщения «Это обязательное поле»
    validations = modal.locator(".validation:visible")
    expect(validations).to_have_count(2)
    expect(validations.first).to_contain_text("Это обязательное поле")


# ===========================================================================
# Кейс 123: Закрыть поп-ап авторизации кликом вне его области
# ===========================================================================
def test_close_auth_popup_by_click_outside(page: Page):
    """Клик по затемнённой области вне карточки закрывает поп-ап."""
    open_auth_popup(page)

    modal = page.locator(".modal__authentification__ecom-content").first

    # Кликаем слева от карточки — координаты считаем от неё самой, чтобы тест
    # не зависел от ширины окна и не попал случайно по самой карточке.
    box = modal.bounding_box()
    page.mouse.click(max(box["x"] / 2, 10), box["y"] + box["height"] / 2)

    expect(page.locator(".modal__authentification__ecom-content")).to_have_count(0)


# ===========================================================================
# Кейс 124: Маска пароля
# ===========================================================================
def test_password_is_masked(page: Page):
    """Пароль вводится скрытым: type=password, но значение сохраняется целиком."""
    open_auth_popup(page)

    modal = page.locator(".modal__authentification__ecom-content").first
    password = modal.locator('input[type="password"]').first

    # По умолчанию поле скрывает ввод
    expect(password).to_have_attribute("type", "password")

    secret = "SecretPass123!"
    password.fill(secret)

    # Символы не показываются — атрибут type не переключился сам по себе
    expect(password).to_have_attribute("type", "password")
    # ...но введённое значение не искажено маской
    expect(password).to_have_value(secret)


# ===========================================================================
# Кейс 125: Показать / скрыть пароль
# ===========================================================================
def test_toggle_password_visibility(page: Page):
    """Иконка глаза переключает пароль между скрытым и видимым."""
    open_auth_popup(page)

    modal = page.locator(".modal__authentification__ecom-content").first
    password = modal.locator('input[placeholder="********"]').first
    eye = modal.locator("button.show__password").first

    password.fill("SecretPass123!")
    expect(password).to_have_attribute("type", "password")

    # Клик по глазу — пароль виден
    eye.click()
    expect(password).to_have_attribute("type", "text")

    # Повторный клик — снова скрыт
    eye.click()
    expect(password).to_have_attribute("type", "password")

    # Значение при переключениях не потерялось
    expect(password).to_have_value("SecretPass123!")


# ===========================================================================
# Кейс 127: Переход к восстановлению пароля
# ===========================================================================
def test_go_to_password_recovery(page: Page):
    """«Забыли пароль? Восстановить» открывает форму восстановления."""
    open_auth_popup(page)

    modal = page.locator(".modal__authentification__ecom-content").first

    # В поп-апе два блока-подсказки (восстановление и регистрация) — берём
    # кнопку по тексту, а не по позиции.
    modal.get_by_role("button", name="Забыли пароль? Восстановить").click()

    # Открылась форма восстановления: заголовок, пояснение и поле email
    recovery = page.locator(".modal__authentification__ecom-content").first
    expect(recovery.locator("h2")).to_contain_text("Восстановление пароля")
    expect(recovery).to_contain_text("адрес электронной почты")
    expect(
        recovery.locator('input[placeholder="Введи e-mail адрес"]')
    ).to_be_visible()

    # Поля пароля больше нет — это уже другая форма, а не прежняя авторизация
    expect(recovery.locator('input[type="password"]')).to_have_count(0)

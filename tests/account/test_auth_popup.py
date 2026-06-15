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

    # Отображается ошибка авторизации (точный текст не важен —
    # важно, что появляется сообщение об ошибке логина/пароля).
    # Продукт показывает «Неверный логин или пароль».
    error = modal.locator(".validation:visible")
    expect(error.first).to_be_visible(timeout=10_000)
    expect(modal).to_contain_text("пароль", timeout=10_000)


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

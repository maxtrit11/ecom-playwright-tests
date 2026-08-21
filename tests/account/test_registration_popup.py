"""Тесты поп-апа Регистрация"""

import re
import time

import pytest
from playwright.sync_api import Page, expect

from conftest import load_users

USERS, _ = load_users()

# Телефон уже зарегистрированного пользователя — для проверки дубля.
REGISTERED_PHONE = USERS["registerUser"]["phone"]

# Эндпоинт регистрации: по числу запросов к нему проверяется защита от
# двойного клика (см. соответствующий тест).
REGISTER_ENDPOINT = "/auth/users/"


# ---------------------------------------------------------------------------
# Хелпер: открыть поп-ап регистрации
# ---------------------------------------------------------------------------
def open_registration_popup(page: Page) -> None:
    page.locator(".btn__action.btn__auth").click(force=True)
    page.locator(".modal__authentification__ecom-content").first.wait_for(
        state="visible", timeout=10_000
    )

    page.get_by_text("Зарегистрироваться").first.click()
    expect(
        page.get_by_role("heading", name="Регистрация")
    ).to_be_visible(timeout=10_000)


# ---------------------------------------------------------------------------
# Фикстура: перейти на главную перед каждым тестом
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def navigate_home(page: Page):
    # wait_until="load" зависает на /ru из-за фоновых ресурсов
    # (чат-виджет и т.д.) — используем domcontentloaded
    page.goto("/ru", wait_until="domcontentloaded", timeout=60_000)
    # networkidle тоже зачастую не достигается — ждём наличия шапки
    page.locator(".btn__action.btn__auth").wait_for(state="visible", timeout=15_000)


# ===========================================================================
# Кейс 1: Переход на поп-ап Регистрации
# ===========================================================================
def test_open_registration_popup_with_all_elements(page: Page):
    """Открытие поп-апа регистрации с проверкой всех элементов."""
    page.locator(".btn__action.btn__auth").click(force=True)
    page.locator(".modal__authentification__ecom-content").first.wait_for(
        state="visible", timeout=10_000
    )

    # Нажать на кнопку «Зарегистрироваться»
    page.get_by_text("Зарегистрироваться").first.click()

    # Открывается поп-ап регистрации
    expect(
        page.get_by_role("heading", name="Регистрация")
    ).to_be_visible(timeout=10_000)

    # По умолчанию выбран тип «Физическое лицо»
    active_tab = page.locator(
        ".modal__authentification__ecom-content-form-tabs button.active"
    )
    expect(active_tab).to_contain_text("Физическое лицо")

    # Поля ищем ВНУТРИ поп-апа, а не по всей странице: на главной живёт ещё и
    # промо-модалка «подарок» (.modal__gift) со своим полем телефона. Как только
    # она хоть раз показалась, intl-tel-input вешает .iti__tel-input и на неё —
    # и общестраничный селектор находит два поля, падая на strict mode
    # (прогон 32455950259). Внутри формы регистрации поле ровно одно.
    form = page.locator(".modal__authentification__ecom-content")

    # Отображаются все поля формы
    expect(form.locator('input[placeholder="Ваше имя"]')).to_be_visible()
    expect(form.locator('input[placeholder="Ваше фамилия"]')).to_be_visible()
    expect(
        form.locator('input[placeholder="Введи e-mail адрес"]').first
    ).to_be_visible()
    # Видимое пользователю поле телефона — сгенерированное плагином
    # .iti__tel-input, а не исходный <input id="phone">.
    expect(form.locator('input[type="tel"].iti__tel-input')).to_be_visible()

    password_fields = form.locator('input[type="password"]')
    expect(password_fields).to_have_count(2)
    for i in range(2):
        expect(password_fields.nth(i)).to_be_visible()


# ===========================================================================
# Кейс 2: Отображение ошибки при вводе пустых полей
# ===========================================================================
def test_empty_fields_show_validation_errors(page: Page):
    """Отображение ошибок при отправке пустых обязательных полей."""
    open_registration_popup(page)

    modal = page.locator(".modal__authentification__ecom-content")

    # Нажать кнопку «Зарегистрироваться» не заполняя поля
    modal.locator('button[type="submit"]').first.click()

    # Под обязательными полями отображаются сообщения об ошибке
    visible_validations = modal.locator(".validation:visible")
    assert visible_validations.count() >= 3

    # Регистрация не выполняется — поп-ап остаётся открытым
    expect(page.get_by_role("heading", name="Регистрация")).to_be_visible()


# ===========================================================================
# Кейс 3: Показать / Скрыть пароль (иконка глаза)
# ===========================================================================
def test_toggle_password_visibility(page: Page):
    """Показать и скрыть пароль по клику на иконку глаза."""
    open_registration_popup(page)

    password_input = page.locator('input[placeholder="********"]').first

    # Ввести пароль
    password_input.fill("TestPassword123")

    # Символы отображаются в виде точек (type=password)
    expect(password_input).to_have_attribute("type", "password")

    # Кликаем на иконку глаза — пароль виден
    page.locator("button.show__password").first.click()
    expect(password_input).to_have_attribute("type", "text")

    # Повторный клик — пароль снова скрыт
    page.locator("button.show__password").first.click()
    expect(password_input).to_have_attribute("type", "password")


# ===========================================================================
# Кейс 4: Ввести неправильный повторный пароль
# ===========================================================================
def test_password_mismatch_shows_error(page: Page):
    """Отображение ошибки при несовпадении паролей."""
    open_registration_popup(page)

    form = page.locator(".modal__authentification__ecom-content-form")

    # Заполнить все поля
    form.locator('input[placeholder="Ваше имя"]').fill("Тест")
    form.locator('input[placeholder="Ваше фамилия"]').fill("Тестов")
    form.locator('input[placeholder="Введи e-mail адрес"]').first.fill(
        "testuser_random@test.com"
    )
    form.locator('input[type="tel"].iti__tel-input').fill("60123456")

    # Ввести разные пароли
    password_fields = form.locator('input[placeholder="********"]')
    password_fields.nth(0).fill("Password123!")
    expect(password_fields.nth(0)).to_have_attribute("type", "password")

    password_fields.nth(1).fill("DifferentPass456!")

    # Нажать кнопку «Зарегистрироваться»
    form.locator('button[type="submit"]').first.click()

    # Отображается сообщение о несовпадении паролей
    modal = page.locator(".modal__authentification__ecom-content")
    validation_messages = modal.locator(".validation:visible")
    expect(validation_messages).to_contain_text("Пароли не совпадают")

    # Поп-ап остаётся открытым
    expect(page.get_by_role("heading", name="Регистрация")).to_be_visible()


# ===========================================================================
# Кейс 5: Ошибка при вводе почты уже зарегистрированного пользователя
# ===========================================================================
def test_duplicate_email_shows_error(page: Page):
    """Отображение ошибки при вводе уже зарегистрированного email."""
    open_registration_popup(page)

    form = page.locator(".modal__authentification__ecom-content-form")

    # Заполнить форму валидными данными
    form.locator('input[placeholder="Ваше имя"]').fill("Тест")
    form.locator('input[placeholder="Ваше фамилия"]').fill("Тестов")
    form.locator('input[type="tel"].iti__tel-input').fill("60123456")

    password_fields = form.locator('input[placeholder="********"]')
    password_fields.nth(0).fill("Password123!")
    password_fields.nth(1).fill("Password123!")

    checkbox = form.locator('input[type="checkbox"]')
    checkbox.dispatch_event("click")

    # Валидация не отображается
    expect(form.locator(".validation:visible")).to_have_count(0)

    # Ввести e-mail уже зарегистрированного пользователя
    form.locator('input[placeholder="Введи e-mail адрес"]').first.fill(
        "maxim.turcan1@gmail.com"
    )

    # Нажать кнопку «Зарегистрироваться»
    form.locator('button[type="submit"]').first.click()

    # Отображается сообщение, что Email уже используется
    modal = page.locator(".modal__authentification__ecom-content")
    expect(modal.locator(".validation:visible")).to_contain_text(
        "Пользователь с указанным адресом электронной почты уже существует",
        timeout=10_000,
    )

    # Поп-ап остаётся открытым
    expect(page.get_by_role("heading", name="Регистрация")).to_be_visible()


# ===========================================================================
# Кейс 6: Переключатели — Юридическое лицо
# ===========================================================================
def test_switch_to_legal_entity_shows_extra_fields(page: Page):
    """Переключение на тип Юридическое лицо с отображением доп. полей."""
    open_registration_popup(page)

    form = page.locator(".modal__authentification__ecom-content-form")

    # Нажать на «Юридическое лицо»
    page.get_by_text("Юридическое лицо").click()

    # Проверить активную вкладку
    active_tab = page.locator(
        ".modal__authentification__ecom-content-form-tabs button.active"
    )
    expect(active_tab).to_contain_text("Юридическое лицо")

    # Проверить дополнительные поля
    for label_text in [
        "Название компании",
        "ИДНО",
        "Физический адрес",
        "Юридический адрес",
        "Район",
        "Город",
        "Название Банка",
        "Cont/IBAN",
    ]:
        expect(form.locator("label", has_text=label_text)).to_be_visible()


# ===========================================================================
# Кейс 7: Положительный сценарий регистрации
# ===========================================================================
def test_successful_registration(page: Page):
    """Успешная регистрация нового пользователя."""
    open_registration_popup(page)

    form = page.locator(".modal__authentification__ecom-content-form")
    unique = int(time.time() * 1000)
    unique_email = f"testqa_{unique}@mailinator.com"
    unique_phone = str(unique)[-6:]

    # Заполнить все поля
    form.locator('input[placeholder="Ваше имя"]').fill("Тест")
    form.locator('input[placeholder="Ваше фамилия"]').fill("Тестов")
    form.locator('input[placeholder="Введи e-mail адрес"]').first.fill(
        unique_email
    )
    form.locator('input[type="tel"].iti__tel-input').fill(f"60{unique_phone}")

    password_fields = form.locator('input[placeholder="********"]')
    password_fields.nth(0).fill("TestPass123!")
    password_fields.nth(1).fill("TestPass123!")

    # Отметить чекбокс согласия
    checkbox = form.locator('input[type="checkbox"]')
    checkbox.dispatch_event("click")

    # Валидация не отображается
    expect(form.locator(".validation:visible")).to_have_count(0)

    # Нажать кнопку «Зарегистрироваться»
    form.locator('button[type="submit"]').first.click()

    # Отображается сообщение об отправке ссылки активации
    expect(
        page.get_by_text("была отправлена ссылка")
    ).to_be_visible(timeout=15_000)


# ---------------------------------------------------------------------------
# Хелпер: заполнить форму регистрации валидными данными
# ---------------------------------------------------------------------------
def fill_registration_form(page: Page, email: str, phone: str) -> None:
    """Заполнить все обязательные поля физлица и отметить согласие."""
    form = page.locator(".modal__authentification__ecom-content-form")

    form.locator('input[placeholder="Ваше имя"]').fill("Тест")
    form.locator('input[placeholder="Ваше фамилия"]').fill("Тестов")
    form.locator('input[placeholder="Введи e-mail адрес"]').first.fill(email)
    form.locator('input[type="tel"].iti__tel-input').fill(phone)

    password_fields = form.locator('input[placeholder="********"]')
    password_fields.nth(0).fill("TestPass123!")
    password_fields.nth(1).fill("TestPass123!")

    # Чекбокс перекрыт кастомной разметкой — кликаем событием, как в кейсе 7
    form.locator('input[type="checkbox"]').dispatch_event("click")


# ===========================================================================
# Кейс 134: Регистрация — переход к авторизации
# ===========================================================================
def test_go_to_authorization_from_registration(page: Page):
    """«Есть аккаунт? Войти» возвращает из регистрации в форму входа."""
    open_registration_popup(page)

    modal = page.locator(".modal__authentification__ecom-content")
    modal.get_by_role("button", name="Есть аккаунт? Войти").click()

    # Сначала дожидаемся, пока уедет форма регистрации: на время анимации
    # перехода в DOM ЛЕЖАТ ОБА заголовка и оба набора полей, и любая проверка
    # «сколько полей пароля» в этот момент ловит смесь двух форм.
    expect(page.get_by_role("heading", name="Регистрация")).not_to_be_visible(
        timeout=15_000
    )

    # Открылась форма авторизации: заголовок, кнопка входа и одно поле пароля
    expect(modal.locator("h2")).to_contain_text("Аутентификация")
    expect(modal.locator('button[type="submit"]')).to_contain_text(
        "Войдите в аккаунт"
    )
    expect(modal.locator('input[type="password"]')).to_have_count(1)


# ===========================================================================
# Кейс 141: Ошибка при использовании номера зарегистрированного пользователя
# ===========================================================================
def test_duplicate_phone_shows_error(page: Page):
    """Регистрация на занятый номер телефона отклоняется с понятной ошибкой."""
    open_registration_popup(page)

    # E-mail обязательно уникальный: иначе непонятно, на что именно ругнулся
    # сервер — на почту или на телефон, и тест проверял бы не тот кейс.
    unique_email = f"testqa_{int(time.time() * 1000)}@mailinator.com"
    fill_registration_form(page, unique_email, REGISTERED_PHONE)

    form = page.locator(".modal__authentification__ecom-content-form")
    # До отправки валидация молчит — значит форма заполнена корректно
    expect(form.locator(".validation:visible")).to_have_count(0)

    form.locator('button[type="submit"]').first.click()

    # Ошибка приходит от сервера в блок валидации под полем телефона.
    # Регистр игнорируем: текст выводится капсом через CSS.
    expect(form.locator(".validation:visible")).to_contain_text(
        re.compile("номером телефона уже существует", re.I), timeout=15_000
    )

    # Регистрация не выполнилась — поп-ап остался открытым
    expect(page.get_by_role("heading", name="Регистрация")).to_be_visible()


# ===========================================================================
# Кейс 143: Защита от двойного клика по кнопке регистрации
# ===========================================================================
@pytest.mark.real_submit
def test_double_click_creates_single_account(page: Page):
    """Двойной клик по «Зарегистрироваться» отправляет ровно один запрос.

    Проверяем не внешний вид кнопки, а число POST-запросов на создание
    пользователя: именно дубль запроса означает второй аккаунт (и второе письмо
    активации). Продукт защищается полноэкранным лоадером `.vld-overlay`,
    который перехватывает повторный клик — сама кнопка при этом не получает
    атрибут `disabled`, так что проверка на disabled была бы ложно-зелёной.
    """
    open_registration_popup(page)

    requests: list[str] = []
    page.on(
        "request",
        lambda r: (
            requests.append(r.url)
            if r.method == "POST" and REGISTER_ENDPOINT in r.url
            else None
        ),
    )

    unique = int(time.time() * 1000)
    fill_registration_form(
        page,
        f"testqa_dbl_{unique}@mailinator.com",
        f"61{str(unique)[-6:]}",
    )

    submit = page.locator(
        ".modal__authentification__ecom-content-form button[type='submit']"
    ).first

    # Второй клик — force: лоадер накрывает кнопку, и обычный click просто
    # ждал бы её освобождения вместо того, чтобы сымитировать спешащего юзера.
    submit.click()
    submit.click(force=True)

    # Регистрация всё-таки прошла — иначе «один запрос» ничего не доказывает
    expect(page.get_by_text("была отправлена ссылка")).to_be_visible(
        timeout=20_000
    )

    # Даём заведомо опоздавшему дублю время долететь
    page.wait_for_timeout(3_000)
    assert len(requests) == 1, (
        f"Ожидался 1 запрос регистрации, отправлено {len(requests)} — "
        f"двойной клик создаёт лишний аккаунт"
    )

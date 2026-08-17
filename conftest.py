import json
import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "viewport": {"width": 1920, "height": 1080},
        "ignore_https_errors": True,
    }


# ---------------------------------------------------------------------------
# Ожидание гидрации Nuxt.
#
# Стенд отдаёт разметку с сервера, поэтому кнопки ВИДНЫ раньше, чем Vue навесит
# на них обработчики. Тест, который дождался только видимости и сразу кликнул,
# теряет клик: страница выглядит готовой, но ещё не реагирует. Особенно коварен
# `click(force=True)` — force отключает проверки готовности, так что Playwright
# даже не пытается дождаться интерактивности.
#
# Проверено экспериментально (2026-07-29, по 3 прогона на вариант).
#
# Карточка товара — хватает `window.$nuxt`:
#   только видимость   → 0/3   networkidle → 3/3 (~3.1s)   $nuxt → 3/3 (~1.2s)
#
# Главная (кнопка «Войти» в шапке) — `$nuxt` уже НЕ хватает: корень смонтирован,
# а шапка навешивает обработчик чуть позже:
#   $nuxt          → 0/3
#   $nuxt + 300ms  → 3/3 (~1.4s)
#   networkidle    → 3/3 (~2.2s)
#   клик с повтором→ 3/3 (всегда срабатывает со 2-й попытки)
#
# Отсюда двухступенчатое ожидание: сначала `$nuxt` (монтирование корня), затем
# ОГРАНИЧЕННОЕ ожидание сетевой тишины на до-монтирование дочерних компонентов.
# Фиксированную паузу не ставим: 300ms достаточно локально, но под нагрузкой в
# CI не хватит. Потолок в 3s держит цену: если стенд всё время что-то опрашивает
# и тишина не наступает никогда, ждём 3s и идём дальше, а не висим до таймаута.
# ---------------------------------------------------------------------------
_HYDRATED_JS = "() => typeof window.$nuxt !== 'undefined'"
_HYDRATION_TIMEOUT_MS = 30_000
_SETTLE_TIMEOUT_MS = 3_000


def wait_hydrated(page, timeout: int | None = None) -> None:
    """Дождаться, пока Vue-приложение смонтируется и начнёт реагировать на клики.

    Не бросает исключение: на редиректах, 404 и служебных страницах `$nuxt` может
    не появиться, и падать из-за этого тест не должен — там просто нечего ждать.
    """
    try:
        page.wait_for_function(_HYDRATED_JS, timeout=timeout or _HYDRATION_TIMEOUT_MS)
    except Exception:
        return
    try:
        page.wait_for_load_state("networkidle", timeout=_SETTLE_TIMEOUT_MS)
    except Exception:
        pass


# Методы, после которых страница перезагружается с нуля и гидрацию нужно ждать
# заново. SPA-переходы по клику сюда не входят — там приложение уже живое.
_NAVIGATION_METHODS = ("goto", "reload", "go_back", "go_forward")


@pytest.fixture(autouse=True)
def _hydrate_after_navigation(page):
    """Автоматически ждать гидрации после каждой полной навигации.

    Обёртка на уровне conftest, а не правка каждого теста: иначе один забытый
    `goto` возвращает ложное падение, которое выглядит как баг продукта.
    """

    def wrap(original):
        def wrapper(*args, **kwargs):
            result = original(*args, **kwargs)
            wait_hydrated(page)
            return result

        return wrapper

    for name in _NAVIGATION_METHODS:
        setattr(page, name, wrap(getattr(page, name)))
    yield


@pytest.fixture
def hydrated():
    """Явное ожидание гидрации — для навигаций, которые инициирует само приложение.

    Обёртка выше ловит только явные `goto`/`reload`/`go_back`. Но страница
    перезагружается и сама: например, успешный логин делает полный редирект, после
    которого шапка гидрируется заново — и клик по «Кабинет», сделанный сразу за
    логином, снова теряется. Такие места помечаем вызовом `hydrated(page)`.
    """
    return wait_hydrated


# ---------------------------------------------------------------------------
# Динамический подбор товара со стоком.
# Товары на stage то и дело уходят в «Предзаказ» (нет стока) — тогда чекаут
# непроходим и фикстуры корзины/чекаута падают. Чтобы не залипать на одном
# хардкоженном товаре, ищем доступный: сначала среди кандидатов, потом — из
# категории. Резолвится один раз за сессию и переиспользуется всеми тестами.
# ---------------------------------------------------------------------------
_PRODUCT_CANDIDATES = [
    "/ru/product/jbl-tour-one-m3-smart-tx-black",
    "/ru/product/jbl-tour-pro-3-latte",
    "/ru/product/jbl-jbl-tour-one-m2-black",
    "/ru/product/jbl-live-770nc-sandstone",
    "/ru/product/live-beam-3-black",
]
# Категории, со страниц которых добираем кандидатов, если список выше не дал стока.
_CATEGORY_FALLBACKS = ["/ru/casti", "/ru/acustica-portabila", "/ru/catalog"]

# Остаток лежит прямо в SSR-пейлоаде страницы (`window.__NUXT__`), который
# инлайнится в HTML — то есть доступен сразу после domcontentloaded, без гидрации.
# На карточке товара это `state.product.product.stock`, на странице категории —
# объекты вида {slug, stock} внутри того же дерева.
_PDP_STOCK_JS = "() => window.__NUXT__?.state?.product?.product?.stock ?? null"

# Обход дерева __NUXT__: собираем все объекты, у которых есть и slug, и stock.
_CATEGORY_STOCK_JS = """
() => {
  const seen = new Set();
  const out = [];
  const walk = (o) => {
    if (!o || typeof o !== 'object' || seen.has(o) || out.length > 500) return;
    seen.add(o);
    if (!Array.isArray(o) && 'stock' in o && (o.slug || o.url)) {
      out.push({ slug: o.slug || o.url, stock: o.stock });
    }
    for (const k of Object.keys(o)) walk(o[k]);
  };
  walk(window.__NUXT__);
  return [...new Map(out.map(p => [p.slug, p])).values()]
           .filter(p => Number(p.stock) > 0)
           .map(p => p.slug);
}
"""


def _has_stock(page, product_url: str) -> bool:
    """Проверить реальный остаток товара по данным страницы.

    ВАЖНО (проверено на живом stage 2026-07-29): по кнопке «В корзину» сток НЕ
    определяется — в данных одновременно `stock: 0` и `available: true`, а вёрстка
    смотрит на `available`, поэтому кнопка остаётся активной при нулевом остатке
    (меняется лишь текст на «Предзаказ»).

    Раньше остаток подтверждался добавлением в корзину. Это работало, но стоило
    ~15s на товар и ломалось от гонки с гидрацией: клик «В корзину» не доходил,
    корзина оставалась пустой, и товар со стоком 43 отбраковывался как пустой.
    Из-за этого фикстура уходила в перебор всех товаров категорий и съедала
    десятки минут. Теперь читаем остаток напрямую — один evaluate вместо цикла.
    """
    try:
        page.goto(product_url, wait_until="domcontentloaded", timeout=60_000)
        stock = page.evaluate(_PDP_STOCK_JS)
    except Exception:
        return False
    return isinstance(stock, (int, float)) and not isinstance(stock, bool) and stock > 0


def _resolve_in_stock_products(page, count: int) -> list[str]:
    """Вернуть до `count` различных URL товаров со стоком."""
    found: list[str] = []

    def _try(url: str) -> None:
        url = url.split("?")[0]
        if url not in found and _has_stock(page, url):
            found.append(url)

    for url in _PRODUCT_CANDIDATES:
        _try(url)
        if len(found) >= count:
            return found

    # Кандидаты не дали стока — берём его со страницы категории одним запросом,
    # а не перебором «зайти в товар → положить в корзину → посмотреть».
    for category in _CATEGORY_FALLBACKS:
        try:
            page.goto(category, wait_until="domcontentloaded", timeout=60_000)
            slugs = page.evaluate(_CATEGORY_STOCK_JS)
        except Exception:
            continue
        for slug in slugs:
            # Подтверждаем на самой карточке: в листинге сток может быть
            # суммарным по вариантам цвета, а тестам нужен конкретный товар.
            _try(slug if slug.startswith("/") else f"/ru/product/{slug}")
            if len(found) >= count:
                return found

    if not found:
        raise RuntimeError(
            "Не нашли ни одного товара со стоком ни среди кандидатов, ни в категориях"
        )
    return found


@pytest.fixture(scope="session")
def in_stock_products(browser, base_url) -> list[str]:
    """До 2 различных товаров со стоком (для тестов, где нужно ≥2 товара)."""
    ctx = browser.new_context(base_url=base_url, ignore_https_errors=True)
    page = ctx.new_page()
    try:
        return _resolve_in_stock_products(page, count=2)
    finally:
        ctx.close()


@pytest.fixture(scope="session")
def in_stock_product(in_stock_products) -> str:
    """Один товар со стоком."""
    return in_stock_products[0]


# ---------------------------------------------------------------------------
# Динамический подбор товара, доступного в кредит.
# Кредит включается не для всего каталога: в пейлоаде товара лежит
# `credit: {has, value, rate, months}`, и при `has: false` вёрстка рендерит
# `div.actions.product.credit-not-available` вообще БЕЗ кнопки `button.btn__credit`.
# Проверено на живом stage 2026-07-30: у зашитого раньше в тесты
# `jbl-partybox-on-the-go-2` (сток 82, цена 6649) `credit.has == false`, поэтому
# фикстура падала на «element(s) not found» — селектор при этом верный.
# Отсюда тот же приём, что и со стоком: искать товар по данным, а не хардкодить.
# ---------------------------------------------------------------------------
_CREDIT_CANDIDATES = [
    # Подтверждён вручную 2026-08-03 — проверяем первым, чтобы фикстура не
    # перебирала остальных кандидатов и категории.
    "/ru/product/jbl-charge-6-purple",
    "/ru/product/harman-kardon-onyx-studio-9-grey",
    "/ru/product/harman-kardon-onyx-studio-9-black",
    "/ru/product/jbl-boombox-4-black",
]
_CREDIT_CATEGORY_FALLBACKS = ["/ru/acustica-portabila", "/ru/casti", "/ru/catalog"]

_PDP_CREDIT_JS = "() => window.__NUXT__?.state?.product?.product?.credit?.has === true"

# То же дерево `__NUXT__`, но отбираем по кредиту; сток тоже требуем — без него
# товар уходит в «Предзаказ» и часть сценариев кредита недоступна.
_CATEGORY_CREDIT_JS = """
() => {
  const seen = new Set();
  const out = [];
  const walk = (o) => {
    if (!o || typeof o !== 'object' || seen.has(o) || out.length > 500) return;
    seen.add(o);
    if (!Array.isArray(o) && o.credit && typeof o.credit === 'object' && (o.slug || o.url)) {
      out.push({ slug: o.slug || o.url, has: o.credit.has === true, stock: o.stock });
    }
    for (const k of Object.keys(o)) walk(o[k]);
  };
  walk(window.__NUXT__);
  return [...new Map(out.map(p => [p.slug, p])).values()]
           .filter(p => p.has && Number(p.stock) > 0)
           .map(p => p.slug);
}
"""


def _has_credit(page, product_url: str) -> bool:
    try:
        page.goto(product_url, wait_until="domcontentloaded", timeout=60_000)
        return bool(page.evaluate(_PDP_CREDIT_JS))
    except Exception:
        return False


@pytest.fixture(scope="session")
def credit_product(browser, base_url) -> str:
    """URL товара, доступного в кредит (есть `button.btn__credit`)."""
    ctx = browser.new_context(base_url=base_url, ignore_https_errors=True)
    page = ctx.new_page()
    try:
        for url in _CREDIT_CANDIDATES:
            if _has_credit(page, url):
                return url

        for category in _CREDIT_CATEGORY_FALLBACKS:
            try:
                page.goto(category, wait_until="domcontentloaded", timeout=60_000)
                slugs = page.evaluate(_CATEGORY_CREDIT_JS)
            except Exception:
                continue
            for slug in slugs:
                url = slug if slug.startswith("/") else f"/ru/product/{slug}"
                if _has_credit(page, url):
                    return url

        raise RuntimeError(
            "Не нашли ни одного товара с доступным кредитом "
            "(credit.has) ни среди кандидатов, ни в категориях"
        )
    finally:
        ctx.close()


# ---------------------------------------------------------------------------
# Глобально гасим оверлеи, которые перехватывают клики и валят тесты.
# На каждой загрузке странички инжектим CSS и MutationObserver, который убивает
# такие элементы по мере появления.
#
# 1. `[class*="b24-widget"]` — виджет Bitrix24, ловит клики по хедеру/футеру.
# 2. `.ecom-modal` — промо-попап «До 10% скидки» (`position: fixed`, z-index 100).
#    Появляется НЕ на каждой загрузке и через какое-то время уходит сам, поэтому
#    ломает прогон недетерминированно: Playwright пишет
#    «<div class="ecom-modal__body"> … intercepts pointer events» и клик уходит
#    в таймаут. Наблюдалось вживую 2026-07-30 на карточке товара и на предзаказе.
#    Отдельными тестами промо-попап не покрыт — гасим целиком.
# ---------------------------------------------------------------------------
_OVERLAY_SELECTORS = '[class*="b24-widget"], .ecom-modal'

_HIDE_OVERLAYS_SCRIPT = """
(() => {
  const SEL = '%s';
  const style = document.createElement('style');
  style.textContent = SEL + ' { display: none !important; visibility: hidden !important; pointer-events: none !important; }';
  (document.head || document.documentElement).appendChild(style);
  const kill = () => document.querySelectorAll(SEL).forEach(el => el.remove());
  kill();
  new MutationObserver(kill).observe(document.documentElement, { childList: true, subtree: true });
})();
""" % _OVERLAY_SELECTORS


@pytest.fixture(autouse=True)
def _suppress_overlays(page):
    page.add_init_script(_HIDE_OVERLAYS_SCRIPT)
    yield


# ---------------------------------------------------------------------------
# Устойчивость к тормозам stage. Под нагрузкой сервер отвечает медленно, и
# стандартные таймауты Playwright (действия 30s, expect 5s) дают ложные
# TimeoutError на стабильных тестах. Поднимаем дефолты — это ТОЛЬКО добавляет
# запас: проходящий тест остаётся быстрым (поллинг завершается сразу), а
# медленный ответ сервера успевает дойти, а не падает по таймауту.
# STAGE_SLOW=1 удваивает запас, когда stage совсем залипает.
# ---------------------------------------------------------------------------
_ACTION_TIMEOUT_MS = 45_000
_NAV_TIMEOUT_MS = 60_000
_EXPECT_TIMEOUT_MS = 15_000


@pytest.fixture(autouse=True)
def _resilient_timeouts(page):
    slow = os.getenv("STAGE_SLOW") == "1"
    mult = 2 if slow else 1
    page.set_default_timeout(_ACTION_TIMEOUT_MS * mult)
    page.set_default_navigation_timeout(_NAV_TIMEOUT_MS * mult)
    try:
        from playwright.sync_api import expect

        expect.set_options(timeout=_EXPECT_TIMEOUT_MS * mult)
    except Exception:
        # На старых версиях expect.set_options может отсутствовать — не критично.
        pass
    yield


# ---------------------------------------------------------------------------
# Учётки тестовых пользователей.
#
# tests/fixtures/users.json содержит реальные учётки stage и потому лежит в
# .gitignore — на свежей машине сразу после `git clone` его НЕТ. Раньше тесты
# кабинета читали файл на уровне модуля (`json.loads(...)` рядом с импортами),
# и его отсутствие давало не скип, а ОШИБКУ СБОРА: pytest падал на импорте
# tests/account/*, так и не добравшись до остальных файлов суиты.
#
# Теперь недостающий (или ещё не заполненный) файл подменяется шаблоном
# users.example.json, а тесты, которым нужен реальный вход, помечаются скипом
# с инструкцией. Смысл: свежий клон собирается и гоняет всё, что не требует
# учёток, а причина скипа видна в отчёте вместо красной ошибки импорта.
#
# Плейсхолдеры ловим отдельно: CI-шаг «Provision test credentials» при пустом
# секрете USERS_JSON копирует example в users.json — файл есть, но пароли в нём
# фиктивные. Без этой проверки такие прогоны давали бы ложные падения логина.
# ---------------------------------------------------------------------------
_FIXTURES_DIR = Path(__file__).parent / "tests" / "fixtures"
_USERS_FILE = _FIXTURES_DIR / "users.json"
_USERS_EXAMPLE = _FIXTURES_DIR / "users.example.json"
_PLACEHOLDER = "REPLACE_ME"

_SETUP_HINT = (
    "скопируй tests/fixtures/users.example.json в tests/fixtures/users.json "
    "и впиши реальные учётки stage (файл в .gitignore, в репозиторий не попадает)"
)


def _has_placeholders(users: dict) -> bool:
    return any(
        value == _PLACEHOLDER
        for section in users.values()
        if isinstance(section, dict)
        for value in section.values()
    )


def load_users() -> tuple[dict, str | None]:
    """Вернуть учётки и причину скипа.

    Причина — None, когда файл на месте и заполнен; иначе строка для
    `pytest.mark.skipif`. Словарь возвращается в любом случае, чтобы модуль
    импортировался и обращения к `USERS[...]` на уровне модуля не падали.
    """
    if not _USERS_FILE.exists():
        example = json.loads(_USERS_EXAMPLE.read_text(encoding="utf-8"))
        return example, f"нет tests/fixtures/users.json — {_SETUP_HINT}"

    users = json.loads(_USERS_FILE.read_text(encoding="utf-8"))
    if _has_placeholders(users):
        return users, f"в users.json остались значения {_PLACEHOLDER} — {_SETUP_HINT}"
    return users, None


# ---------------------------------------------------------------------------
# Вход в кабинет через поп-ап авторизации.
#
# Логин был скопирован в каждый файл кабинета отдельно. Тесты смены пароля
# логинятся ТРИЖДЫ (старым паролем, новым, и ещё раз при восстановлении), так
# что копия номер четыре превратилась бы в четыре места, где чинить один и тот
# же селектор шапки. Держим здесь, рядом с `load_users`.
# ---------------------------------------------------------------------------
AUTH_MODAL = ".modal__authentification__ecom-content"
BTN_HEADER_AUTH = ".btn__action.btn__auth"
EMAIL_INPUT = 'input[placeholder="Введи e-mail адрес"]'

# Итог попытки входа. Ждём НЕ только успех: при неверном пароле форма показывает
# «Неверный логин или пароль», и если ждать только смены шапки — хелпер честно
# висит до таймаута. А тестам смены пароля неудачный вход нужен как ОЖИДАЕМЫЙ
# результат (проверяем, что старый пароль отвалился), и он должен быть быстрым.
# Кнопка шапки: «Войти» у гостя, «Кабинет» у авторизованного.
_LOGIN_RESULT_JS = """
() => {
  const b = document.querySelector('%s');
  if (b && /Кабинет|Cabinet/i.test(b.innerText)) return 'ok';
  const e = document.querySelector('%s-form-error');
  if (e && e.offsetParent !== null && e.innerText.trim()) return 'error';
  return null;
}
""" % (BTN_HEADER_AUTH, AUTH_MODAL)


def goto_resilient(page, path: str) -> None:
    """Навигация с повтором на ERR_ABORTED.

    `/ru` отдаёт клиентский редирект на `/`, и если он случается, пока
    Playwright ещё ждёт `domcontentloaded`, прилетает net::ERR_ABORTED —
    навигация не «упала», её просто перебила следующая. Это же ловили и тесты
    истории заказов после логина. Повторяем вместо того, чтобы отдавать тесту
    ложное падение на ровном месте.
    """
    for attempt in range(3):
        try:
            page.goto(path, wait_until="domcontentloaded", timeout=60_000)
            return
        except Exception as exc:
            if "ERR_ABORTED" in str(exc) and attempt < 2:
                page.wait_for_timeout(1_500)
                continue
            raise


def open_auth_modal(page):
    """Открыть поп-ап авторизации из шапки и вернуть его локатор.

    Кликаем с повтором: первый клик по шапке после гидрации регулярно теряется
    (подробности — в блоке про гидрацию выше).
    """
    page.locator(BTN_HEADER_AUTH).wait_for(state="visible", timeout=15_000)
    modal = page.locator(AUTH_MODAL).first
    for _ in range(3):
        page.locator(BTN_HEADER_AUTH).click(force=True)
        try:
            modal.wait_for(state="visible", timeout=5_000)
            return modal
        except Exception:
            continue
    modal.wait_for(state="visible", timeout=5_000)
    return modal


def login_via_popup(page, email: str, password: str) -> bool:
    """Войти в кабинет. Возвращает True при успехе, False — если вход не прошёл.

    Именно bool, а не исключение: тестам смены пароля нужно УТВЕРЖДАТЬ, что
    старый пароль больше не подходит, и восстанавливать учётку, подбирая
    рабочий пароль. Падение внутри хелпера там только мешает.
    """
    goto_resilient(page, "/ru")
    modal = open_auth_modal(page)

    page.locator(EMAIL_INPUT).first.fill(email)
    modal.locator('input[type="password"]').first.fill(password)
    modal.locator('button[type="submit"]').first.click()

    try:
        outcome = page.wait_for_function(_LOGIN_RESULT_JS, timeout=20_000).json_value()
    except Exception:
        return False
    if outcome != "ok":
        return False

    # Успешный логин перезагружает страницу — шапка гидрируется заново, и клик
    # по «Кабинет» сразу после входа теряется без этого ожидания.
    wait_hydrated(page)
    return True


def open_account_page(page, path: str = "/ru/account") -> None:
    """Открыть раздел кабинета прямой ссылкой.

    Через меню «Кабинет» надёжнее не выходит: выпадашка раскрывается по клику,
    а первый клик по шапке после гидрации регулярно теряется — пункт «Личные
    данные» так и не всплывает, и тест падает не на проверке, а на попытке до
    него докликаться (проверено: 4 из 4 тестов удаления аккаунта отвалились
    именно здесь). Прямая навигация проверяет то же самое — раздел доступен
    авторизованному — но без гонки.

    Сразу после логина приложение делает собственный редирект, и `goto` в этот
    момент прилетает ERR_ABORTED — его гасит `goto_resilient`.
    """
    goto_resilient(page, path)


def logout(page) -> None:
    """Выйти из аккаунта через меню «Кабинет».

    Если пункт «Выйти» почему-то недоступен, сносим сессию принудительно:
    задача хелпера — гарантированно оставить браузер гостем, а не проверять
    сам логаут (это отдельный кейс).
    """
    try:
        goto_resilient(page, "/ru")
        page.locator(BTN_HEADER_AUTH).click()
        page.get_by_role("button", name="Выйти", exact=True).click(timeout=10_000)
        page.wait_for_function(
            "() => { const b = document.querySelector('%s');"
            " return !!b && !/Кабинет|Cabinet/i.test(b.innerText); }"
            % BTN_HEADER_AUTH,
            timeout=15_000,
        )
        return
    except Exception:
        pass

    page.context.clear_cookies()
    try:
        page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
    except Exception:
        pass
    goto_resilient(page, "/ru")


# ---------------------------------------------------------------------------
# Отчётность (терминальная сводка, HTML, сводка для GitHub Actions) вынесена
# в reporting.py: здесь — поведение тестов, там — представление результатов.
# ---------------------------------------------------------------------------
pytest_plugins = ("reporting",)

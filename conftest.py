import json
import os
import time
from pathlib import Path

import pytest

from admin_orders import admin_login, read_order


# ---------------------------------------------------------------------------
# Мобильная версия — отдельный прогон.
#
# tests/mobile/ гоняется в эмуляции телефона (см. tests/mobile/conftest.py) и в
# обычный `pytest` НЕ попадает: десктопная суита и её CI остаются как были.
# Мобильные тесты собираются, только когда путь к ним передан явно:
#   pytest tests/mobile
#   pytest tests/mobile/test_catalog_menu_mobile.py -k close
# ---------------------------------------------------------------------------
_MOBILE_DIR = Path(__file__).parent / "tests" / "mobile"
# Прод (tests/prod) — так же только по явному пути: ночная суита и локальный
# `pytest` ходят на stage; прод проверяется только вручную (`pytest tests/prod`).
_PROD_DIR = Path(__file__).parent / "tests" / "prod"
_EXPLICIT_ONLY_DIRS = (_MOBILE_DIR, _PROD_DIR)


def _dir_requested(config, directory: Path) -> bool:
    base = Path(config.invocation_params.dir)
    for arg in config.args:
        target = (base / arg.split("::")[0]).resolve()
        if target == directory or directory in target.parents:
            return True
    return False


def pytest_ignore_collect(collection_path, config):
    if collection_path in _EXPLICIT_ONLY_DIRS and not _dir_requested(config, collection_path):
        return True
    return None


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

# ---------------------------------------------------------------------------
# Повтор навигации при обрыве связи со стендом.
#
# Стенд изредка «моргает» на секунду: goto падает с ERR_CONNECTION_REFUSED, а
# соседние тесты в ту же минуту проходят (прогон 32455950259, Кейс 244 — обрыв
# случился прямо в фикстуре, до единой проверки). Такое падение ничего не
# говорит о продукте, но выглядит в отчёте как настоящая ошибка и каждый раз
# требует ручного разбора. Ретраим ТОЛЬКО транспортные обрывы: 404, редиректы и
# таймауты ожидания элементов сюда не попадают и падают как раньше.
# ---------------------------------------------------------------------------
_TRANSIENT_NAV_ERRORS = (
    "ERR_CONNECTION_REFUSED",
    "ERR_CONNECTION_RESET",
    "ERR_CONNECTION_CLOSED",
    "ERR_CONNECTION_TIMED_OUT",
    "ERR_EMPTY_RESPONSE",
    "ERR_SOCKET_NOT_CONNECTED",
    "ERR_NAME_NOT_RESOLVED",
    "ERR_NETWORK_CHANGED",
)
_NAV_RETRIES = 2
_NAV_RETRY_DELAY_S = 3.0


def _is_transient_nav_error(error: Exception) -> bool:
    message = str(error)
    return any(marker in message for marker in _TRANSIENT_NAV_ERRORS)


@pytest.fixture(autouse=True)
def _hydrate_after_navigation(page):
    """Автоматически ждать гидрации после каждой полной навигации.

    Обёртка на уровне conftest, а не правка каждого теста: иначе один забытый
    `goto` возвращает ложное падение, которое выглядит как баг продукта.
    Здесь же — повтор навигации при обрыве связи со стендом.
    """

    def wrap(original, name):
        def wrapper(*args, **kwargs):
            for attempt in range(_NAV_RETRIES + 1):
                try:
                    result = original(*args, **kwargs)
                    break
                except Exception as error:
                    if attempt == _NAV_RETRIES or not _is_transient_nav_error(error):
                        raise
                    print(
                        f"[nav-retry] {name}: стенд оборвал соединение "
                        f"(попытка {attempt + 1} из {_NAV_RETRIES + 1}), "
                        f"повтор через {_NAV_RETRY_DELAY_S:.0f} с"
                    )
                    time.sleep(_NAV_RETRY_DELAY_S)
            wait_hydrated(page)
            return result

        return wrapper

    for name in _NAVIGATION_METHODS:
        setattr(page, name, wrap(getattr(page, name), name))
    yield


# ---------------------------------------------------------------------------
# Ожидание значения вместо ожидания по часам.
#
# Массовый приём в суите — «сделать действие, поспать фиксированную паузу,
# прочитать состояние»:
#
#     btn.click()
#     page.wait_for_timeout(1000)
#     sum_after = _header_cart_sum(page)
#
# Пауза подобрана под конкретный прогон и превращается в лотерею, как только
# машина занята: XHR приходит на 1.2 с, в шапке ещё ноль, тест падает на
# исправном продукте. Проверено 2026-09-02: `test_add_to_cart_updates_header_sum`
# упал и в параллельном прогоне, и в последовательном — паузы в 1000 мс не
# хватило просто так, без всякой параллели.
#
# Ждать по условию и быстрее, и надёжнее: значение обычно приезжает за ~100-300 мс
# (замер в браузере: корзина обновляется за ~75 мс), и опрос завершается сразу,
# а не досыпает остаток фиксированной паузы. Потолок берём с большим запасом —
# он тратится только когда что-то действительно сломано.
#
# Исключение не бросаем сознательно: падать должен ассерт самого теста со своим
# понятным сообщением, а не «TimeoutError» из хелпера. Тот же принцип, что у
# `_click_until` в tests/test_cart_block.py.
#
# Тот же хелпер (код один в один) лежит в невлитой ветке perf/parallel-xdist —
# при её мердже оставить одну копию.
# ---------------------------------------------------------------------------
def wait_until(page, read, done, timeout_ms: int = 15_000, poll_ms: int = 100):
    """Опрашивать `read()`, пока `done(значение)` не станет истинным.

    Возвращает последнее прочитанное значение — истёк потолок или нет.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    value = read()
    while not done(value) and time.monotonic() < deadline:
        page.wait_for_timeout(poll_ms)
        value = read()
    return value


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
# Тип корзины.
#
# stage.ecom.md — конструктор: вид корзины задаётся в админке
# (Настройки сайта → «Вид страницы Корзины») и приезжает на фронт в SSR-пейлоаде
# как `mainUiInterface.cart_button_catalog_view_type`. Виды взаимоисключающие:
#
#   default        Вид 1 — корзина поп-апом (.modal__cart), страницы /cart НЕТ
#   casadeltabaco  Вид 2 — корзина отдельной страницей /cart (.page-cart),
#                  оформление на той же странице, поп-апа НЕТ
#   farmacie       Вид 3 — персонализированный (не покрыт)
#   step_by_step   Вид 4 — пошаговый (не покрыт)
#
# Тесты НЕ переключают вид сами: это глобальная настройка, общая для всех.
# Они спрашивают, что сейчас активно, и работают с этим. Переключение — забота
# CI (отдельный шаг workflow), см. tools/cart_view.py.
# ---------------------------------------------------------------------------
CART_VIEW_POPUP = "default"
CART_VIEW_PAGE = "casadeltabaco"

CART_VIEW_JS = (
    "() => window.__NUXT__?.state?.global?.globalSettings"
    "?.mainUiInterface?.cart_button_catalog_view_type ?? null"
)


@pytest.fixture(scope="session")
def cart_view(browser, base_url) -> str:
    """Активный вид корзины. Резолвится один раз за сессию.

    Читаем с самого фронта, а не из админки: настройка кэшируется, и админка
    может показывать одно, а отдаваться другое. Источник истины — то, что
    реально приехало в браузер.
    """
    ctx = browser.new_context(base_url=base_url, ignore_https_errors=True)
    page = ctx.new_page()
    try:
        # `?dev_mode=true` обязателен: обычный /ru отдаётся из кэша, и после
        # смены вида в админке там какое-то время лежит СТАРОЕ значение.
        # Без этого детектор определял вид 1 при активном виде 2, и весь файл
        # тестов молча уходил в skip — прогон при этом выглядел успешным.
        page.goto("/ru?dev_mode=true", wait_until="domcontentloaded", timeout=60_000)
        value = page.evaluate(CART_VIEW_JS)
        if not value:
            raise RuntimeError(
                "Не удалось прочитать вид корзины из window.__NUXT__ — "
                "страница не отрисовалась или изменилась структура пейлоада"
            )
        return value
    finally:
        ctx.close()


@pytest.fixture
def require_cart_view(cart_view):
    """Пропустить тест, если активен не тот вид корзины.

    Скип, а не падение: другой вид — это конфигурация стенда, а не дефект.
    Текст пишем явно, иначе пропуск потеряется среди прочих (по этой грабле
    уже ходили — молчаливые скипы дают ложное ощущение покрытия).
    """

    def _require(expected: str, human: str) -> None:
        if cart_view != expected:
            pytest.skip(
                f"Активен вид корзины {cart_view!r}, а тест написан под "
                f"{expected!r} ({human}). Вид переключается в админке."
            )

    return _require


# ---------------------------------------------------------------------------
# Динамический подбор товара со стоком.
# Товары на stage то и дело уходят в «Предзаказ» (нет стока) — тогда чекаут
# непроходим и фикстуры корзины/чекаута падают. Чтобы не залипать на одном
# хардкоженном товаре, ищем доступный: сначала среди кандидатов, потом — из
# категории. Резолвится один раз за сессию и переиспользуется всеми тестами.
# ---------------------------------------------------------------------------
_PRODUCT_CANDIDATES = [
    # Подтверждён юзером 2026-08-18: остаток 150 штук. Держим первым, чтобы
    # фикстура не перебирала кандидатов и чтобы тесты, расходующие сток
    # (оформление заказа), не выбивали товар из-под остальных.
    "/ru/product/jbl-partybox-club-120",
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
# На каждой загрузке странички инжектим CSS, который прячет такие элементы и
# делает их некликабельными (из DOM не удаляем — почему, см. ниже).
#
# 1. `[class*="b24-widget"]` — виджет Bitrix24, ловит клики по хедеру/футеру.
# 2. `.ecom-modal` — промо-попап «До 10% скидки» (`position: fixed`, z-index 100).
#    Появляется НЕ на каждой загрузке и через какое-то время уходит сам, поэтому
#    ломает прогон недетерминированно: Playwright пишет
#    «<div class="ecom-modal__body"> … intercepts pointer events» и клик уходит
#    в таймаут. Наблюдалось вживую 2026-07-30 на карточке товара и на предзаказе.
#    Отдельными тестами промо-попап не покрыт — гасим целиком.
# 3. `.cookie-banner` — баннер согласия на cookie. Сам баннер на стенде давно,
#    но БЛОКИРУЮЩИМ он стал в ночь на 2026-08-21, и это доказуемо: прогон
#    32104493897 (18-го) весь зелёный, в 32338373909 (20-го) эти тесты прошли,
#    а сегодня они падают 6 из 6 локально на том же коде тестов (диффа между
#    `1e5a0b7` и `1c9ffb7` в этих кейсах нет). Замерено сегодня: баннер виден
#    через 0.9 с после загрузки и НЕ уходит сам — ни от скролла, ни от клика,
#    ни при переходе. Раньше он так себя не вёл, иначе зелёных прогонов бы не
#    было. Это `position: fixed; bottom: 0` во всю
#    ширину и высотой ~78px, то есть он накрывает ровно ту полосу, где живут
#    кнопки фиксированного сайдбара корзины и оформления заказа: замер на живом
#    stage — кнопка «Оформить заказ»/«Продолжить покупки» занимает y 789…849,
#    баннер — y 811…873, центр кнопки внутри баннера. Playwright честно пишет
#    «<div class="cookie-banner__inner"> … intercepts pointer events».
#    Согласие живёт в localStorage, а каждый тест в CI стартует с чистым
#    контекстом — поэтому баннер показывается в КАЖДОМ тесте, а не изредка.
#    Гасим так же, как остальные оверлеи: сам баннер тестами не покрыт.
# ---------------------------------------------------------------------------
_OVERLAY_SELECTORS = '[class*="b24-widget"], .ecom-modal, .cookie-banner'

# ВАЖНО про момент запуска. `add_init_script` выполняется на document-start, а
# там `document.documentElement` ещё NULL: разметку парсер создаст позже.
# Прежняя версия скрипта сразу делала `(document.head || document.documentElement)
# .appendChild(...)` и падала с «TypeError: Cannot read properties of null» —
# то есть весь блок подавления МОЛЧА не работал ни разу (проверено 2026-08-21:
# добавленный в скрипт флаг `window.__killerRan` до страницы не доживал).
# Тесты это не замечали, потому что b24 и промо-попап всплывают редко, а в
# чекауте виджет и без того сносится вручную (`_hide_b24_widget`). Постоянный
# cookie-баннер разницу и вскрыл.
# Поэтому ставим перехват, как только появится корень документа.
#
# ТОЛЬКО прячем через CSS, из DOM НЕ удаляем. До 09.10.2026 скрипт ещё и делал
# `el.remove()` — и ломал Vue: cookie-баннер это узел, которым управляет Vue, и
# после его выдёргивания приложение переставало дорисовывать часть компонентов.
# Наблюдаемо: в мобильном поп-апе фильтров поля цены не появлялись вовсе (на
# их месте пустые `<!---->`), прайс-тесты уходили в ложный skip «нет полей
# ценового фильтра» в каждом прогоне. Замер под Pixel 7: с remove() полей 0
# из 3 загрузок, только CSS — поля есть каждый раз. Чтобы клики проходили,
# хватает `display: none` + `pointer-events: none`. Наблюдатель лишь
# возвращает наш <style>, если Nuxt перепишет <head>.
_HIDE_OVERLAYS_SCRIPT = """
(() => {
  const SEL = '%s';
  let installed = false;
  const install = () => {
    if (installed || !document.documentElement) return;
    installed = true;
    const style = document.createElement('style');
    style.textContent = SEL + ' { display: none !important; visibility: hidden !important; pointer-events: none !important; }';
    const attach = () => {
      if (!style.isConnected) (document.head || document.documentElement).appendChild(style);
    };
    attach();
    new MutationObserver(attach).observe(document.documentElement, { childList: true, subtree: true });
  };
  install();
  if (!installed) {
    const timer = setInterval(() => {
      install();
      if (installed) clearInterval(timer);
    }, 5);
  }
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


@pytest.fixture(scope="session")
def admin_order(browser):
    """Читалка заказа из админки stage: `admin_order(226342)` → dict (admin_orders.py).

    Отдельный контекст браузера на всю сессию: вход в админку один раз, и
    страница сайта в тесте его не видит. Нет учётки adminUser — скип: без
    админки сверять не с чем, а заказ на сайте тест уже проверил.
    """
    users, reason = load_users()
    admin = users.get("adminUser") or {}
    if reason or not admin.get("username"):
        pytest.skip(reason or f"в users.json нет adminUser — {_SETUP_HINT}")

    ctx = browser.new_context(ignore_https_errors=True)
    page = ctx.new_page()
    logged_in = False

    def read(order_id):
        nonlocal logged_in
        if not logged_in:
            admin_login(page, admin)
            logged_in = True
        return read_order(page, order_id)

    yield read
    ctx.close()


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

    Отдельная беда — гонка с самим приложением: если зайти в кабинет слишком
    быстро после входа, гард раздела ещё не видит сессию и выкидывает на
    `/?login=true` — навигация при этом ФОРМАЛЬНО успешна, `goto` не падает, и
    тест валится позже на «URL не похож на account». Ловилось в прогоне
    32441454012 на первом же тесте файла смены пароля (остальные три теста с
    той же фикстурой прошли — значит, продукт исправен, это чистая гонка).
    Поэтому проверяем результат и повторяем заход.
    """
    for _ in range(3):
        goto_resilient(page, path)
        if "login=true" not in page.url:
            return
        page.wait_for_timeout(2_000)


_LOGGED_IN_JS = (
    "() => { const b = document.querySelector('%s');"
    " return !!b && /Кабинет|Cabinet/i.test(b.innerText); }" % BTN_HEADER_AUTH
)


def _is_logged_in(page) -> bool:
    """Шапка показывает «Кабинет» — значит, сессия есть."""
    try:
        return bool(page.evaluate(_LOGGED_IN_JS))
    except Exception:
        return False


def _logout_via_header_menu(page) -> bool:
    """Выйти через меню «Кабинет» на текущей странице. True — вышли."""
    try:
        page.locator(BTN_HEADER_AUTH).click()
        page.get_by_role("button", name="Выйти", exact=True).click(timeout=10_000)
        page.wait_for_function(f"() => !({_LOGGED_IN_JS})()", timeout=15_000)
        return True
    except Exception:
        return False


def logout(page) -> None:
    """Выйти из аккаунта через меню «Кабинет».

    Если пункт «Выйти» почему-то недоступен, сносим сессию принудительно:
    задача хелпера — гарантированно оставить браузер гостем, а не проверять
    сам логаут (это отдельный кейс).

    Главную открываем, только если без этого никак: у авторизованного она
    грузится 6-7 с против 2 с у гостя (замер 21.09.2026), а шапка с меню
    «Кабинет» есть на любой странице сайта. Поэтому сперва пробуем выйти прямо
    с текущей страницы — тесты зовут logout из кабинета, где приложение давно
    гидрировано и клик по шапке не теряется.
    """
    if _is_logged_in(page) and _logout_via_header_menu(page):
        return

    try:
        goto_resilient(page, "/ru")
        wait_hydrated(page)
        if not _is_logged_in(page):
            return  # уже гость — ждать пункт «Выйти» незачем
        if _logout_via_header_menu(page):
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

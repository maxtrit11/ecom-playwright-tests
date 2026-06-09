import sys

import pytest


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "viewport": {"width": 1920, "height": 1080},
        "ignore_https_errors": True,
    }


# ---------------------------------------------------------------------------
# Динамический подбор товара со стоком.
# Товары на stage то и дело уходят в «Предзаказ» (нет стока) — тогда кнопка
# «В корзину» (`button.btn__add_cart`) задизейблена и фикстуры корзины/чекаута
# не открывают форму. Чтобы не залипать на одном хардкоженном товаре, ищем
# доступный: сначала среди кандидатов, потом — первый подходящий из категории.
# Резолвится один раз за сессию и переиспользуется всеми тестами.
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

_ADD_TO_CART = "button.btn__add_cart"
_HEADER_CART_BTN = 'button.btn__action.btn__cart[title="Корзина"]'
_CART_MODAL_SHOWN = ".modal__cart.show"
_BTN_CLEAR_ALL = "button.cart-products__header__clear-btn"
_BTN_CART_CLOSE = '.modal__cart button.btn__close[title="Закрыть корзину"]'
# При нулевом остатке корзина помечает товар этими классами, а кнопки
# «Следующий шаг»/«Оформить заказ» остаются disabled (проверено через MCP).
_STOCK_ERROR = ".cart__error-stock, .cart__product--out-of-stock"


def _reset_cart(page):
    """Обнулить анонимную корзину между проверками кандидатов."""
    try:
        page.evaluate(
            """() => {
                ['cart-data','cart-version','cart-owner-token'].forEach(k => {
                    try { localStorage.removeItem(k); } catch (e) {}
                });
                ['cart','cart-owner-token'].forEach(n => {
                    document.cookie = n + '=; path=/; max-age=0';
                });
            }"""
        )
    except Exception:
        pass


def _has_stock(page, product_url: str) -> bool:
    """Проверить, что товар РЕАЛЬНО доступен к заказу.

    ВНИМАНИЕ (подтверждено через MCP на живом stage): кнопка «В корзину» на PDP
    остаётся активной даже при нулевом остатке — одной её НЕДОСТАТОЧНО. Реальный
    сток подтверждаем добавлением в корзину: при стоке 0 корзина рисует
    `.cart__error-stock` / `.cart__product--out-of-stock`, а кнопка «Следующий шаг»
    остаётся disabled (и весь чекаут/сабмит-сценарий становится непроходимым).
    """
    _reset_cart(page)
    try:
        page.goto(product_url, wait_until="domcontentloaded", timeout=60_000)
    except Exception:
        return False
    try:
        page.wait_for_selector(_ADD_TO_CART, timeout=8_000)
    except Exception:
        return False
    btn = page.locator(_ADD_TO_CART).first
    try:
        # is_enabled() падает на этой разметке («не button»), поэтому проверяем
        # атрибут disabled напрямую + что это именно кнопка «В корзину».
        looks_available = (
            btn.is_visible()
            and btn.get_attribute("disabled") is None
            and "корзин" in (btn.inner_text() or "").lower()
        )
    except Exception:
        return False
    if not looks_available:
        return False

    # Подтверждаем реальный остаток через корзину.
    try:
        page.evaluate(
            """() => document.querySelectorAll('[class*="b24-widget"]').forEach(el => el.remove())"""
        )
        btn.click()
        page.wait_for_timeout(800)
        page.locator(_HEADER_CART_BTN).click()
        page.wait_for_selector(_CART_MODAL_SHOWN, timeout=10_000)
        page.wait_for_timeout(600)
        in_stock = page.locator(_STOCK_ERROR).count() == 0
    except Exception:
        return False
    finally:
        # Чистим корзину, чтобы следующий кандидат стартовал «с нуля».
        try:
            if page.locator(_BTN_CLEAR_ALL).count() > 0:
                page.locator(_BTN_CLEAR_ALL).first.click()
                page.wait_for_timeout(500)
            page.locator(_BTN_CART_CLOSE).click()
            page.wait_for_timeout(300)
        except Exception:
            pass
    return in_stock


def _resolve_in_stock_products(page, count: int) -> list[str]:
    """Вернуть до `count` различных URL товаров со стоком."""
    found: list[str] = []

    def _try(url: str):
        url = url.split("?")[0]
        if url not in found and _has_stock(page, url):
            found.append(url)

    for url in _PRODUCT_CANDIDATES:
        _try(url)
        if len(found) >= count:
            return found

    for category in _CATEGORY_FALLBACKS:
        try:
            page.goto(category, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(2_500)
        except Exception:
            continue
        hrefs = page.eval_on_selector_all(
            'a[href*="/product/"]',
            "els => [...new Set(els.map(a => a.getAttribute('href').split('?')[0]))]",
        )
        for href in hrefs:
            _try(href)
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
# Глобально гасим виджет Bitrix24 — он перехватывает клики по элементам
# хедера/футера и валит тесты. На каждой загрузке странички инжектим CSS
# и MutationObserver, который убивает любые [class*="b24-widget"].
# ---------------------------------------------------------------------------
_HIDE_B24_SCRIPT = """
(() => {
  const style = document.createElement('style');
  style.textContent = `[class*="b24-widget"] { display: none !important; visibility: hidden !important; pointer-events: none !important; }`;
  (document.head || document.documentElement).appendChild(style);
  const kill = () => document.querySelectorAll('[class*="b24-widget"]').forEach(el => el.remove());
  kill();
  new MutationObserver(kill).observe(document.documentElement, { childList: true, subtree: true });
})();
"""


@pytest.fixture(autouse=True)
def _suppress_b24_widget(page):
    page.add_init_script(_HIDE_B24_SCRIPT)
    yield


# ---------------------------------------------------------------------------
# Сводный отчёт по тест-кейсам в конце прогона
# ---------------------------------------------------------------------------
_results: list[dict] = []


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Собираем время и статус каждого теста (на фазе call)."""
    outcome = yield
    report = outcome.get_result()
    if report.when != "call":
        return
    _results.append(
        {
            "nodeid": report.nodeid,
            "name": item.name,
            "outcome": report.outcome,  # passed / failed / skipped
            "duration": report.duration,
        }
    )


def _supports_unicode() -> bool:
    """Поддерживает ли stdout эмодзи (utf-8/utf-16)."""
    enc = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in enc


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Печатаем красивую таблицу с результатами в конце прогона."""
    if not _results:
        return

    tr = terminalreporter
    unicode_ok = _supports_unicode()
    title = "Сводка по тест-кейсам" if unicode_ok else "Test cases summary"
    tr.write_sep("=", title, bold=True)

    name_width = max(len(r["name"]) for r in _results)
    name_width = max(name_width, 30)

    if unicode_ok:
        icons = {"passed": "✅", "failed": "❌", "skipped": "⏭"}
    else:
        icons = {"passed": "[OK]", "failed": "[FAIL]", "skipped": "[SKIP]"}

    for i, r in enumerate(_results, 1):
        icon = icons.get(r["outcome"], "?")
        tr.write_line(
            f"{i:>2}. {icon} {r['name']:<{name_width}}  "
            f"{r['duration']:>6.2f}s  ({r['outcome']})"
        )

    total = sum(r["duration"] for r in _results)
    passed = sum(1 for r in _results if r["outcome"] == "passed")
    failed = sum(1 for r in _results if r["outcome"] == "failed")
    skipped = sum(1 for r in _results if r["outcome"] == "skipped")
    tr.write_sep("-")
    if unicode_ok:
        tr.write_line(
            f"   Итого: {len(_results)} тестов за {total:.2f}s — "
            f"{passed} {icons['passed']} / {failed} {icons['failed']} / "
            f"{skipped} {icons['skipped']}"
        )
    else:
        tr.write_line(
            f"   Total: {len(_results)} tests in {total:.2f}s -- "
            f"{passed} {icons['passed']} / {failed} {icons['failed']} / "
            f"{skipped} {icons['skipped']}"
        )

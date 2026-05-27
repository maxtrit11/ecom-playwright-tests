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

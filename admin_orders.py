"""Заказ глазами админки stage: прочитать то, что реально сохранилось.

Попап «Заказ оформлен» доказывает только, что фронт получил ответ. Что в базу
легли правильный товар, сумма, телефон и доставка, видно лишь в админке —
её и читаем. Номер из попапа = ID заказа в админке (проверено 13.10.2026:
заказ 226342), поэтому идём сразу на карточку, без поиска по списку.

Только чтение: форму заказа не сохраняем — это изменило бы статус и историю.

Использование (фикстура `admin_order` в conftest.py):
    order = admin_order(226342)
    order["phone"], order["items"], order["total"] ...
    assert_order_matches(order, {...})   # сверка с тем, что ввёл покупатель
Суммы — в бани (int), как и в тестах сайта.
"""

from __future__ import annotations

import os
import re

ADMIN = os.environ.get("ADMIN_URL", "https://stage.admin.ecom.md")
ORDER_URL = ADMIN + "/ru/admin/general_products/generalorder/{id}/change/"

# Поля карточки заказа (Django admin, id = "id_" + имя поля модели).
# Строки товаров и адрес — инлайны; пустая заготовка `__prefix__` и лишняя
# пустая строка («---------») в данные не попадают.
_READ_JS = r"""() => {
  const val = id => {
    const el = document.getElementById(id);
    if (!el) return null;
    if (el.tagName === 'SELECT') {
      const o = el.options[el.selectedIndex];
      return o && o.value ? o.text.trim() : '';
    }
    return (el.value ?? '').trim();
  };
  const items = [];
  for (let i = 0; document.getElementById(`id_order_items-${i}-product`); i++) {
    const product = val(`id_order_items-${i}-product`);
    if (!product) continue;
    items.push({product,
                quantity: val(`id_order_items-${i}-quantity`),
                price: val(`id_order_items-${i}-price`)});
  }
  return {
    title: document.title,
    name: val('id_name'), phone: val('id_phone'), email: val('id_email'),
    pay_method: val('id_pay_method'), delivery_type: val('id_delivery_type'),
    delivery_cost: val('id_delivery_cost'), subtotal: val('id_subtotal'),
    total: val('id_total_price'), status: val('id_status'),
    region: val('id_Base_files-address-0-region'),
    locality: val('id_Base_files-address-0-locality'),
    address: val('id_Base_files-address-0-address_ru'),
    items,
  };
}"""


def _bani(raw: str | None) -> int | None:
    """«7029.05» / «7029,05» → 702905. Пустое поле → None."""
    if not raw:
        return None
    return round(float(raw.replace(",", ".").replace(" ", "")) * 100)


def admin_login(page, admin: dict) -> None:
    page.goto(f"{ADMIN}/ru/admin/login/", wait_until="domcontentloaded", timeout=60_000)
    page.fill("#id_username", admin["username"])
    page.fill("#id_password", admin["password"])
    page.press("#id_password", "Enter")
    page.wait_for_load_state("domcontentloaded")
    if "/login/" in page.url:
        raise RuntimeError("Вход в админку stage не удался — проверь adminUser в users.json")


def read_order(page, order_id: int | str) -> dict:
    """Карточка заказа → dict. Нет такого заказа → AssertionError с причиной."""
    page.goto(ORDER_URL.format(id=order_id), wait_until="domcontentloaded", timeout=90_000)
    if "/login/" in page.url:
        raise RuntimeError("Сессия админки истекла — вход не сохранился")
    data = page.evaluate(_READ_JS)
    # Несуществующий ID Django уводит на список с сообщением «не существует»
    assert data["name"] is not None, (
        f"Заказа {order_id} нет в админке (открылась «{data['title']}», {page.url})"
    )
    for key in ("delivery_cost", "subtotal", "total"):
        data[key] = _bani(data[key])
    for item in data["items"]:
        item["quantity"] = float(item["quantity"] or 0)
        item["price"] = _bani(item["price"])
    return data


def assert_order_matches(order: dict, expected: dict) -> None:
    """Сверить заказ из админки с тем, что ввёл покупатель и показал сайт.

    Собираем ВСЕ расхождения, а не падаем на первом: сломанный маппинг поля
    обычно задевает сразу несколько, и по одному их не разглядеть.
    Телефон в админке хранится с кодом страны (+373…), сравниваем по хвосту.
    Суммы — в бани; эталон — сводка чекаута прямо перед сабмитом.
    «Сумма» и цена строки в админке — уже СО скидкой: «Стоимость товаров» на
    сайте 7 399, скидка 369,95 → в админке 7 029,05 (13.10.2026).
    """
    s = expected["summary"]
    goods_net = s["goods"] - s["discount"]
    items = order["items"]
    checks = [
        ("Имя клиента", expected["name"], order["name"]),
        ("Почта", expected["email"], order["email"]),
        ("Метод доставки", expected["delivery_type"], order["delivery_type"]),
        ("Область", expected["region"], order["region"]),
        ("Адрес", expected["address"], order["address"]),
        ("Статус заказа", "Новый заказ", order["status"]),
        ("Строк товара", 1, len(items)),
        ("Товары со скидкой, бани", goods_net, order["subtotal"]),
        ("Доставка, бани", s["delivery"], order["delivery_cost"]),
        ("Итого, бани", s["total"], order["total"]),
    ]
    problems = [f"{what}: на сайте {want!r}, в админке {got!r}"
                for what, want, got in checks if want != got]

    # Подпись способа оплаты — из настроек магазина: у JBL «Наличные», у
    # другого тенанта на том же стенде «Наличными при доставке» (11.10.2026).
    if not (order["pay_method"] or "").startswith(expected["pay_method"]):
        problems.append(f"Способ оплаты: ожидали «{expected['pay_method']}…», "
                        f"в админке {order['pay_method']!r}")

    digits = re.sub(r"\D", "", order["phone"] or "")
    if not digits.endswith(expected["phone"]):
        problems.append(f"Телефон: введён {expected['phone']}, в админке {order['phone']!r}")

    if len(items) == 1:
        item = items[0]
        if item["quantity"] != 1:
            problems.append(f"Количество: положили 1, в админке {item['quantity']}")
        if item["price"] * item["quantity"] != goods_net:
            problems.append(f"Цена строки × кол-во = {item['price'] * item['quantity']}, "
                            f"а товары со скидкой в сводке {goods_net} (бани)")
        # В админке — название из справочника товаров, на сайте — h1; одно
        # должно содержать другое (без учёта регистра).
        a, b = item["product"].lower(), expected["product"].lower()
        if a not in b and b not in a:
            problems.append(f"Товар: на сайте «{expected['product']}», в админке «{item['product']}»")

    assert not problems, "Заказ в админке не совпадает с оформленным:\n  " + "\n  ".join(problems)

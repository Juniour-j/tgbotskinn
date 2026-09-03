# Мультиринок — чернетка

Ідея: бот стежить за скіном **на кількох ринках одразу**, показує де яка ціна,
алертить коли будь-де впаде нижче цілі.

## 1. Що дає кожен ринок

| Ринок | Фід | Ціна | Обсяг | Драбина (per-listing) | Buy-order |
|---|---|---|---|---|---|
| lis-skins | `market_export_json` | так | так | **так** (повний експорт) | ні |
| market.csgo.com | `api/v2/prices/USD.json` (277 КБ) | так | `volume` | ні | так (`class_instance` фід) |
| Skinport | `api.skinport.com/v1/items` (~1 МБ) | так | `quantity` | ні | ні |

**Глибокий сканер (`x<шт>`, `/depth`) залишається лише на lis-skins** — тільки він
віддає полистингові дані. Це не «двічі»: інші ринки дають одне число (ціна) + обсяг,
драбини в них нема. Тобто «1 глибоке джерело + N поверхневих».

## 2. Два типи стеження

### Price watch (мультиринок) — `/watch <назва> <ціна>`
- стежимо на всіх увімкнених ринках;
- алерт коли **будь-де** ціна `<= ціль`;
- `/list` показує розклад по ринках.

### Depth watch (`x<шт>`) — lis-skins only
- без змін;
- у виводі довідково: `market.csgo.com: volume 121` (просто загальна кількість, без драбини).

## 3. Проблема назв (головне)

- lis-skins — власні назви (`Sealed Dead Hand Terminal`);
- market.csgo.com + Skinport — Steam `market_hash_name`.

Для **кейсів / капсул / контейнерів** назви майже збігаються → стартуємо з них.
Для граффіті / стікерів / деяких — різняться → потрібна мапа
`item_class_id → market_hash_name` (lis-skins full export має `item_class_id`).

MVP: матч по нормалізованій назві + прапорець «на цьому ринку не знайдено».

## 4. Полінг (усе влазить у Oracle free)

| Джерело | Розмір | Період |
|---|---|---|
| lis-skins csgo.json | 4.5 МБ | 60 с (є) |
| lis-skins full | 160 МБ | 10 хв (є, для depth) |
| market.csgo.com prices | 277 КБ | 60 с |
| Skinport items | ~1 МБ | 5 хв (їх rate-limit ~8 запитів / 5 хв) |

## 5. Як виглядатиме

### Додавання
```
> Kilowatt Case 0.13

Стежу [#1]: Kilowatt Case
Ціль: <= $0.13
Зараз:  lis $0.14 · mcsgo $0.13 · skinport $0.15
Найдешевше: market.csgo.com — $0.13
```

### /list
```
#1  Kilowatt Case  —  від $0.128 (mcsgo), ціль <= $0.13  ✅ спрацював
#2  AK-47 | Redline (FT)  —  від $6.90 (skinport), ціль <= $6.50
```

### Алерт
```
Ціна досягнута — Kilowatt Case
market.csgo.com: $0.128   (volume 340)
ще:  lis $0.14 · skinport $0.15
https://market.csgo.com/...
```

### /depth 1 (як зараз, lis-skins)
```
Kilowatt Case
ціна на сайті (lis): $0.14
ціна    шт     сумарно
$0.14   3      3
$0.15   210    213
...
--- інші ринки ---
market.csgo.com $0.128 (vol 340)
skinport       $0.15  (qty 190)
```

### /compare <назва> (нова, без стеження)
```
Kilowatt Case
lis-skins       $0.14   (3 шт по флору)
market.csgo.com $0.128  (vol 340, buy $0.11)
skinport        $0.15   (qty 190)
```

## 6. Архітектура (ескіз)

```
Source (protocol):
    key: str                      # "lis" | "mcsgo" | "skinport"
    async refresh() -> bool
    price(hash_name) -> (price, qty) | None
    url(hash_name) -> str

registry = [LisSource, McsgoSource, SkinportSource]   # увімкнені в .env
poller: для кожного watch -> по всіх source.price() -> min -> порівняти з ціллю
depth:  окремо, тільки Lis (як зараз)
```

`.env`: `SOURCES=lis,mcsgo,skinport` — вимикати/вмикати без коду.

## 7. Що вирішити (обговорити з братом)

1. Алерт по «найдешевше на будь-якому ринку» чи окремі цілі на ринок?
2. Показувати `buy_order` з market.csgo.com («скуповують по $X»)?
3. Ринки за замовчуванням для нового watch — усі чи вибір?
4. Матч назв: суворо (тільки що збіглось) чи фаззі з попередженням?
5. Комісії/вивід у кожного ринку різні — рахувати «ефективну» ціну чи ні? (мабуть не в v1)
6. `/depth` для market.csgo.com/skinport — треба взагалі, якщо драбини нема?

## 8. Порядок робіт

1. Source-абстракція + **market.csgo.com**. Price watch показує lis + mcsgo.
2. **Skinport**.
3. Мапа назв для незбіжних айтемів (class_id).
4. (опц.) CSFloat — там драбина по пагінації.
5. `x<шт>` / `/depth` не чіпаємо на всіх етапах.

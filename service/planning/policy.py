"""Политика качества запроса: допустим ли автоматический сбор и с какими параметрами."""

from datetime import date, datetime, timezone

from service.planning import catalog
from service.planning.models import Plan
from service.planning.query import QueryFeatures
from service.providers import COINGECKO, EXCHANGERATE, Call, Source

HINTS_VAGUE = (
    "Укажите актив: монеты (bitcoin, ethereum) или валюты (доллар, евро, юань).",
    "Добавьте ограничение: количество (топ-10), период (за 7 дней) или дату (2026-09-01).",
    "Перечислите поля, например: name, price, change_24h.",
)
HINTS_RESTRICTED = (
    "Доступны только публичные котировки CoinGecko и exchangerate.host.",
    "Замените прогноз или рекомендацию на текущие цены или историю за период.",
    "Пример: «Собери историю bitcoin в долларах за 30 дней».",
)


def _held(source: str, reason: str, hints) -> Plan:
    return Plan(source=source, plan_steps=[], fields_to_keep=[], confidence="low").hold(reason, hints)


def evaluate(features: QueryFeatures, source: Source | None) -> Plan:
    code = source.code if source else ""
    if features.empty:
        return _held(code, "Пустой запрос.", HINTS_VAGUE)
    if features.restricted:
        return _held(code, f"Запрос невыполним: {features.restricted} не входят в публичные котировки источников.",
                     HINTS_RESTRICTED)
    if features.vague:
        return _held(code, "Запрос двусмысленный: не определены активы и критерии отбора.", HINTS_VAGUE)

    if source is EXCHANGERATE and features.crypto:
        return _held(code, "Запрос не соответствует источнику набора: exchangerate.host не содержит криптовалют.", (
            "Выберите набор с источником CoinGecko.",
            "Для этого набора запросите курсы валют: «Собери курсы доллара и евро к рублю».",
        ))
    if source is COINGECKO and not features.crypto and features.fiats:
        return _held(code, "Запрос не соответствует источнику набора: CoinGecko не содержит курсов фиатных валют.", (
            "Выберите набор с источником exchangerate.host.",
            "Для этого набора назовите монеты: «Собери цены bitcoin и ethereum в рублях».",
        ))

    if source is None:
        source = COINGECKO if features.crypto else EXCHANGERATE if features.fiats else None
    if source is None or (source is COINGECKO and not features.crypto) or (source is EXCHANGERATE and not features.fiats):
        return _held(source.code if source else "", "Запрос двусмысленный: не указаны активы для сбора.", HINTS_VAGUE)

    if source is COINGECKO:
        return _crypto_history(features) if features.history else _crypto_markets(features)
    return _fx(features)


def _quote_currencies(features: QueryFeatures, notes: list[str]) -> tuple[list[str], bool] | str:
    unsupported = [c for c in features.fiats if c not in catalog.COINGECKO_QUOTE]
    if unsupported:
        return f"CoinGecko не котирует активы в {', '.join(unsupported)}."
    if not features.fiats:
        notes.append("Валюта котировки не указана: USD.")
        return ["USD"], False
    quotes = features.fiats
    if len(quotes) > catalog.MAX_PARALLEL_CALLS:
        notes.append(f"Валюты котировки ограничены первыми {catalog.MAX_PARALLEL_CALLS}.")
        quotes = quotes[: catalog.MAX_PARALLEL_CALLS]
    return quotes, True


def _crypto_markets(f: QueryFeatures) -> Plan:
    notes: list[str] = []
    quotes = _quote_currencies(f, notes)
    if isinstance(quotes, str):
        return _held(COINGECKO.code, quotes, ("Допустимые валюты котировки: USD, EUR, RUB, CNY, GBP, JPY, TRY, AED, CHF.",))
    currencies, quote_explicit = quotes
    if f.days is not None and f.days not in (1, 7):
        return _held(COINGECKO.code,
                     "Для списка монет доступно изменение только за 24 часа и 7 дней.",
                     ("Для произвольного периода укажите монету: «Собери историю bitcoin за 30 дней».",
                      "Поля изменения: change_24h, change_7d."))
    if f.coins:
        size = len(f.coins)
    else:
        size = f.count or 10
        if f.count is None:
            notes.append("Количество не указано: топ-10.")
        elif f.count > catalog.MAX_MARKET_ITEMS:
            notes.append(f"Количество ограничено {catalog.MAX_MARKET_ITEMS}.")
            size = catalog.MAX_MARKET_ITEMS
    order = "volume_desc" if f.by_volume else "market_cap_desc"
    calls = []
    for currency in currencies:
        params = {"vs_currency": currency.lower(), "order": order, "per_page": str(max(1, size)),
                  "page": "1", "price_change_percentage": "24h,7d"}
        if f.coins:
            params["ids"] = ",".join(cid for cid, _ in f.coins)
        calls.append(Call(COINGECKO.code, "/coins/markets", params))
    scope = ", ".join(n for _, n in f.coins) if f.coins else f"топ-{size} по {'объёму' if f.by_volume else 'капитализации'}"
    steps = [f"Выборка: {scope}; валюта {', '.join(currencies)}.",
             f"Запрос CoinGecko /coins/markets: {len(calls)}."]
    constrained = f.count is not None or quote_explicit or bool(f.fields) or f.days is not None
    return _complete(COINGECKO.code, calls, catalog.MARKET_FIELDS, f, constrained, notes, steps)


def _crypto_history(f: QueryFeatures) -> Plan:
    notes: list[str] = []
    if not f.coins:
        return _held(COINGECKO.code, "Для истории цены требуется конкретная монета.",
                     ("Укажите монету: bitcoin, ethereum, toncoin.",
                      "Пример: «Собери историю bitcoin в долларах за 7 дней»."))
    if f.days is not None and f.days > catalog.MAX_HISTORY_DAYS:
        return _held(COINGECKO.code, f"Запрос невыполним: история доступна не более чем за {catalog.MAX_HISTORY_DAYS} дней.",
                     (f"Укажите период до {catalog.MAX_HISTORY_DAYS} дней.",))
    quotes = _quote_currencies(f, notes)
    if isinstance(quotes, str):
        return _held(COINGECKO.code, quotes, ("Допустимые валюты котировки: USD, EUR, RUB, CNY, GBP, JPY, TRY, AED, CHF.",))
    currencies, quote_explicit = quotes
    days = f.days
    if days is None:
        days = 7
        notes.append("Период не указан: 7 дней.")
    coins = f.coins
    if len(coins) > catalog.MAX_PARALLEL_CALLS:
        notes.append(f"Монеты ограничены первыми {catalog.MAX_PARALLEL_CALLS}.")
        coins = coins[: catalog.MAX_PARALLEL_CALLS]
    if len(currencies) > 1:
        notes.append(f"История строится в одной валюте: {currencies[0]}.")
    currency = currencies[0]
    calls = []
    for cid, name in coins:
        params = {"vs_currency": currency.lower(), "days": str(days)}
        if days >= 2:
            params["interval"] = "daily"
        calls.append(Call(COINGECKO.code, f"/coins/{cid}/market_chart", params, {"coin_name": name}))
    steps = [f"Монеты: {', '.join(n for _, n in coins)}; валюта {currency}; период {days} дн.",
             f"Запрос CoinGecko /market_chart: {len(calls)}.",
             "Агрегация точек по дням (для периода 1 день — по часам)."]
    constrained = f.days is not None or quote_explicit or bool(f.fields)
    return _complete(COINGECKO.code, calls, catalog.HISTORY_FIELDS, f, constrained, notes, steps)


def _fx(f: QueryFeatures) -> Plan:
    notes: list[str] = []
    base = f.base
    if base is None:
        base = "RUB"
        notes.append("Базовая валюта не указана: RUB.")
    targets = [c for c in f.fiats if c != base]
    if not targets:
        return _held(EXCHANGERATE.code, "Не указаны валюты для получения курса.",
                     ("Пример: «Собери курсы доллара, евро и юаня к рублю».", HINTS_VAGUE[1]))
    if f.days is not None and f.on_date is None:
        return _held(EXCHANGERATE.code,
                     "Курсы за период недоступны на тарифе exchangerate.host: допустим текущий курс или курс на дату.",
                     ("Уберите период: «Собери курсы доллара и евро к рублю».",
                      "Или укажите дату: «на дату 2026-09-01»."))
    today = datetime.now(timezone.utc).date()
    if f.on_date and f.on_date > today:
        return _held(EXCHANGERATE.code, "Запрос невыполним: дата в будущем.", ("Укажите текущую или прошедшую дату.",))
    if f.on_date and f.on_date < date(*catalog.FX_FIRST_DATE):
        return _held(EXCHANGERATE.code, "Запрос невыполним: данные доступны с 1999-01-01.", ("Укажите дату не ранее 1999-01-01.",))

    codes = sorted({base, *targets} - {"USD"}) or [base]
    params = {"source": "USD", "currencies": ",".join(codes)}
    endpoint = "/live"
    if f.on_date:
        endpoint, params = "/historical", {"date": f.on_date.isoformat(), **params}
    calls = [Call(EXCHANGERATE.code, endpoint, params, {"base": base, "targets": targets})]
    when = f"на {f.on_date.isoformat()}" if f.on_date else "текущие"
    steps = [f"Валюты: {', '.join(targets)}; база {base}; курсы {when}.",
             f"Запрос exchangerate.host {endpoint}: 1.",
             f"Расчёт кросс-курсов через USD: {base} за 1 единицу валюты."]
    constrained = f.base is not None or f.on_date is not None or bool(f.fields)
    return _complete(EXCHANGERATE.code, calls, catalog.FX_FIELDS, f, constrained, notes, steps)


def _complete(source, calls, allowed, f: QueryFeatures, constrained, notes, steps) -> Plan:
    if not constrained:
        return _held(source, "Запрос двусмысленный: нет ограничений (количество, период, дата, валюта или поля).",
                     HINTS_VAGUE)
    known = [x for x in f.fields if x in allowed]
    unknown = [x for x in f.fields if x not in allowed]
    if unknown and not known:
        return _held(source, f"Поля {', '.join(unknown)} недоступны. Допустимые поля: {', '.join(allowed)}.",
                     (f"Выберите поля из списка: {', '.join(allowed)}.",))
    if unknown:
        notes.append(f"Недоступные поля исключены: {', '.join(unknown)}.")
    confidence = "medium" if notes else "high"
    kept = known or list(allowed)
    if "price" in kept and "currency" in allowed and "currency" not in kept:
        kept.insert(kept.index("price") + 1, "currency")
        notes.append("Поле currency добавлено к price.")
    return Plan(
        source=source,
        plan_steps=[*steps, f"Сохранение полей: {', '.join(kept)}."][:5],
        fields_to_keep=kept,
        confidence=confidence,
        calls=calls,
        notes=notes,
    )

MARKET_FIELDS = ("rank", "name", "symbol", "price", "currency", "market_cap",
                 "volume_24h", "change_24h", "change_7d", "updated_at")
HISTORY_FIELDS = ("date", "coin", "currency", "price", "market_cap", "volume")
FX_FIELDS = ("date", "base", "currency", "rate")

# (id CoinGecko, отображаемое имя, шаблон распознавания)
COINS = (
    ("bitcoin", "Bitcoin", r"bitcoin|биткоин\w*|биткойн\w*|\bbtc\b"),
    ("ethereum", "Ethereum", r"ethereum|эфириум\w*|\bэфир\w*|\beth\b"),
    ("tether", "Tether", r"tether|\busdt\b"),
    ("binancecoin", "BNB", r"\bbnb\b|binance\s*coin"),
    ("solana", "Solana", r"solana|солан\w*|\bsol\b"),
    ("ripple", "XRP", r"\bxrp\b|ripple|рипл\w*"),
    ("the-open-network", "Toncoin", r"toncoin|тонкоин\w*|\bton\b|\bтон\b"),
    ("dogecoin", "Dogecoin", r"dogecoin|догикоин\w*|\bdoge\b"),
    ("cardano", "Cardano", r"cardano|кардано|\bada\b"),
    ("tron", "TRON", r"\btron\b|\btrx\b|\bтрон\b"),
    ("litecoin", "Litecoin", r"litecoin|лайткоин\w*|\bltc\b"),
)

FIATS = (
    ("USD", r"доллар\w*|\busd\b|\$"),
    ("EUR", r"\bевро\b|\beur\b|€"),
    ("RUB", r"рубл\w*|\brub\b|₽"),
    ("CNY", r"юан\w*|\bcny\b"),
    ("KZT", r"тенге|\bkzt\b"),
    ("GBP", r"фунт\w*|\bgbp\b"),
    ("JPY", r"\bиен\w*|\bйен\w*|\bjpy\b"),
    ("TRY", r"\bлир\w*|\btry\b"),
    ("AED", r"дирхам\w*|\baed\b"),
    ("CHF", r"франк\w*|\bchf\b"),
    ("BYN", r"белорусск\w*|\bbyn\b"),
)

COINGECKO_QUOTE = frozenset({"USD", "EUR", "RUB", "CNY", "GBP", "JPY", "TRY", "AED", "CHF"})

CRYPTO_TERMS = r"криптовалют\w*|крипт\w*|монет\w*|токен\w*|альткоин\w*|\bтоп\b|топ-?\s*\d+"
HISTORY_TERMS = r"истори\w*|динамик\w*|график\w*"
VOLUME_TERMS = r"объем\w*|объём\w*"

RESTRICTED = (
    ("закрыт", "закрытые данные"),
    ("приватн", "приватные данные"),
    ("секретн", "конфиденциальные данные"),
    ("инсайд", "инсайдерская информация"),
    ("конкурент", "данные третьих лиц"),
    ("ордер", "книга заявок бирж"),
    ("кошельк", "данные кошельков"),
    ("прогноз", "прогноз курса"),
    ("предскаж", "прогноз курса"),
    ("на завтра", "будущие значения"),
    ("что купить", "инвестиционная рекомендация"),
    ("выгодно купить", "инвестиционная рекомендация"),
    ("куда вложить", "инвестиционная рекомендация"),
)

VAGUE = (
    "самое важное", "самое важн", "сделай вывод", "по рынку", "покажи лучшее",
    "что-нибудь", "что нибудь", "все подряд", "что интересно", "интересное",
)

MAX_MARKET_ITEMS = 250
MAX_HISTORY_DAYS = 365
MAX_PARALLEL_CALLS = 3
FX_FIRST_DATE = (1999, 1, 1)

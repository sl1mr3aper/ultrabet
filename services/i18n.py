"""Легковесная i18n для локализации бота.

Поддерживаемые языки: ru, en, uk, kz.
По умолчанию — русский. При старте load_translations() загружает все
переводы в память. Клиент вызывает t(key, lang) для получения строки.
"""

from __future__ import annotations

from typing import Final

_TRANSLATIONS: Final[dict[str, dict[str, str]]] = {
    "ru": {
        "welcome": "Добро пожаловать в UltraBet!",
        "menu.matches": "Матчи",
        "menu.leagues": "Лиги",
        "menu.dailypicks": "Пикс дня",
        "menu.profile": "Профиль",
        "menu.settings": "Настройки",
        "menu.help": "Помощь",
        "prediction.header": "Прогноз на матч",
        "prediction.home_prob": "Победа хозяев",
        "prediction.draw_prob": "Ничья",
        "prediction.away_prob": "Победа гостей",
        "prediction.btts": "Обе забьют",
        "prediction.over_2_5": "Тотал > 2.5",
        "prediction.under_2_5": "Тотал < 2.5",
        "error.generic": "Произошла ошибка, попробуй ещё раз.",
        "error.rate_limit": "Слишком часто! Подожди немного.",
        "error.not_found": "Не найдено.",
        "error.timeout": "Сервер не ответил вовремя.",
        "value.bet": "Валуйная ставка",
        "value.pct": "Валуйность",
        "fair.odds": "Справедливый коэф",
        "market.home": "П1",
        "market.draw": "Ничья",
        "market.away": "П2",
        "subscription.expiring": "Твоя подписка скоро кончится.",
        "subscription.active": "Подписка активна до",
        "strategy.conservative": "Консервативная",
        "strategy.balanced": "Сбалансированная",
        "strategy.aggressive": "Агрессивная",
        "strategy.underdog": "Андердог",
    },
    "en": {
        "welcome": "Welcome to UltraBet!",
        "menu.matches": "Matches",
        "menu.leagues": "Leagues",
        "menu.dailypicks": "Daily picks",
        "menu.profile": "Profile",
        "menu.settings": "Settings",
        "menu.help": "Help",
        "prediction.header": "Match prediction",
        "prediction.home_prob": "Home win",
        "prediction.draw_prob": "Draw",
        "prediction.away_prob": "Away win",
        "prediction.btts": "Both teams to score",
        "prediction.over_2_5": "Total > 2.5",
        "prediction.under_2_5": "Total < 2.5",
        "error.generic": "An error occurred, please try again.",
        "error.rate_limit": "Too many requests! Please wait.",
        "error.not_found": "Not found.",
        "error.timeout": "Server didn't respond in time.",
        "value.bet": "Value bet",
        "value.pct": "Value percent",
        "fair.odds": "Fair odds",
        "market.home": "1",
        "market.draw": "X",
        "market.away": "2",
        "subscription.expiring": "Your subscription is ending soon.",
        "subscription.active": "Subscription active until",
        "strategy.conservative": "Conservative",
        "strategy.balanced": "Balanced",
        "strategy.aggressive": "Aggressive",
        "strategy.underdog": "Underdog",
    },
    "uk": {
        "welcome": "Ласкаво просимо до UltraBet!",
        "menu.matches": "Матчі",
        "menu.leagues": "Ліги",
        "menu.dailypicks": "Піки дня",
        "menu.profile": "Профіль",
        "menu.settings": "Налаштування",
        "menu.help": "Допомога",
        "prediction.header": "Прогноз на матч",
        "prediction.home_prob": "Перемога господарів",
        "prediction.draw_prob": "Нічия",
        "prediction.away_prob": "Перемога гостей",
        "prediction.btts": "Обидві заб'ють",
        "prediction.over_2_5": "Тотал > 2.5",
        "prediction.under_2_5": "Тотал < 2.5",
        "error.generic": "Сталася помилка, спробуй ще раз.",
        "error.rate_limit": "Забагато запитів! Зачекай трохи.",
        "error.not_found": "Не знайдено.",
        "error.timeout": "Сервер не відповів вчасно.",
        "value.bet": "Валуйна ставка",
        "value.pct": "Валуйність",
        "fair.odds": "Справжній коеф",
        "market.home": "П1",
        "market.draw": "Нічия",
        "market.away": "П2",
        "subscription.expiring": "Твоя підписка скоро закінчиться.",
        "subscription.active": "Підписка активна до",
        "strategy.conservative": "Консервативна",
        "strategy.balanced": "Збалансована",
        "strategy.aggressive": "Агресивна",
        "strategy.underdog": "Андердог",
    },
    "kz": {
        "welcome": "UltraBet-ке қош келдіңіз!",
        "menu.matches": "Ойындар",
        "menu.leagues": "Лигалар",
        "menu.dailypicks": "Күн таңдаулары",
        "menu.profile": "Профиль",
        "menu.settings": "Баптаулар",
        "menu.help": "Көмек",
        "prediction.header": "Матч болжамы",
        "prediction.home_prob": "Үй иелерінің жеңісі",
        "prediction.draw_prob": "Тең түсу",
        "prediction.away_prob": "Қонақтардың жеңісі",
        "prediction.btts": "Екі команда гол соғады",
        "prediction.over_2_5": "Жалпы > 2.5",
        "prediction.under_2_5": "Жалпы < 2.5",
        "error.generic": "Қате пайда болды, қайталап көріңіз.",
        "error.rate_limit": "Көп сұрау! Күте тұрыңыз.",
        "error.not_found": "Табылмады.",
        "error.timeout": "Сервер уақытында жауап бермеді.",
        "value.bet": "Валуй ставкасы",
        "value.pct": "Валуйлық",
        "fair.odds": "Нақты коэф",
        "market.home": "П1",
        "market.draw": "Тең",
        "market.away": "П2",
        "subscription.expiring": "Жазылымыңыз жақында бітеді.",
        "subscription.active": "Жазылым белсенді",
        "strategy.conservative": "Консервативті",
        "strategy.balanced": "Теңдестірілген",
        "strategy.aggressive": "Агрессивті",
        "strategy.underdog": "Күтпеген",
    },
}

DEFAULT_LANG: Final[str] = "ru"
SUPPORTED_LANGS: Final[tuple[str, ...]] = tuple(_TRANSLATIONS.keys())


def t(key: str, lang: str = DEFAULT_LANG) -> str:
    """Возвращает перевод для key на lang, с fallback на DEFAULT_LANG и key."""
    if lang not in _TRANSLATIONS:
        lang = DEFAULT_LANG
    return (
        _TRANSLATIONS[lang].get(key)
        or _TRANSLATIONS[DEFAULT_LANG].get(key)
        or key
    )


def keys_for(lang: str) -> list[str]:
    """Все доступные ключи для языка."""
    if lang not in _TRANSLATIONS:
        return []
    return sorted(_TRANSLATIONS[lang].keys())


def missing_for(lang: str) -> list[str]:
    """Ключи в DEFAULT_LANG, которых нет в переданном lang."""
    if lang not in _TRANSLATIONS:
        return []
    default = set(_TRANSLATIONS[DEFAULT_LANG].keys())
    target = set(_TRANSLATIONS[lang].keys())
    return sorted(default - target)


__all__ = ["DEFAULT_LANG", "SUPPORTED_LANGS", "keys_for", "missing_for", "t"]

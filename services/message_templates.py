"""Шаблоны сообщений бота с параметризацией.

Собирает все длинные тексты в одно место, упрощает локализацию и
поддержание единого стиля.
"""

from __future__ import annotations

from string import Template

TEMPLATES: dict[str, str] = {
    "welcome": """
👋 Привет, ${name}!

Ты в UltraBet — боте для футбольных прогнозов с детальной аналитикой.

Что я умею:
• /matches — матчи сегодня/завтра с пагинацией
• /leagues — все лиги мира
• /dailypicks — топ-5 главных прогнозов дня
• /predict <id> — прогноз на конкретный матч
• /simulate <xg1> <xg2> — Monte-Carlo симуляция
• /arb2, /arb3 — поиск арбитражей
• /parlay — калькулятор экспрессов
• /bankroll — калькулятор ставок по Келли
• /strategy — выбери стратегию прогнозов
• /profile — твой профиль и статистика
• /referral — приведи друга, получи бонусы

Твой реферальный код: `${ref_code}`
""".strip(),
    "prediction_header": """
${icon} *Прогноз на матч*
━━━━━━━━━━━━━━━━━━━━━━━

⚽ ${home} vs ${away}
🏆 ${league}
📅 ${date_time}

━━━━━━━━━━━━━━━━━━━━━━━
""".strip(),
    "prediction_body": """
📊 *Вероятности модели:*
• Победа ${home}: *${p_home}%*
• Ничья: *${p_draw}%*
• Победа ${away}: *${p_away}%*

⚽ *Голы (Poisson):*
• Обе забьют: *${btts_pct}%*
• Тотал > 2.5: *${over25_pct}%*
• Тотал < 2.5: *${under25_pct}%*
• xG ожидаемые: ${home} ${xg_home} — ${xg_away} ${away}
""".strip(),
    "value_bet_block_header": """
💎 *Валуйные ставки (по валуйности ↓):*
""".strip(),
    "value_bet_row": """
${rank}. *${market_name}* — ${book}
   вер.=${prob}% · честн.=${fair} · кф=*${odds}* · +${value}% 🔥
""".strip(),
    "subscription_offer": """
🎁 *Подписка UltraBet*

• 1 день — ${price_day}₽
• 1 неделя — ${price_week}₽
• 1 месяц — ${price_month}₽ (экономия ${save_month}%)
• 3 месяца — ${price_quarter}₽ (экономия ${save_quarter}%)
• 12 месяцев — ${price_year}₽ (экономия ${save_year}%)

Подписка снимает лимит запросов и открывает value-ставки с полными деталями.

Промокод от реферала: ${ref_code}
""".strip(),
    "subscription_active": """
✅ *Твоя подписка активна*

План: *${plan}*
Активна до: *${until}*
Осталось дней: *${days_left}*

Запросов сегодня: *${today_requests}*
Всего прогнозов получено: *${total_predictions}*
""".strip(),
    "subscription_expired": """
⚠️ *Подписка истекла*

Твоя подписка закончилась ${ended_at}.

Продли, чтобы снова получать:
• неограниченные прогнозы
• валуйные ставки с деталями
• ежедневные главные прогнозы
• live-мониторинг

Купить: /subscribe
""".strip(),
    "referral_share": """
🎯 *Реферальная программа*

Приводи друзей — получай бонусы!

• Регистрация по твоей ссылке: *+3 прогноза*
• Подписка 1 мес: *+5 прогнозов*
• Подписка 3 мес: *+15 прогнозов*
• Подписка 12 мес: *+45 прогнозов*

Твоя ссылка:
https://t.me/${bot_name}?start=${ref_code}

Приведено всего: *${total_invited}*
Получено бонусов: *${total_bonus}*
""".strip(),
    "error_rate_limit": """
🚦 Слишком много запросов!

Ты превысил лимит ${limit} запросов в минуту.
Подожди ${wait_sec} секунд и повтори.

Купи подписку, чтобы снять лимит: /subscribe
""".strip(),
    "error_generic": """
❌ Ой, что-то пошло не так.

${detail}

Попробуй через минуту. Если ошибка повторяется — напиши в поддержку.
""".strip(),
    "daily_digest_header": """
📰 *Дайджест на ${date}*
━━━━━━━━━━━━━━━━━━━━━━━
""".strip(),
    "daily_digest_footer": """
━━━━━━━━━━━━━━━━━━━━━━━
Ставок сегодня: ${total}
Средняя валуйность: ${avg_value}%

Удачных прогнозов! 🍀
""".strip(),
    "live_alert": """
🔴 *LIVE: Резкое изменение коэф*

${home} ${score_home} - ${score_away} ${away}
Минута ${minute}'

📉 *Коэф на ${market_name}:*
Было: ${old_odds} → Стало: *${new_odds}* (${delta}%)

Возможная причина: ${reason}
""".strip(),
    "match_reminder": """
⏰ Напоминание о матче

${home} vs ${away}
Начало через ${minutes_left} минут
""".strip(),
    "bet_slip_header": """
🎫 *Купон*

${events_count} событий
Общий коэф: *${total_odds}*
Комбинированная вероятность: *${combined_prob}%*
""".strip(),
    "arb_found": """
🎯 *Арбитраж найден!*

${event}

Распределение ставок (на 1000₽):
${allocation}

Гарантированная прибыль: *${profit}₽ (${profit_pct}%)*
""".strip(),
}


def render(template_key: str, **kwargs) -> str:
    raw = TEMPLATES.get(template_key)
    if raw is None:
        return f"(template '{template_key}' not found)"
    t = Template(raw)
    return t.safe_substitute(**kwargs)


def available_templates() -> list[str]:
    return sorted(TEMPLATES.keys())


def placeholders_in(template_key: str) -> list[str]:
    """Возвращает список ключей $placeholder из шаблона."""
    raw = TEMPLATES.get(template_key, "")
    t = Template(raw)
    return t.get_identifiers() if hasattr(t, "get_identifiers") else []


__all__ = ["TEMPLATES", "available_templates", "placeholders_in", "render"]

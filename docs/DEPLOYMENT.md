# Развёртывание UltraBet

## Локально (для разработки)

```bash
git clone https://github.com/sl1mr3aper/ultrabet.git
cd ultrabet
python3.11 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env  # затем заполнить TG_BOT_TOKEN
.venv/bin/python main.py
```

## Production: Systemd

`/etc/systemd/system/ultrabet.service`:

```ini
[Unit]
Description=UltraBet Telegram bot
After=network-online.target

[Service]
Type=simple
User=ultrabet
WorkingDirectory=/srv/ultrabet
EnvironmentFile=/srv/ultrabet/.env
ExecStart=/srv/ultrabet/.venv/bin/python main.py
Restart=on-failure
RestartSec=5
StandardOutput=append:/var/log/ultrabet/bot.log
StandardError=append:/var/log/ultrabet/bot.err

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now ultrabet
journalctl -u ultrabet -f
```

## Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

```bash
docker build -t ultrabet:latest .
docker run -d --name ultrabet --env-file .env ultrabet:latest
```

## Бэкапы базы

SQLite — `./ultrabet.db`. Раз в сутки скопировать:

```bash
sqlite3 ultrabet.db ".backup '/var/backups/ultrabet/$(date +%F).db'"
```

## Webhook вместо long-polling (на будущее)

```python
from aiogram.webhook.aiohttp_server import SimpleRequestHandler
# см. docs/handlers.md
```

## Мониторинг

- Логи через `loguru` → файл с ротацией.
- Метрика: количество прогнозов/час, средний latency SStats, % ошибок.
- Алерт: если `APIRateLimitError` > 5/мин → отправить уведомление админу.

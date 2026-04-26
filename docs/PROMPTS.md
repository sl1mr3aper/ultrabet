# Эталонные промпты

## Запросы пользователя

```
Реал Мадрид - Барселона
/match Реал Мадрид - Барселона
/match реал — барселона
```

Все три варианта парсятся `services.match_finder._parse_query`.

## Запросы к API SStats

### 1×2 + тоталы за день

```http
GET https://api.sstats.net/Games/list?Today=true&Limit=80&TimeZone=3
```

### Glicko для матча

```http
GET https://api.sstats.net/Games/glicko/{game_id}
```

### Прематч-коэффициенты

```http
GET https://api.sstats.net/Odds/{game_id}
```

Заголовки: `X-Api-Key`, `Accept: application/json`.

### Поиск команд

```http
GET https://api.sstats.net/Teams/list?Name=Real
```

### H2H

```http
POST https://api.sstats.net/Games/query
Content-Type: application/json

{
  "team1Id": 123,
  "team2Id": 456,
  "limit": 10
}
```

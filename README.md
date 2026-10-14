# Async Payment Processing Microservice

Асинхронный микросервис обработки платежей на FastAPI, PostgreSQL и RabbitMQ (FastStream).

## Quickstart

```bash
git clone https://github.com/yar-python/payment-service.git
```

```bash
cd payment-service
```

```bash
cp .env.example .env
```

```bash
docker compose up -d --build
```

### URL по умолчанию:


| Сервис      | URL / порт                                                           |
| ----------- | -------------------------------------------------------------------- |
| API         | [http://localhost:8000](http://localhost:8000)                       |
| Swagger     | [http://localhost:8000/docs](http://localhost:8000/docs)             |
| RabbitMQ UI | [http://localhost:15672](http://localhost:15672) (`guest` / `guest`) |
| PostgreSQL  | `localhost:5433`                                                     |




## Архитектура

- `app/domain` — статусы, ошибки, протоколы
- `app/application` — сервисы (создание платежа, обработка, публикация outbox)
- `app/api` — схемы, проверка ключа в header, маршруты
- `app/infrastructure` — PostgreSQL, RabbitMQ, эмуляция платежного шлюза, HTTP-вебхук



## Возможности



### Скрипт для генерации платежей - generate_payments.py

Скрипт создаёт платежи через API, `API_KEY` берет из `.env`. 
Требуется `httpx`. 
Если `uv`, установить с помощью:

```bash
uv venv
uv pip install httpx
```

Без `uv`, через pip:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip3 install httpx
```

Для приема вебхуков, генерируемых по умолчанию необходимо поднять webhook-сервер - описан в отдельном Compose.
Консьюмер вызывает его по имени сервиса `http://webhook-mock:9000`. 
С хоста доступен на [http://localhost:9000](http://localhost:9000).

```bash
docker compose -f docker-compose.webhook.yml up -d
```



#### Запуск сприпта генерации платежей:

```bash
uv run python scripts/generate_payments.py --count 500
```

или:

```bash
python3 scripts/generate_payments.py --count 50
```

Доступные флаги:

```bash
--webhook-url
--count
--url
--api-key
```

Webhook-сервер на каждый запрос отвечает `200` или `500`. Процент ошибок и порт задаются в блоке `environment` файла `docker-compose.webhook.yml`: `WEBHOOK_FAIL_PERCENT` (по умолчанию `10`), `WEBHOOK_PORT` — `9000`. 

Можно запустить локально вместо Compose:

```bash
python3 scripts/mock_webhook.py --fail-percent 20
```



### Несколько воркеров и консьюмеров

Запуск дополнительных реплик:

```bash
docker compose up -d --scale outbox-worker=2 --scale consumer=10
```



### Поток:

1. API в одной транзакции пишет платёж и событие `payment.created`.
2. `outbox-worker` захватывает строку (`claimed`), публикует её в `payments.new` и отмечает `published`. Если брокер не принял сообщение, строка снова становится `pending`.
3. `consumer` вызывает `charge` (обработка платежа в шлюзе): 2–5 секунд и исход 90% `succeeded`, 10% `failed`. Затем пишет `status` и `processed_at` и отправляет webhook на `webhook_url`. Повтор сообщения не вызывает `charge`, если статус уже конечный.
4. Ошибка отправки webhook повторяется в консьюмере: вторая попытка через 5 секунд, третья через 10. Если все три не удались, копия сообщения из `payments.new` записывается в `payments.dlq` вместе с текстом ошибки, и только потом исходное сообщение подтверждается. `status` и `processed_at` при этом уже сохранены.

- `POST /api/v1/payments` создаёт платёж и отвечает `202 Accepted`
- Повтор того же `Idempotency-Key` с тем же телом возвращает существующий платёж (`200`)
- Тот же ключ с другим телом отвечает `409 Conflict`
- `GET /api/v1/payments/{payment_id}` возвращает платёж
- Доступ по заголовку `X-API-Key`
- Консьюмер после обработки платежа отправляет webhook. Отправка повторяется до 3 раз с экспоненциальной задержкой. Затем сообщение уходит в DLQ
- Если вставка платежа откатилась и строки с этим ключом нет, API отвечает `500`. Тот же `Idempotency-Key` можно отправить снова



## Примеры



### Создать платёж

```bash
curl -s -X POST http://localhost:8000/api/v1/payments \
  -H "Content-Type: application/json" \
  -H "X-API-Key: lcjnb13NWVrjE-T3eDO01NsmRnii4F_WC5hlGeacxUM" \
  -H "Idempotency-Key: demo-key-001" \
  -d '{
    "amount": "1500.00",
    "currency": "RUB",
    "description": "Test payment",
    "metadata": {"order_id": "1"},
    "webhook_url": "https://webhook.site/your-unique-id"
  }'
```

Ответ (`202`):

```json
{
  "payment_id": "...",
  "status": "pending",
  "created_at": "..."
}
```

Повтор с тем же ключом и телом вернёт тот же платёж со статусом `200`. Другое тело при том же ключе вернёт `409`. Если платёж не сохранился, ответ `500`, и тот же ключ можно отправить ещё раз.

### Получить платёж

```bash
curl -s http://localhost:8000/api/v1/payments/<payment_id> \
  -H "X-API-Key: lcjnb13NWVrjE-T3eDO01NsmRnii4F_WC5hlGeacxUM"
```



## Проверки

```bash
uv run ruff check app tests
uv run ruff format --check app tests
uv run mypy app
uv run pytest
```


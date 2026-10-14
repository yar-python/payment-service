"""Create sample payments through the API.

Requires httpx.

uv run python scripts/generate_payments.py
python scripts/generate_payments.py --count 50

Every payment uses the same webhook URL. The receiver decides success or
failure on each request.
"""

import argparse
import random
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx

CURRENCIES = ("RUB", "USD", "EUR")
ROOT = Path(__file__).resolve().parents[1]


def env(key: str, default: str = "") -> str:
    path = ROOT / ".env"
    prefix = f"{key}="
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith(prefix):
                return line.split("=", 1)[1].strip()
    return default


def random_amount() -> str:
    cents = random.randint(100, 250_000_00)
    return f"{Decimal(cents) / Decimal(100):.2f}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create sample payments")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument(
        "--url",
        default=f"http://127.0.0.1:{env('API_PORT', '8000')}/api/v1/payments",
    )
    parser.add_argument("--api-key", default=env("API_KEY"))
    parser.add_argument("--webhook-url", default="http://webhook-mock:9000")
    args = parser.parse_args()
    if not args.api_key:
        raise SystemExit("API_KEY is empty in .env. Pass --api-key.")

    with httpx.Client(timeout=10) as client:
        for index in range(args.count):
            response = client.post(
                args.url,
                headers={
                    "X-API-Key": args.api_key,
                    "Idempotency-Key": str(uuid4()),
                },
                json={
                    "amount": random_amount(),
                    "currency": random.choice(CURRENCIES),
                    "description": f"Generated payment {index + 1}",
                    "metadata": {"order_id": str(index + 1)},
                    "webhook_url": args.webhook_url,
                },
            )
            body = response.json()
            print(response.status_code, body.get("payment_id", body))


if __name__ == "__main__":
    main()

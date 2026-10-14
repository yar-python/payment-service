"""Webhook receiver for local runs. Not part of the payment service.

Each request returns 200 or 500. The error percentage is WEBHOOK_FAIL_PERCENT
or --fail-percent. The port is WEBHOOK_PORT or --port.
The consumer retries three times, so a payment reaches the DLQ only when every attempt fails.

    python scripts/mock_webhook.py --fail-percent 20
"""

import argparse
import logging
import os
import random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Random webhook receiver")
    parser.add_argument(
        "--fail-percent",
        type=int,
        default=int(os.environ.get("WEBHOOK_FAIL_PERCENT", "10")),
        help="Percentage of requests answered with HTTP 500 (default: %(default)s)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("WEBHOOK_PORT", "9000")),
        help="Port for the webhook server (default: %(default)s)",
    )
    args = parser.parse_args()
    if not 0 <= args.fail_percent <= 100:
        raise SystemExit("--fail-percent must be between 0 and 100")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            if length:
                self.rfile.read(length)
            failed = random.randrange(100) < args.fail_percent
            self.send_response(500 if failed else 200)
            self.end_headers()

    logger.info("Webhook receiver on :%s, fail percent %s", args.port, args.fail_percent)
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()

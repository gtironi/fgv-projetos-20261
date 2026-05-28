"""
Simula chegada de novos pedidos no banco classicmodels.

Uso:
    python simulate_new_orders.py [--count N] [--seed S]

- Escolhe customerNumber e productCode existentes aleatoriamente.
- Insere em orders com orderDate estritamente posterior ao watermark atual
  (ou MAX(orders.orderDate), o que for maior).
- Insere ao menos uma linha em orderdetails por pedido.
- NÃO atualiza etl_watermark (responsabilidade do job Glue na Task 2).
- orderNumber calculado como MAX(orderNumber) + incremento sequencial
  (o schema do classicmodels não usa AUTO_INCREMENT nessa coluna).

Exit code: 0 = sucesso, 1 = falha.
"""

import argparse
import json
import logging
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import boto3
import mysql.connector

# Permite rodar de qualquer diretório, carregando src/.env
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import envlocal

envlocal.load()

SECRET_ARN = os.environ["SECRET_ARN"]
REGION = os.environ.get("AWS_REGION", "us-east-1")
DB_NAME = "classicmodels"
PIPELINE_NAME = "classicmodels_sales"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("simulate_new_orders")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Simula novos pedidos no classicmodels")
    p.add_argument("--count", type=int, default=5, help="Número de pedidos a criar (default: 5)")
    p.add_argument("--seed", type=int, default=None, help="Seed para reprodutibilidade")
    return p.parse_args()


def get_secret() -> dict:
    client = boto3.client("secretsmanager", region_name=REGION)
    return json.loads(client.get_secret_value(SecretId=SECRET_ARN)["SecretString"])


def connect(secret: dict):
    return mysql.connector.connect(
        host=secret["host"],
        user=secret["username"],
        password=secret["password"],
        port=int(secret["port"]),
        database=DB_NAME,
        use_pure=True,
        connection_timeout=10,
        autocommit=False,
    )


def get_watermark_date(cur) -> date | None:
    cur.execute(
        "SELECT last_processed_order_date FROM etl_watermark WHERE pipeline_name = %s",
        (PIPELINE_NAME,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def get_max_order_date(cur) -> date | None:
    cur.execute("SELECT MAX(orderDate) FROM orders")
    row = cur.fetchone()
    return row[0] if row else None


def get_baseline_date(cur) -> date:
    """Retorna a data de referência: max(watermark, MAX(orderDate))."""
    wm = get_watermark_date(cur)
    max_date = get_max_order_date(cur)

    candidates = [d for d in [wm, max_date] if d is not None]
    if not candidates:
        # banco vazio — começa de hoje
        return date.today()
    return max(candidates)


def get_customers(cur) -> list[int]:
    cur.execute("SELECT customerNumber FROM customers")
    return [row[0] for row in cur.fetchall()]


def get_products(cur) -> list[str]:
    cur.execute("SELECT productCode FROM products")
    return [row[0] for row in cur.fetchall()]


def get_product_price(cur, product_code: str) -> float:
    cur.execute("SELECT MSRP FROM products WHERE productCode = %s", (product_code,))
    row = cur.fetchone()
    return float(row[0]) if row else 10.0


def get_next_order_number(cur) -> int:
    cur.execute("SELECT MAX(orderNumber) FROM orders")
    return (cur.fetchone()[0] or 0) + 1


def simulate(conn, rng: random.Random, count: int) -> list[dict]:
    cur = conn.cursor()

    baseline = get_baseline_date(cur)
    log.info("Data de referência (baseline): %s", baseline)

    customers = get_customers(cur)
    products = get_products(cur)

    if not customers or not products:
        raise RuntimeError("Banco sem customers ou products — verifique a carga inicial")

    created = []
    next_order_number = get_next_order_number(cur)

    for i in range(count):
        order_number = next_order_number + i
        # Cada pedido avança pelo menos 1 dia em relação ao anterior
        order_date = baseline + timedelta(days=i + 1)
        customer = rng.choice(customers)
        status = "In Process"
        comments = f"Pedido simulado A2/Task1 #{i+1}"

        cur.execute(
            """
            INSERT INTO orders
                (orderNumber, orderDate, requiredDate, shippedDate, status, comments, customerNumber)
            VALUES (%s, %s, %s, NULL, %s, %s, %s)
            """,
            (
                order_number,
                order_date,
                order_date + timedelta(days=7),
                status,
                comments,
                customer,
            ),
        )

        # Pelo menos 1 linha de detalhe, aleatoriamente até 3
        num_lines = rng.randint(1, 3)
        chosen_products = rng.sample(products, min(num_lines, len(products)))
        detail_count = 0

        for line_num, product_code in enumerate(chosen_products, start=1):
            price = get_product_price(cur, product_code)
            # Pequena variação sobre o MSRP (70–100%)
            price_each = round(price * rng.uniform(0.70, 1.00), 2)
            quantity = rng.randint(1, 20)

            cur.execute(
                """
                INSERT INTO orderdetails
                    (orderNumber, productCode, quantityOrdered, priceEach, orderLineNumber)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (order_number, product_code, quantity, price_each, line_num),
            )
            detail_count += 1

        conn.commit()
        created.append(
            {
                "order_number": order_number,
                "order_date": order_date,
                "customer": customer,
                "detail_lines": detail_count,
            }
        )
        log.info(
            "  [ok] orderNumber=%d date=%s customerNumber=%d details=%d",
            order_number, order_date, customer, detail_count,
        )

    cur.close()
    return created


def print_summary(created: list[dict]) -> None:
    if not created:
        log.info("Nenhum pedido criado.")
        return

    dates = [o["order_date"] for o in created]
    total_details = sum(o["detail_lines"] for o in created)
    order_ids = [o["order_number"] for o in created]

    log.info("=" * 50)
    log.info("RESUMO")
    log.info("  Pedidos criados: %d", len(created))
    log.info("  IDs: %s", order_ids)
    log.info("  Faixa de datas: %s → %s", min(dates), max(dates))
    log.info("  Total linhas em orderdetails: %d", total_details)
    log.info("=" * 50)


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)

    conn = None
    try:
        secret = get_secret()
        conn = connect(secret)
        created = simulate(conn, rng, args.count)
        print_summary(created)
        return 0
    except Exception as exc:
        log.exception("Falha: %s", exc)
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return 1
    finally:
        if conn is not None and conn.is_connected():
            conn.close()


if __name__ == "__main__":
    sys.exit(main())

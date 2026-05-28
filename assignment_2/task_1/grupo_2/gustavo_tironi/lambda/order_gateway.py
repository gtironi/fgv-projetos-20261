"""
Lambda gateway: valida pedidos simulados antes de inserir no RDS.

Gate (em memória, antes de tocar RDS):
  - len(details) >= 1

Se passar: insere orders + orderdetails em transação. Rollback no erro.

Event esperado:
{
  "order": {
    "orderNumber": int,
    "orderDate": "YYYY-MM-DD",
    "requiredDate": "YYYY-MM-DD",
    "status": str,
    "comments": str,
    "customerNumber": int
  },
  "details": [
    {"productCode": str, "quantityOrdered": int, "priceEach": float, "orderLineNumber": int},
    ...
  ]
}

Resposta:
  {"status": "ok"|"rejected", "orderNumber": int, "errors": [str, ...]}
"""

import json
import os

import boto3
import mysql.connector

SECRET_ARN = os.environ["SECRET_ARN"]
DB_NAME = os.environ.get("DB_NAME", "classicmodels")
REGION = os.environ.get("AWS_REGION", "us-east-1")


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


def validate(event: dict) -> list[str]:
    errors = []
    details = event.get("details") or []
    if len(details) < 1:
        errors.append("orderdetails vazio: ao menos 1 linha exigida")
    return errors


def lambda_handler(event, context):
    order_number = event.get("order", {}).get("orderNumber")

    errors = validate(event)
    if errors:
        return {"status": "rejected", "orderNumber": order_number, "errors": errors}

    order = event["order"]
    details = event["details"]

    conn = None
    try:
        secret = get_secret()
        conn = connect(secret)
        cur = conn.cursor()

        cur.execute(
            """
            INSERT INTO orders
                (orderNumber, orderDate, requiredDate, shippedDate, status, comments, customerNumber)
            VALUES (%s, %s, %s, NULL, %s, %s, %s)
            """,
            (
                order["orderNumber"],
                order["orderDate"],
                order["requiredDate"],
                order["status"],
                order.get("comments"),
                order["customerNumber"],
            ),
        )

        for d in details:
            cur.execute(
                """
                INSERT INTO orderdetails
                    (orderNumber, productCode, quantityOrdered, priceEach, orderLineNumber)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    order["orderNumber"],
                    d["productCode"],
                    d["quantityOrdered"],
                    d["priceEach"],
                    d["orderLineNumber"],
                ),
            )

        conn.commit()
        cur.close()
        return {"status": "ok", "orderNumber": order_number, "errors": []}

    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return {"status": "rejected", "orderNumber": order_number, "errors": [str(exc)]}
    finally:
        if conn is not None and conn.is_connected():
            conn.close()


import os

import envlocal
import mysql.connector

envlocal.load()

# com base no script de carga
TABELAS = (
    "customers",
    "employees",
    "offices",
    "orderdetails",
    "orders",
    "payments",
    "productlines",
    "products",
)
LINHAS_ESPERADAS = {
    "customers": 122,
    "employees": 23,
    "offices": 7,
    "orderdetails": 2996,
    "orders": 326,
    "payments": 273,
    "productlines": 7,
    "products": 110,
}

conn = mysql.connector.connect(
    host=os.environ["MYSQL_HOST"],
    user=os.environ.get("MYSQL_USER", "admin"),
    password=os.environ["MYSQL_PASSWORD"],
    port=int(os.environ.get("MYSQL_PORT", "3306")),
    database=os.environ.get("MYSQL_DATABASE", "classicmodels"),
)
cur = conn.cursor()

# verificação simples de leitura (tabelas e linhas)
for t in TABELAS:
    cur.execute(f"SELECT COUNT(*) FROM `{t}`")
    n = cur.fetchone()[0]
    esp = LINHAS_ESPERADAS[t]
    assert n == esp, f"{t}: tem {n}, esperado {esp}"

cur.close()
conn.close()
print("validacao ok.")

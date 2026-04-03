import os
from pathlib import Path

import envlocal
import mysql.connector

envlocal.load()

SQL_FILE = Path(__file__).resolve().parents[3] / "data" / "mysqlsampledatabase.sql"

# conecta a base de dados relacional
conn = mysql.connector.connect(
    host=os.environ["MYSQL_HOST"],
    user=os.environ.get("MYSQL_USER", "admin"),
    password=os.environ["MYSQL_PASSWORD"],
    port=int(os.environ.get("MYSQL_PORT", "3306")),
)
cur = conn.cursor()

# carrega o script de carga
sql = SQL_FILE.read_text(encoding="utf-8", errors="replace")
for result in cur.execute(sql, multi=True):
    if result is not None and result.with_rows:
        result.fetchall()

# finalização padrão
conn.commit()
cur.close()
conn.close()
print("classicmodels carregado.")

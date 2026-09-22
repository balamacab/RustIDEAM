FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY . /app

RUN python3 -m compileall -q tools \
    && python3 - <<'PY'
import sqlite3
con = sqlite3.connect(":memory:")
try:
    con.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
finally:
    con.close()
print("sqlite_fts5=ok")
PY

VOLUME ["/app/data"]

CMD ["python3", "tools/init_db.py"]

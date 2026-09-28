FROM python:3.12-slim-bookworm AS base

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


FROM base AS case-tester

RUN python3 -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    -r requirements-case-tester.txt


FROM base AS runtime

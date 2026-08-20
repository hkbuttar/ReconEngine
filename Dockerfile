# FastAPI backend deployment image (render.yaml runs this). Installs
# Microsoft's ODBC Driver 18 for SQL Server via their official apt repo --
# a Linux container sidesteps the macOS-specific Xcode Command Line Tools
# blocker hit trying to install the same driver on the host directly
# (backend/db_client.py's docstring) -- so the pyodbc path this image
# runs IS the one actually verified end to end, not just documented.
FROM python:3.11-slim-bookworm
# Pinned to bookworm (Debian 12) explicitly, not the floating "slim" tag --
# it now resolves to trixie (Debian 13), whose stricter SHA-1 signing
# policy rejects Microsoft's Debian-12-targeted apt repo key, breaking the
# ODBC driver install below (found live, see DEPLOYMENT.md).

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg2 apt-transport-https ca-certificates \
    && curl -sSL -O https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
    && dpkg -i packages-microsoft-prod.deb \
    && rm packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev \
    && apt-get purge -y curl gnupg2 apt-transport-https \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

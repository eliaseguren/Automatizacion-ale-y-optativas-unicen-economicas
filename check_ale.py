#!/usr/bin/env python3
"""
Chequea la página de ALE/Optativas de Económicas UNICEN y notifica
(email + push via ntfy.sh) SOLO cuando aparece una actividad nueva.
Guarda el estado (códigos ya vistos) en state/known_codes.json,
que el workflow de GitHub Actions vuelve a commitear al repo.
"""

import json
import os
import re
import smtplib
import ssl
import sys
import urllib.request
from email.mime.text import MIMEText
from pathlib import Path

URL = "https://www.econ.unicen.edu.ar/alumnos/ale/ofertas-ale-y-optativas"
STATE_FILE = Path(__file__).resolve().parent.parent / "state" / "known_codes.json"

# Códigos publicados al momento de armar este watcher (17/08/2026).
# Sirve como "semilla" para que la primera corrida no dispare avisos falsos.
SEED_CODES = ["AD178", "AD179", "MO237", "TA232", "AE27", "CO256", "AD177", "AD176", "AD175", "CO255"]


def fetch_page():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (ale-watcher)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def extract_activities(html):
    """Extrae pares (codigo, titulo) del HTML de la página."""
    # Las tarjetas tienen un heading con el código (ej: "AD178") seguido
    # muy cerca por el título de la actividad.
    pattern = re.compile(
        r'([A-Z]{2,3}\d{2,4})[^<]{0,50}?</[^>]+>\s*<[^>]+>\s*([^<]{5,150})',
        re.MULTILINE,
    )
    found = {}
    for codigo, titulo in pattern.findall(html):
        titulo = titulo.strip()
        if codigo not in found and titulo:
            found[codigo] = titulo

    # Fallback: si el patrón de arriba no matchea nada (cambió el HTML),
    # al menos rescatamos los códigos sueltos para no perder la detección.
    if not found:
        for codigo in set(re.findall(r'\b([A-Z]{2,3}\d{2,4})\b', html)):
            found[codigo] = ""

    return found


def load_known():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set(SEED_CODES)


def save_known(codes):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(sorted(codes), ensure_ascii=False, indent=2))


def notify_ntfy(nuevos):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return
    mensaje = "\n".join(f"{c} - {t}" for c, t in nuevos.items())
    data = mensaje.encode("utf-8")
    req = urllib.request.Request(
        f"https://ntfy.sh/{topic}",
        data=data,
        headers={"Title": "Nueva ALE/Optativa UNICEN".encode("utf-8"), "Priority": "4"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"Error enviando ntfy: {e}", file=sys.stderr)


def notify_email(nuevos):
    host = os.environ.get("SMTP_HOST")
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    to_addr = os.environ.get("EMAIL_TO")
    port = int(os.environ.get("SMTP_PORT", "465"))
    if not all([host, user, password, to_addr]):
        return

    cuerpo = "\n\n".join(f"{c} - {t}" for c, t in nuevos.items())
    cuerpo += f"\n\nVer todas: {URL}"

    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = "Nueva actividad ALE/Optativa publicada (UNICEN)"
    msg["From"] = user
    msg["To"] = to_addr

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, context=context) as server:
        server.login(user, password)
        server.sendmail(user, [to_addr], msg.as_string())


def main():
    html = fetch_page()
    actuales = extract_activities(html)
    conocidos = load_known()

    nuevos_codigos = [c for c in actuales if c not in conocidos]

    if nuevos_codigos:
        nuevos = {c: actuales[c] for c in nuevos_codigos}
        print(f"Novedades encontradas: {nuevos}")
        notify_ntfy(nuevos)
        notify_email(nuevos)
    else:
        print("Sin novedades.")

    save_known(conocidos | set(actuales.keys()))


if __name__ == "__main__":
    main()

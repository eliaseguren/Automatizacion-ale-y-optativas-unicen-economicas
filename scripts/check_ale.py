#!/usr/bin/env python3
"""Chequea la pagina de ALE/Optativas de Economicas UNICEN y notifica
(email + push via ntfy.sh) SOLO cuando aparece una actividad nueva.
Guarda el estado (codigos ya vistos) en state/known_codes.json,
que el workflow de GitHub Actions vuelve a commitear al repo."""

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

SEED_CODES = ["AD178", "AD179", "MO237", "TA232", "AE27", "CO256", "AD177", "AD176", "AD175", "CO255"]


def env(name):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return None
    return value


def fetch_page():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 (ale-watcher)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def extract_activities(html):
    # Estructura real de la pagina: <h3>CODIGO</h3><h2>Titulo</h2>
    pattern = re.compile(r'<h3>\s*([A-Z]{2,3}\d{2,4})\s*</h3>\s*<h2>\s*(.*?)\s*</h2>', re.DOTALL)
    found = {}
    for codigo, titulo_html in pattern.findall(html):
        titulo = strip_tags(titulo_html)
        if codigo not in found and titulo:
            found[codigo] = titulo

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
    topic = env("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC no configurado, salteo notificacion push.")
        return
    mensaje = "\n".join(f"{c} - {t}" for c, t in nuevos.items())
    data = mensaje.encode("utf-8")
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=data, headers={"Title": "Nueva ALE/Optativa UNICEN", "Priority": "4"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception as e:
        print(f"Error enviando ntfy: {e}", file=sys.stderr)


def notify_email(nuevos):
    host = env("SMTP_HOST")
    user = env("SMTP_USER")
    password = env("SMTP_PASS")
    to_addr = env("EMAIL_TO")
    port_raw = env("SMTP_PORT")
    port = int(port_raw) if port_raw else 465
    if not all([host, user, password, to_addr]):
        print("Faltan credenciales de mail, salteo notificacion por email.")
        return
    cuerpo = "\n\n".join(f"{c} - {t}" for c, t in nuevos.items())
    cuerpo += f"\n\nVer todas: {URL}"
    msg = MIMEText(cuerpo, "plain", "utf-8")
    msg["Subject"] = "Nueva actividad ALE/Optativa publicada (UNICEN)"
    msg["From"] = user
    msg["To"] = to_addr
    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(host, port, context=context) as server:
            server.login(user, password)
            server.sendmail(user, [to_addr], msg.as_string())
    except Exception as e:
        print(f"Error enviando mail: {e}", file=sys.stderr)


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

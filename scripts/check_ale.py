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

# El HTML de la pagina tiene el titulo ANIDADO dentro del <h3> (mal formado en origen):
# <h3> CODIGO <h2>Titulo</h2> </h3> <span class="badge ...">Oferta ALE|Materia Optativa</span>
# Notar que el </h3> de cierre queda ENTRE el </h2> y el <span> del tipo.
ACTIVITY_PATTERN = re.compile(
    r'<h3[^>]*>\s*([A-Z]{2,3}\d{2,4})\s*<h2[^>]*>\s*(.*?)\s*</h2>'
    r'\s*(?:</h3>)?\s*(?:<span[^>]*class="[^"]*badge[^"]*"[^>]*>\s*(.*?)\s*</span>)?',
    re.DOTALL,
)


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
    found = {}
    for codigo, titulo_html, tipo_html in ACTIVITY_PATTERN.findall(html):
        titulo = strip_tags(titulo_html)
        tipo = strip_tags(tipo_html)
        if codigo not in found and titulo:
            found[codigo] = {"titulo": titulo, "tipo": tipo}
    # OJO: a proposito NO hay fallback que busque el codigo suelto en toda
    # la pagina. El HTML tiene comentarios ocultos con blobs base64 (ej. un
    # watermark de Figma) que por azar pueden contener 4 letras/numeros que
    # matchean el patron de codigo, generando falsos positivos (paso con
    # "LU21"). Preferimos no reportar nada antes que inventar actividades.
    return found


def load_known():
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set(SEED_CODES)


def save_known(codes):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(sorted(codes), ensure_ascii=False, indent=2))


def tipo_corto(tipo):
    tipo_low = (tipo or "").lower()
    if "optativa" in tipo_low:
        return "optativa"
    if "ale" in tipo_low:
        return "ALE"
    return "actividad"


def format_entry(info):
    return f"Hay una nueva {tipo_corto(info.get('tipo'))} - {info['titulo']}"


def notify_ntfy(nuevos):
    topic = env("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC no configurado, salteo notificacion push.")
        return
    mensaje = "\n\n".join(format_entry(info) for info in nuevos.values())
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
    cuerpo = "\n\n".join(format_entry(info) for info in nuevos.values())
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
    if not actuales:
        print("ADVERTENCIA: no se detecto ninguna actividad. Puede que la pagina haya cambiado de estructura.", file=sys.stderr)
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

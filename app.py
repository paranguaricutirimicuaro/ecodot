from flask import Flask, render_template, request, send_file, jsonify
import io, base64, os, tempfile, traceback

app = Flask(__name__)

# -------------------------------------------------------
# 🔥 ERROR HANDLER GLOBAL (CLAVE)
# -------------------------------------------------------
@app.errorhandler(Exception)
def handle_exception(e):
    print(traceback.format_exc())
    return jsonify({"error": str(e)}), 500


# -------------------------------------------------------
# IMPORTS
# -------------------------------------------------------
from PIL import Image, ImageDraw

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False


# -------------------------------------------------------
# BRAILLE (SIN CAMBIOS IMPORTANTES)
# -------------------------------------------------------
DPI = 96
PX_POR_MM = DPI / 25.4

DIAMETRO_PUNTO_MM = 1.8
SEPARACION_MM = 2.5
ESPACIO_ENTRE_CELDAS_MM = 6.0
ESPACIO_ENTRE_LINEAS_MM = 10.0
MARGEN_MM = 5.0

COLOR_FONDO = (255,255,255)
COLOR_PUNTO = (20,20,80)
COLOR_GUIA  = (200,210,225)

BRAILLE = {
    "a":"⠁","b":"⠃","c":"⠉","d":"⠙","e":"⠑",
    "f":"⠋","g":"⠛","h":"⠓","i":"⠊","j":"⠚",
    "k":"⠅","l":"⠇","m":"⠍","n":"⠝","o":"⠕",
    "p":"⠏","q":"⠟","r":"⠗","s":"⠎","t":"⠞",
    "u":"⠥","v":"⠧","w":"⠺","x":"⠭","y":"⠽","z":"⠵",
    " ":" "
}

def mm(v): return round(v * PX_POR_MM)

def texto_a_braille(texto):
    return "\n".join(
        "".join(BRAILLE.get(c.lower(), "?") for c in linea)
        for linea in texto.split("\n")
    )

def generar_imagen(texto_braille):
    radio = mm(DIAMETRO_PUNTO_MM / 2)
    sep = mm(SEPARACION_MM)
    paso = mm(ESPACIO_ENTRE_CELDAS_MM)
    margen = mm(MARGEN_MM)

    lineas = texto_braille.split("\n")
    ancho = margen*2 + paso * max(len(l) for l in lineas)
    alto = margen*2 + len(lineas) * paso

    img = Image.new("RGB", (ancho, alto), COLOR_FONDO)
    draw = ImageDraw.Draw(img)

    for y, linea in enumerate(lineas):
        for x, car in enumerate(linea):
            cx = margen + x * paso
            cy = margen + y * paso
            draw.ellipse([cx-radio,cy-radio,cx+radio,cy+radio], fill=COLOR_PUNTO)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


# -------------------------------------------------------
# RUTA TEXTO
# -------------------------------------------------------
@app.route("/convertir", methods=["POST"])
def convertir():
    data = request.get_json()
    texto = data.get("texto", "").strip()

    if not texto:
        return jsonify({"error": "Texto vacío"}), 400

    braille = texto_a_braille(texto)
    img = generar_imagen(braille)

    b64 = base64.b64encode(img.read()).decode()

    return jsonify({
        "braille": braille,
        "imagen": b64
    })


# -------------------------------------------------------
# MAPA (ARREGLADO)
# -------------------------------------------------------
def procesar_imagen_mapa(img_bytes, min_area=800):
    if not CV2_OK:
        raise ValueError("OpenCV no disponible")

    if not img_bytes:
        raise ValueError("Imagen vacía")

    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    if img is None:
        raise ValueError("No se pudo leer la imagen")

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    lower = np.array([40, 80, 80])
    upper = np.array([95, 255, 255])

    mask = cv2.inRange(hsv, lower, upper)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5,5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contornos, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    preview = np.zeros_like(img)

    filtrados = []
    for c in contornos:
        if cv2.contourArea(c) < min_area:
            continue
        filtrados.append(c)
        cv2.drawContours(preview, [c], -1, (0,255,0), 2)

    _, buf = cv2.imencode(".png", preview)
    b64 = base64.b64encode(buf).decode()

    return b64, img.shape[1], img.shape[0], filtrados


@app.route("/mapa/preview", methods=["POST"])
def mapa_preview():
    f = request.files.get("imagen")

    if not f:
        return jsonify({"error": "No se recibio imagen"}), 400

    try:
        min_area = int(request.form.get("min_area", 800))
    except:
        min_area = 800

    img_bytes = f.read()

    b64, w, h, contornos = procesar_imagen_mapa(img_bytes, min_area)

    return jsonify({
        "preview": b64,
        "ancho": w,
        "alto": h,
        "contornos": len(contornos)
    })


# -------------------------------------------------------
# HOME
# -------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

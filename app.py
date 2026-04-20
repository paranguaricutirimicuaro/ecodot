from flask import Flask, render_template, request, send_file, jsonify
import io
import base64
import os
import tempfile
import threading, uuid, queue as queue_mod, json as _json
import math

from PIL import Image, ImageDraw

try:
    import cadquery as cq
    CADQUERY_OK = True
except ImportError:
    CADQUERY_OK = False

try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False

app = Flask(__name__)

# -------------------------------------------------------
# CONFIG
# -------------------------------------------------------
DPI = 96
PX_POR_MM = DPI / 25.4
DIAMETRO_PUNTO_MM = 1.8
SEPARACION_MM = 2.5
ESPACIO_ENTRE_CELDAS_MM = 6.0
ESPACIO_ENTRE_LINEAS_MM = 10.0
MARGEN_MM = 5.0

BRAILLE = {
    "a":"⠁","b":"⠃","c":"⠉","d":"⠙","e":"⠑",
    "f":"⠋","g":"⠛","h":"⠓","i":"⠊","j":"⠚",
    "k":"⠅","l":"⠇","m":"⠍","n":"⠝","o":"⠕",
    "p":"⠏","q":"⠟","r":"⠗","s":"⠎","t":"⠞",
    "u":"⠥","v":"⠧","w":"⠺","x":"⠭","y":"⠽","z":"⠵",
    " ":" "
}

def texto_a_braille(texto):
    return "\n".join(
        "".join(BRAILLE.get(c, "?") for c in linea.lower())
        for linea in texto.split("\n")
    )

def ajustar_lineas(texto):
    return texto

def obtener_puntos(caracter):
    if caracter == " ":
        return []
    codigo = ord(caracter) - 0x2800
    mapa = [(0,0),(1,0),(2,0),(0,1),(1,1),(2,1)]
    return [pos for i,pos in enumerate(mapa) if codigo & (1<<i)]

# -------------------------------------------------------
# 🔥 FUNCIÓN CORREGIDA (MAPA STL)
# -------------------------------------------------------
def generar_stl_mapa_con_progreso(contornos, marcadores, leyenda_texto,
                                   ancho_px, alto_px, progress_cb,
                                   ancho_placa_mm=150, grosor_base=1.5,
                                   altura_linea=1.2, ancho_linea=1.0):

    if not CADQUERY_OK:
        return None

    MARGEN = 5.0
    SEP = SEPARACION_MM
    R_PT = DIAMETRO_PUNTO_MM / 2
    H_PT = 1.6

    escala = ancho_placa_mm / ancho_px
    alto_mapa_mm = alto_px * escala
    ancho_base = ancho_placa_mm + MARGEN * 2

    leyenda_braille = texto_a_braille(leyenda_texto) if leyenda_texto else ""
    lineas_ley = leyenda_braille.split("\n") if leyenda_braille else []

    alto_base = alto_mapa_mm + 40

    progress_cb(2, "Base...")
    modelo = cq.Workplane("XY").box(ancho_base, alto_base, grosor_base)
    cz = grosor_base / 2

    # CONTORNOS OPTIMIZADOS
    total = len(contornos)
    progress_cb(5, f"Extruyendo {total} contornos...")

    segmentos = []

    for idx, contorno in enumerate(contornos):
        pts = contorno.reshape(-1, 2)
        if len(pts) < 2:
            continue

        pts_mm = []
        for (px, py) in pts:
            x = -ancho_base/2 + MARGEN + px * escala
            y = alto_base/2 - MARGEN - py * escala
            pts_mm.append((x, y))

        if pts_mm[0] != pts_mm[-1]:
            pts_mm.append(pts_mm[0])

        for i in range(len(pts_mm)-1):
            x1, y1 = pts_mm[i]
            x2, y2 = pts_mm[i+1]

            dx = x2 - x1
            dy = y2 - y1
            lng = math.sqrt(dx*dx + dy*dy)

            if lng < 0.1:
                continue

            ang = math.degrees(math.atan2(dy, dx))

            seg = (
                cq.Workplane("XY")
                .transformed(offset=((x1+x2)/2, (y1+y2)/2, cz),
                             rotate=(0,0,ang))
                .box(lng, ancho_linea, altura_linea)
                .val()
            )

            segmentos.append(seg)

        pct = 5 + int(((idx+1)/total)*65)
        progress_cb(pct, f"Contorno {idx+1}/{total}")

    if segmentos:
        comp = cq.Compound.makeCompound(segmentos)
        modelo = modelo.union(comp)

    # EXPORT
    progress_cb(95, "Exportando...")
    tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
    tmp.close()
    cq.exporters.export(modelo, tmp.name)

    progress_cb(100, "Listo")
    return tmp.name

# -------------------------------------------------------
# JOB SYSTEM
# -------------------------------------------------------
_jobs = {}

def _worker(job_id, contornos, marcadores, leyenda, w, h):
    q = _jobs[job_id]["queue"]

    def cb(p, m):
        q.put({"pct": p, "msg": m})

    try:
        path = generar_stl_mapa_con_progreso(contornos, marcadores, leyenda, w, h, cb)
        _jobs[job_id]["stl_path"] = path
    except Exception as e:
        _jobs[job_id]["error"] = str(e)
        q.put({"pct": -1, "msg": str(e)})
    finally:
        q.put(None)

# -------------------------------------------------------
# RUTAS
# -------------------------------------------------------
@app.route("/")
def index():
    return "OK"

@app.route("/mapa/iniciar", methods=["POST"])
def iniciar():
    f = request.files.get("imagen")
    if not f:
        return jsonify({"error":"no image"}), 400

    img_bytes = f.read()
    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _,th = cv2.threshold(gray,127,255,0)
    contornos,_ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"queue": queue_mod.Queue(), "stl_path": None, "error": None}

    t = threading.Thread(target=_worker,
                         args=(job_id, contornos, [], "", img.shape[1], img.shape[0]),
                         daemon=True)
    t.start()

    return jsonify({"job_id": job_id})

@app.route("/mapa/progreso/<job_id>")
def progreso(job_id):
    q = _jobs[job_id]["queue"]

    def stream():
        while True:
            item = q.get()
            if item is None:
                yield "data: {\"done\":true}\n\n"
                break
            yield f"data: {_json.dumps(item)}\n\n"

    return app.response_class(stream(), mimetype="text/event-stream")

@app.route("/mapa/descargar/<job_id>")
def descargar(job_id):
    path = _jobs[job_id]["stl_path"]
    return send_file(path, as_attachment=True)

# -------------------------------------------------------
if __name__ == "__main__":
    app.run()
    

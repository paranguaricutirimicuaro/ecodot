from flask import Flask, render_template, request, send_file, jsonify
import io
import base64
import os
import tempfile

from PIL import Image, ImageDraw

try:
    import cadquery as cq
    CADQUERY_OK = True
except ImportError:
    CADQUERY_OK = False
print("CADQUERY_OK:", CADQUERY_OK)
app = Flask(__name__)

# -------------------------------------------------------
# MEDIDAS BRAILLE
# -------------------------------------------------------
DPI                     = 96
PX_POR_MM               = DPI / 25.4
DIAMETRO_PUNTO_MM       = 1.8
SEPARACION_MM           = 2.5
ESPACIO_ENTRE_CELDAS_MM = 6.0
ESPACIO_ENTRE_LINEAS_MM = 10.0
MARGEN_MM               = 5.0
COLOR_FONDO             = (255, 255, 255)
COLOR_PUNTO             = (20,  20,  80)
COLOR_GUIA              = (200, 210, 225)

BRAILLE = {
    "a":"⠁","b":"⠃","c":"⠉","d":"⠙","e":"⠑",
    "f":"⠋","g":"⠛","h":"⠓","i":"⠊","j":"⠚",
    "k":"⠅","l":"⠇","m":"⠍","n":"⠝","o":"⠕",
    "p":"⠏","q":"⠟","r":"⠗","s":"⠎","t":"⠞",
    "u":"⠥","v":"⠧","w":"⠺","x":"⠭","y":"⠽","z":"⠵",
    "á":"⠷","é":"⠮","í":"⠌","ó":"⠬","ú":"⠾","ü":"⠳","ñ":"⠻",
    "1":"⠁","2":"⠃","3":"⠉","4":"⠙","5":"⠑",
    "6":"⠋","7":"⠛","8":"⠓","9":"⠊","0":"⠚",
    ".":"⠲",",":"⠂",";":"⠆",":":"⠒","?":"⠦","!":"⠖",
    "-":"⠤","'":"⠄","(":"⠶",")":"⠶"," ":" ",
}

def mm(v): return round(v * PX_POR_MM)

def texto_a_braille(texto):
    lineas = texto.split("\n")
    resultado = []
    for linea in lineas:
        linea = linea.lower()
        resultado.append("".join(BRAILLE.get(c, "?") for c in linea))
    return "\n".join(resultado)

def ajustar_lineas(texto_braille):
    ancho_max_mm   = 140 - MARGEN_MM * 2
    max_caracteres = int(ancho_max_mm / ESPACIO_ENTRE_CELDAS_MM)
    lineas_finales = []
    for linea in texto_braille.split("\n"):
        if len(linea) <= max_caracteres:
            lineas_finales.append(linea)
        else:
            while len(linea) > max_caracteres:
                corte = linea.rfind(" ", 0, max_caracteres)
                if corte == -1: corte = max_caracteres
                lineas_finales.append(linea[:corte])
                linea = linea[corte:].lstrip(" ")
            if linea: lineas_finales.append(linea)
    return "\n".join(lineas_finales)

def obtener_puntos(caracter_braille):
    if caracter_braille == " ": return []
    codigo = ord(caracter_braille) - 0x2800
    mapa   = [(0,0),(1,0),(2,0),(0,1),(1,1),(2,1)]
    return [pos for i, pos in enumerate(mapa) if codigo & (1 << i)]

def generar_imagen(texto_braille):
    radio      = mm(DIAMETRO_PUNTO_MM / 2)
    sep        = mm(SEPARACION_MM)
    paso_celda = mm(ESPACIO_ENTRE_CELDAS_MM)
    paso_linea = mm(ESPACIO_ENTRE_LINEAS_MM)
    margen     = mm(MARGEN_MM)

    lineas       = texto_braille.split("\n")
    max_celdas   = max(len(l) for l in lineas)
    ancho        = margen * 2 + paso_celda * max_celdas
    alto_celda   = sep * 2 + mm(DIAMETRO_PUNTO_MM)
    alto         = margen * 2 + paso_linea * (len(lineas) - 1) + alto_celda

    img  = Image.new("RGB", (ancho, alto), COLOR_FONDO)
    draw = ImageDraw.Draw(img)

    for nl, linea in enumerate(lineas):
        y = margen + nl * paso_linea
        for idx, car in enumerate(linea):
            x = margen + idx * paso_celda
            for f in range(3):
                for c in range(2):
                    cx, cy = x + c*sep, y + f*sep
                    draw.ellipse([cx-radio,cy-radio,cx+radio,cy+radio], fill=COLOR_GUIA)
            for (f, c) in obtener_puntos(car):
                cx, cy = x + c*sep, y + f*sep
                draw.ellipse([cx-radio,cy-radio,cx+radio,cy+radio], fill=COLOR_PUNTO)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

def calcular_botellas(texto_braille):
    """
    Estima gramos de filamento PET basándose en dimensiones reales de la placa.
    Calibrado con dato real: placa ~40x60mm (5 líneas, 5 chars) = 5.50g en slicer.

    Fórmula: densidad superficial calibrada × área + aporte de puntos.
    DENSIDAD_SUP calibrada = 5.50g / (4.0cm × 6.5cm) ≈ 0.212 g/cm²
    Los puntos añaden ~0.008g cada uno sobre ese valor base.
    Botella PET 600ml: ~20g (promedio México)
    """
    import math
    DENSIDAD_SUP   = 0.212  # g/cm² — calibrado con dato real del slicer
    GRAMOS_PUNTO   = 0.008  # g por punto Braille adicional
    GRAMOS_BOTELLA = 20.0

    paso_celda = ESPACIO_ENTRE_CELDAS_MM / 10
    paso_linea = ESPACIO_ENTRE_LINEAS_MM / 10
    margen     = MARGEN_MM / 10

    lineas     = texto_braille.split("\n")
    max_celdas = max(len(l) for l in lineas)
    ancho_cm   = margen * 2 + paso_celda * max_celdas
    alto_cm    = margen * 2 + paso_linea * (len(lineas) - 1) + SEPARACION_MM/10 * 2 + DIAMETRO_PUNTO_MM/10 + 1.2

    # Gramos base (base plate con perímetros + infill, calibrado)
    gramos_base = ancho_cm * alto_cm * DENSIDAD_SUP

    # Gramos extra por puntos Braille
    total_puntos = sum(len(obtener_puntos(c)) for linea in lineas for c in linea)
    gramos = gramos_base + total_puntos * GRAMOS_PUNTO

    botellas = gramos / GRAMOS_BOTELLA
    return round(gramos, 1), round(botellas, 2)


def generar_stl(texto_braille):
    if not CADQUERY_OK:
        return None

    GROSOR_BASE  = 1.5
    ALTURA_PUNTO = 1.6
    RADIO_PUNTO  = DIAMETRO_PUNTO_MM / 2
    sep        = SEPARACION_MM
    paso_celda = ESPACIO_ENTRE_CELDAS_MM
    paso_linea = ESPACIO_ENTRE_LINEAS_MM
    margen     = MARGEN_MM

    lineas     = texto_braille.split("\n")
    max_celdas = max(len(l) for l in lineas)
    ancho_base = margen * 2 + paso_celda * max_celdas
    alto_base  = margen * 2 + paso_linea * (len(lineas) - 1) + sep * 2 + DIAMETRO_PUNTO_MM + 12

    modelo = cq.Workplane("XY").box(ancho_base, alto_base, GROSOR_BASE)

    # ✅ TODO ESTO VA DENTRO
    cilindros = []

    for nl, linea in enumerate(lineas):
        for idx, car in enumerate(linea):
            x = -ancho_base/2 + margen + idx * paso_celda
            y =  alto_base/2  - margen - nl  * paso_linea
            for (f, c) in obtener_puntos(car):
                cx, cy, cz = x + c*sep, y - f*sep, GROSOR_BASE/2

                cilindros.append(
                    cq.Workplane("XY")
                    .transformed(offset=(cx, cy, cz))
                    .cylinder(ALTURA_PUNTO, RADIO_PUNTO)
                    .val()
                )

    # unión masiva (rápida)
    if cilindros:
        comp = cq.Compound.makeCompound(cilindros)
        modelo = modelo.union(comp)

    # texto
    t = (
        cq.Workplane("XY")
        .transformed(offset=(0, -alto_base/2 + margen, GROSOR_BASE/2))
        .text("ECODOT", fontsize=6, distance=0.6, halign="center", valign="center")
    )
    modelo = modelo.union(t)

    tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
    tmp.close()
    cq.exporters.export(modelo, tmp.name)

    return tmp.name

# -------------------------------------------------------
# RUTAS
# -------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/convertir", methods=["POST"])
def convertir():
    data   = request.get_json()
    texto  = data.get("texto", "").strip()
    if not texto:
        return jsonify({"error": "Texto vacío"}), 400

    braille = ajustar_lineas(texto_a_braille(texto))
    buf     = generar_imagen(braille)
    b64     = base64.b64encode(buf.read()).decode()

    gramos, botellas = calcular_botellas(braille)

    return jsonify({
        "braille":   braille,
        "imagen":    b64,
        "cadquery":  CADQUERY_OK,
        "gramos":    gramos,
        "botellas":  botellas,
    })

@app.route("/stl", methods=["POST"])
def stl():
    data   = request.get_json()
    texto  = data.get("texto", "").strip()
    if not texto:
        return jsonify({"error": "Texto vacío"}), 400

    braille  = ajustar_lineas(texto_a_braille(texto))
    stl_path = generar_stl(braille)

    if not stl_path:
        return jsonify({"error": "cadquery no disponible"}), 500

    palabras   = texto.replace("\n"," ").split()
    nombre     = "_".join(palabras[:4]) + ".stl"

    response = send_file(stl_path, as_attachment=True, download_name=nombre, mimetype="application/octet-stream")

    @response.call_on_close
    def cleanup():
        try: os.unlink(stl_path)
        except: pass

    return response




# -------------------------------------------------------
# CROQUIS TÁCTIL — funciones
# -------------------------------------------------------
try:
    import cv2
    import numpy as np
    CV2_OK = True
except ImportError:
    CV2_OK = False

BRAILLE_NUMS = {
    "1":"⠁","2":"⠃","3":"⠉","4":"⠙","5":"⠑",
    "6":"⠋","7":"⠛","8":"⠓","9":"⠊","0":"⠚",
}

def procesar_imagen_mapa(img_bytes, min_area=800, simplify_eps=2.0):
    """
    Detecta líneas verdes brillantes por color HSV.
    Usa RETR_LIST para capturar TODOS los contornos incluyendo internos.
    """
    if not CV2_OK:
        return None, 0, 0, []

    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

    MAX_W = 600
    h, w  = img.shape[:2]
    if w > MAX_W:
        scale = MAX_W / w
        img   = cv2.resize(img, (MAX_W, int(h * scale)))
        h, w  = img.shape[:2]

    # ── 1. Máscara de verde brillante en HSV ──
    hsv         = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lower_green = np.array([40, 80, 80])
    upper_green = np.array([95, 255, 255])
    mascara     = cv2.inRange(hsv, lower_green, upper_green)

    # ── 2. Closing para rellenar interior de las líneas ──
    kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (10, 10))
    rellena      = cv2.morphologyEx(mascara, cv2.MORPH_CLOSE, kernel_close, iterations=2)

    # Opening suave para eliminar ruido pequeño
    kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    limpia      = cv2.morphologyEx(rellena, cv2.MORPH_OPEN, kernel_open, iterations=1)

    # ── 3. RETR_LIST captura todos los contornos incluyendo internos ──
    contornos_raw, _ = cv2.findContours(limpia, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    # ── 4. Filtrar por área y simplificar ──
    contornos_filtrados = []
    preview = np.zeros((h, w, 3), dtype=np.uint8)

    for c in contornos_raw:
        area = cv2.contourArea(c)
        if area < min_area:
            continue
        epsilon = max(0.3, simplify_eps * cv2.arcLength(c, True) / 1000.0)
        approx  = cv2.approxPolyDP(c, epsilon, True)
        contornos_filtrados.append(approx)
        cv2.drawContours(preview, [approx], -1, (80, 200, 80), 2)

    _, buf = cv2.imencode('.png', preview)
    b64    = base64.b64encode(buf.tobytes()).decode()

    return b64, w, h, contornos_filtrados



def generar_stl_mapa_con_progreso(contornos, marcadores, leyenda_texto,
                                   ancho_px, alto_px, progress_cb,
                                   ancho_placa_mm=150, grosor_base=1.5,
                                   altura_linea=1.2, ancho_linea=1.0):
    """
    Geometría claramente separada en dos zonas:
    ┌─────────────────────────────┐  ← top
    │  MARGEN                     │
    │  ZONA MAPA (alto_mapa_mm)   │
    │  MARGEN                     │
    ├─────────────────────────────┤  ← separador grabado
    │  MARGEN                     │
    │  ZONA LEYENDA (variable)    │
    │  ZONA ECODOT                │
    │  MARGEN                     │
    └─────────────────────────────┘  ← bottom
    """
    if not CADQUERY_OK:
        return None

    import math

    MARGEN = 5.0
    SEP    = SEPARACION_MM
    R_PT   = DIAMETRO_PUNTO_MM / 2
    H_PT   = 1.6

    # ── Dimensiones zona mapa ──
    escala       = ancho_placa_mm / ancho_px
    alto_mapa_mm = alto_px * escala
    ancho_base   = ancho_placa_mm + MARGEN * 2

    # ── Dimensiones zona leyenda (crece según contenido) ──
    leyenda_braille = ajustar_lineas(texto_a_braille(leyenda_texto)) if leyenda_texto.strip() else ""
    n_lineas_ley    = len(leyenda_braille.split("\n")) if leyenda_braille.strip() else 0
    # Cada línea Braille ocupa ESPACIO_ENTRE_LINEAS_MM + margen arriba/abajo + ECODOT
    alto_leyenda_mm = (n_lineas_ley * ESPACIO_ENTRE_LINEAS_MM + MARGEN * 2) if n_lineas_ley else 0
    alto_ecodot_mm  = 8.0   # espacio fijo para marca ECODOT

    # ── Altura total de la placa ──
    alto_zona_mapa    = alto_mapa_mm + MARGEN * 2
    alto_zona_leyenda = alto_leyenda_mm + alto_ecodot_mm + MARGEN
    alto_base         = alto_zona_mapa + alto_zona_leyenda

    # ── Origen Y de cada zona (coordenadas CadQuery, centro=0) ──
    # Y positivo = arriba, Y negativo = abajo
    y_top_mapa    =  alto_base / 2                          # borde superior
    y_bot_mapa    =  alto_base / 2 - alto_zona_mapa         # borde inferior zona mapa
    y_top_leyenda =  y_bot_mapa                             # borde superior zona leyenda
    y_bot_leyenda = -alto_base / 2                          # borde inferior

    progress_cb(2, "Creando base de la placa...")
    modelo = cq.Workplane("XY").box(ancho_base, alto_base, grosor_base)
    cz     = grosor_base / 2

    # Línea separadora entre mapa y leyenda
    if n_lineas_ley > 0:
        separador = (
            cq.Workplane("XY")
            .transformed(offset=(0, y_bot_mapa, cz))
            .box(ancho_base - MARGEN*2, 0.6, 0.8)
        )
        modelo = modelo.union(separador)

    # ── Contornos del mapa ──
    total = len(contornos)
    progress_cb(5, f"Extrudiendo {total} contornos...")

    for idx, contorno in enumerate(contornos):
        pts = contorno.reshape(-1, 2)
        if len(pts) < 2:
            continue

        pts_mm = []
        for (px, py) in pts:
            # El mapa ocupa desde y_top_mapa - MARGEN hasta y_bot_mapa + MARGEN
            x_mm = -ancho_base/2 + MARGEN + px * escala
            y_mm =  y_top_mapa - MARGEN   - py * escala
            pts_mm.append((x_mm, y_mm))

        if pts_mm[0] != pts_mm[-1]:
            pts_mm.append(pts_mm[0])

        for i in range(len(pts_mm) - 1):
            x1, y1 = pts_mm[i]
            x2, y2 = pts_mm[i+1]
            dx  = x2 - x1
            dy  = y2 - y1
            lng = math.sqrt(dx*dx + dy*dy)
            if lng < 0.1:
                continue
            angulo = math.degrees(math.atan2(dy, dx))
            seg = (
                cq.Workplane("XY")
                .transformed(offset=((x1+x2)/2, (y1+y2)/2, cz),
                             rotate=(0, 0, angulo))
                .box(lng, ancho_linea, altura_linea)
            )
            modelo = modelo.union(seg)

        pct = 5 + int(((idx + 1) / total) * 65)
        progress_cb(pct, f"Contorno {idx+1}/{total}...")

    # ── Marcadores numéricos (dentro de zona mapa) ──
    progress_cb(71, "Anadiendo marcadores en Braille...")
    for m in marcadores:
        num_str = str(m.get("numero", ""))
        mx = -ancho_base/2 + MARGEN + m.get("x_pct", 0.5) * ancho_placa_mm
        my =  y_top_mapa - MARGEN   - m.get("y_pct", 0.5) * alto_mapa_mm
        for i, digito in enumerate(num_str):
            car = BRAILLE.get(digito, "")
            if not car: continue
            ox = mx + i * ESPACIO_ENTRE_CELDAS_MM
            for (fila, col) in obtener_puntos(car):
                modelo = modelo.union(
                    cq.Workplane("XY")
                    .transformed(offset=(ox+col*SEP, my-fila*SEP, cz))
                    .cylinder(H_PT, R_PT)
                )

    # ── Leyenda Braille (zona separada debajo del mapa) ──
    progress_cb(80, "Anadiendo leyenda Braille...")
    if leyenda_braille.strip():
        lineas_ley = leyenda_braille.split("\n")
        for nl, linea in enumerate(lineas_ley):
            # Primera línea arriba de la zona leyenda, resto hacia abajo
            y_ley = y_top_leyenda - MARGEN - (nl + 0.5) * ESPACIO_ENTRE_LINEAS_MM
            for idx2, car in enumerate(linea):
                x_ley = -ancho_base/2 + MARGEN + idx2 * ESPACIO_ENTRE_CELDAS_MM
                for (fila, col) in obtener_puntos(car):
                    modelo = modelo.union(
                        cq.Workplane("XY")
                        .transformed(offset=(x_ley+col*SEP, y_ley-fila*SEP, cz))
                        .cylinder(H_PT, R_PT)
                    )

    # ── Marca ECODOT al fondo de zona leyenda ──
    progress_cb(93, "Anadiendo marca ECODOT...")
    modelo = modelo.union(
        cq.Workplane("XY")
        .transformed(offset=(0, y_bot_leyenda + MARGEN, cz))
        .text("ECODOT", fontsize=5, distance=0.5, halign="center", valign="center")
    )

    progress_cb(96, "Exportando STL...")
    tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
    tmp.close()
    cq.exporters.export(modelo, tmp.name)
    progress_cb(100, "Listo!")
    return tmp.name


# ── Cola de jobs ──
import threading, uuid, queue as queue_mod, json as _json

_jobs = {}

def _worker(job_id, contornos, marcadores, leyenda, w, h):
    q = _jobs[job_id]["queue"]
    def cb(pct, msg):
        q.put({"pct": pct, "msg": msg})
    try:
        path = generar_stl_mapa_con_progreso(
            contornos, marcadores, leyenda, w, h, cb
        )
        _jobs[job_id]["stl_path"] = path
    except Exception as e:
        _jobs[job_id]["error"] = str(e)
        q.put({"pct": -1, "msg": f"Error: {e}"})
    finally:
        q.put(None)


# ── RUTAS CROQUIS ──

@app.route("/mapa/preview", methods=["POST"])
def mapa_preview():
    if not CV2_OK:
        return jsonify({"error": "opencv no instalado"}), 500
    f = request.files.get("imagen")
    if not f:
        return jsonify({"error": "No se recibio imagen"}), 400
    min_area = int(request.form.get("min_area", 800))
    img_bytes = f.read()
    b64, w, h, _ = procesar_imagen_mapa(img_bytes, min_area)
    return jsonify({"preview": b64, "ancho": w, "alto": h})


@app.route("/mapa/iniciar", methods=["POST"])
def mapa_iniciar():
    if not CV2_OK:      return jsonify({"error": "opencv no instalado"}), 500
    if not CADQUERY_OK: return jsonify({"error": "cadquery no instalado"}), 500

    f = request.files.get("imagen")
    if not f: return jsonify({"error": "No se recibio imagen"}), 400

    min_area   = int(request.form.get("min_area", 800))
    marcadores = _json.loads(request.form.get("marcadores", "[]"))
    leyenda    = request.form.get("leyenda", "")

    img_bytes = f.read()
    _, w, h, contornos = procesar_imagen_mapa(img_bytes, min_area)

    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"queue": queue_mod.Queue(), "stl_path": None, "error": None}

    t = threading.Thread(target=_worker,
                         args=(job_id, contornos, marcadores, leyenda, w, h),
                         daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/mapa/progreso/<job_id>")
def mapa_progreso(job_id):
    if job_id not in _jobs:
        return jsonify({"error": "job no encontrado"}), 404

    def stream():
        q = _jobs[job_id]["queue"]
        while True:
            item = q.get()
            if item is None:
                if _jobs[job_id]["error"]:
                    yield f'data: {{"pct":-1,"msg":"Error"}}\n\n'
                else:
                    yield f'data: {{"pct":100,"msg":"Listo","done":true}}\n\n'
                break
            yield f"data: {_json.dumps(item)}\n\n"

    return app.response_class(
        stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
    )


@app.route("/mapa/descargar/<job_id>")
def mapa_descargar(job_id):
    job = _jobs.get(job_id)
    if not job or not job["stl_path"]:
        return jsonify({"error": "STL no disponible"}), 404

    path = job["stl_path"]
    response = send_file(path, as_attachment=True,
                         download_name="mapa_tactil.stl",
                         mimetype="application/octet-stream")

    @response.call_on_close
    def cleanup():
        try:
            os.unlink(path)
            del _jobs[job_id]
        except: pass

    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
    

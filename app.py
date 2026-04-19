from flask import Flask, render_template, request, send_file, jsonify
import io, base64, os, tempfile, math, threading, uuid, queue as queue_mod, json as _json

from PIL import Image, ImageDraw
import trimesh
import numpy as np

# Optional CV2
try:
    import cv2
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

COLOR_FONDO = (255,255,255)
COLOR_PUNTO = (20,20,80)
COLOR_GUIA = (200,210,225)

TRIMESH_OK = True

# -------------------------------------------------------
# BRAILLE
# -------------------------------------------------------
BRAILLE = {
    "a":"⠁","b":"⠃","c":"⠉","d":"⠙","e":"⠑",
    "f":"⠋","g":"⠛","h":"⠓","i":"⠊","j":"⠚",
    "k":"⠅","l":"⠇","m":"⠍","n":"⠝","o":"⠕",
    "p":"⠏","q":"⠟","r":"⠗","s":"⠎","t":"⠞",
    "u":"⠥","v":"⠧","w":"⠺","x":"⠭","y":"⠽","z":"⠵",
    "á":"⠷","é":"⠮","í":"⠌","ó":"⠬","ú":"⠾","ü":"⠳","ñ":"⠻",
    "1":"⠁","2":"⠃","3":"⠉","4":"⠙","5":"⠑",
    "6":"⠋","7":"⠛","8":"⠓","9":"⠊","0":"⠚",
    ".":"⠲",",":"⠂"," ":" ",
}

def mm(v): return round(v * PX_POR_MM)

def texto_a_braille(texto):
    return "\n".join(
        "".join(BRAILLE.get(c, "?") for c in linea.lower())
        for linea in texto.split("\n")
    )

def ajustar_lineas(texto_braille):
    max_chars = int((140 - MARGEN_MM*2) / ESPACIO_ENTRE_CELDAS_MM)
    out = []
    for linea in texto_braille.split("\n"):
        while len(linea) > max_chars:
            corte = linea.rfind(" ", 0, max_chars)
            if corte == -1: corte = max_chars
            out.append(linea[:corte])
            linea = linea[corte:].lstrip()
        out.append(linea)
    return "\n".join(out)

def obtener_puntos(c):
    if c == " ": return []
    code = ord(c) - 0x2800
    mapa = [(0,0),(1,0),(2,0),(0,1),(1,1),(2,1)]
    return [p for i,p in enumerate(mapa) if code & (1<<i)]

# -------------------------------------------------------
# IMAGE
# -------------------------------------------------------
def generar_imagen(texto_braille):
    radio = mm(DIAMETRO_PUNTO_MM/2)
    sep = mm(SEPARACION_MM)
    paso_celda = mm(ESPACIO_ENTRE_CELDAS_MM)
    paso_linea = mm(ESPACIO_ENTRE_LINEAS_MM)
    margen = mm(MARGEN_MM)

    lineas = texto_braille.split("\n")
    max_celdas = max(len(l) for l in lineas)

    ancho = margen*2 + paso_celda*max_celdas
    alto = margen*2 + paso_linea*(len(lineas)-1) + sep*2 + mm(DIAMETRO_PUNTO_MM)

    img = Image.new("RGB",(ancho,alto),COLOR_FONDO)
    draw = ImageDraw.Draw(img)

    for nl,linea in enumerate(lineas):
        y = margen + nl*paso_linea
        for i,c in enumerate(linea):
            x = margen + i*paso_celda

            for f in range(3):
                for col in range(2):
                    cx,cy = x+col*sep, y+f*sep
                    draw.ellipse([cx-radio,cy-radio,cx+radio,cy+radio],fill=COLOR_GUIA)

            for f,col in obtener_puntos(c):
                cx,cy = x+col*sep, y+f*sep
                draw.ellipse([cx-radio,cy-radio,cx+radio,cy+radio],fill=COLOR_PUNTO)

    buf = io.BytesIO()
    img.save(buf,format="PNG")
    buf.seek(0)
    return buf

# -------------------------------------------------------
# STL BRAILLE (TRIMESH)
# -------------------------------------------------------
def generar_stl(texto_braille):
    GROSOR_BASE = 1.5
    ALTURA_PUNTO = 1.6
    RADIO = DIAMETRO_PUNTO_MM/2

    sep = SEPARACION_MM
    paso_celda = ESPACIO_ENTRE_CELDAS_MM
    paso_linea = ESPACIO_ENTRE_LINEAS_MM
    margen = MARGEN_MM

    lineas = texto_braille.split("\n")
    max_celdas = max(len(l) for l in lineas)

    ancho = margen*2 + paso_celda*max_celdas
    alto = margen*2 + paso_linea*(len(lineas)-1) + sep*2 + DIAMETRO_PUNTO_MM + 12

    meshes = []

    base = trimesh.creation.box(extents=(ancho,alto,GROSOR_BASE))
    meshes.append(base)

    for nl,linea in enumerate(lineas):
        for i,c in enumerate(linea):
            x = -ancho/2 + margen + i*paso_celda
            y =  alto/2  - margen - nl*paso_linea

            for f,col in obtener_puntos(c):
                cx = x + col*sep
                cy = y - f*sep

                dot = trimesh.creation.cylinder(radius=RADIO,height=ALTURA_PUNTO)
                dot.apply_translation([cx,cy,GROSOR_BASE/2 + ALTURA_PUNTO/2])
                meshes.append(dot)

    model = trimesh.util.concatenate(meshes)

    tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
    tmp.close()
    model.export(tmp.name)
    return tmp.name

# -------------------------------------------------------
# MAP PROCESSING (CV2)
# -------------------------------------------------------
def procesar_imagen_mapa(img_bytes, min_area=800):
    if not CV2_OK:
        return None,0,0,[]

    arr = np.frombuffer(img_bytes,np.uint8)
    img = cv2.imdecode(arr,cv2.IMREAD_COLOR)

    hsv = cv2.cvtColor(img,cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv,(40,80,80),(95,255,255))

    contornos,_ = cv2.findContours(mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)

    filtrados = [c for c in contornos if cv2.contourArea(c) > min_area]

    _,buf = cv2.imencode('.png',img)
    b64 = base64.b64encode(buf.tobytes()).decode()

    return b64,img.shape[1],img.shape[0],filtrados

# -------------------------------------------------------
# STL MAP (TRIMESH)
# -------------------------------------------------------
def generar_stl_mapa(contornos, marcadores, w, h):
    MARGEN = 5
    escala = 150 / w

    meshes = []

    base = trimesh.creation.box(extents=(160,160,1.5))
    meshes.append(base)

    for contorno in contornos:
        pts = contorno.reshape(-1,2)
        for i in range(len(pts)-1):
            x1,y1 = pts[i]
            x2,y2 = pts[i+1]

            dx,dy = x2-x1,y2-y1
            lng = math.sqrt(dx*dx+dy*dy)
            if lng < 1: continue

            angle = math.atan2(dy,dx)

            box = trimesh.creation.box(extents=(lng*escala,1,1))
            mat = trimesh.transformations.rotation_matrix(angle,[0,0,1])
            mat[0][3]=x1*escala
            mat[1][3]=y1*escala
            mat[2][3]=1

            box.apply_transform(mat)
            meshes.append(box)

    model = trimesh.util.concatenate(meshes)

    tmp = tempfile.NamedTemporaryFile(suffix=".stl", delete=False)
    tmp.close()
    model.export(tmp.name)
    return tmp.name

# -------------------------------------------------------
# ROUTES
# -------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/convertir",methods=["POST"])
def convertir():
    data = request.get_json()
    texto = data.get("texto","").strip()

    braille = ajustar_lineas(texto_a_braille(texto))
    img = generar_imagen(braille)

    b64 = base64.b64encode(img.read()).decode()

    return jsonify({
        "braille":braille,
        "imagen":b64,
        "stl":True
    })

@app.route("/stl",methods=["POST"])
def stl():
    data = request.get_json()
    texto = data.get("texto","").strip()

    braille = ajustar_lineas(texto_a_braille(texto))
    path = generar_stl(braille)

    return send_file(path,as_attachment=True,download_name="braille.stl")

# -------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0",port=5000)

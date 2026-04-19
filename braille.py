from PIL import Image, ImageDraw
import cadquery as cq   # para generar el archivo 3D (.stl)

DPI = 96
PX_POR_MM = DPI / 25.4   # ≈ 3.78 píxeles por milímetro

def mm(valor):
    """Convierte milímetros a píxeles (entero redondeado)."""
    return round(valor * PX_POR_MM)


# -----------------------------------------------------------
# MEDIDAS ESTÁNDAR DEL BRAILLE (en milímetros)
# -----------------------------------------------------------
DIAMETRO_PUNTO_MM       = 1.8
SEPARACION_MM           = 2.5
ESPACIO_ENTRE_CELDAS_MM = 6.0
ESPACIO_ENTRE_LINEAS_MM = 10.0
MARGEN_MM               = 5.0

COLOR_FONDO = (255, 255, 255)
COLOR_PUNTO = (20,  20,  80)
COLOR_GUIA  = (200, 210, 225)

BRAILLE = {
    "a": "⠁",  "b": "⠃",  "c": "⠉",  "d": "⠙",  "e": "⠑",
    "f": "⠋",  "g": "⠛",  "h": "⠓",  "i": "⠊",  "j": "⠚",
    "k": "⠅",  "l": "⠇",  "m": "⠍",  "n": "⠝",  "o": "⠕",
    "p": "⠏",  "q": "⠟",  "r": "⠗",  "s": "⠎",  "t": "⠞",
    "u": "⠥",  "v": "⠧",  "w": "⠺",  "x": "⠭",  "y": "⠽",
    "z": "⠵",
    "á": "⠷",  "é": "⠮",  "í": "⠌",  "ó": "⠬",  "ú": "⠾",
    "ü": "⠳",  "ñ": "⠻",
    "1": "⠁",  "2": "⠃",  "3": "⠉",  "4": "⠙",  "5": "⠑",
    "6": "⠋",  "7": "⠛",  "8": "⠓",  "9": "⠊",  "0": "⠚",
    ".": "⠲",  ",": "⠂",  ";": "⠆",  ":": "⠒",
    "?": "⠦",  "!": "⠖",  "-": "⠤",  "'": "⠄",
    "(": "⠶",  ")": "⠶",
    " ": " ",
}


# -----------------------------------------------------------
# FUNCIÓN 1: Convierte texto a cadena de símbolos Braille
# -----------------------------------------------------------
def texto_a_braille(texto):
    # Convertimos línea por línea para preservar los saltos de línea
    lineas = texto.split("\n")
    lineas_braille = []
    for linea in lineas:
        linea = linea.lower()
        resultado = ""
        for letra in linea:
            simbolo = BRAILLE.get(letra, "?")
            resultado += simbolo
        lineas_braille.append(resultado)
    return "\n".join(lineas_braille)


# -----------------------------------------------------------
# FUNCIÓN AUXILIAR: divide el texto Braille en líneas que
# quepan dentro del ancho máximo de media carta (140 mm).
#
# Se aplica ANTES de generar la imagen y el STL, así ambos
# respetan el mismo ancho máximo automáticamente.
# -----------------------------------------------------------
def ajustar_lineas(texto_braille):
    # Ancho disponible = hoja - márgenes izquierdo y derecho
    ancho_maximo_mm = 140 - MARGEN_MM * 2

    # Cuántos caracteres Braille caben en ese ancho
    max_caracteres = int(ancho_maximo_mm / ESPACIO_ENTRE_CELDAS_MM)

    lineas_originales = texto_braille.split("\n")
    lineas_finales    = []

    for linea in lineas_originales:
        # Si la línea ya cabe, la dejamos igual
        if len(linea) <= max_caracteres:
            lineas_finales.append(linea)
        else:
            # Si no cabe, la dividimos tratando de cortar en espacios
            while len(linea) > max_caracteres:
                # Buscamos el último espacio antes del límite
                corte = linea.rfind(" ", 0, max_caracteres)

                if corte == -1:
                    # No hay espacio, cortamos a la fuerza
                    corte = max_caracteres

                lineas_finales.append(linea[:corte])
                linea = linea[corte:].lstrip(" ")

            if linea:
                lineas_finales.append(linea)

    return "\n".join(lineas_finales)


# -----------------------------------------------------------
# FUNCIÓN 2: Obtiene qué puntos están activos en un carácter Braille
# -----------------------------------------------------------
def obtener_puntos(caracter_braille):
    if caracter_braille == " ":
        return []
    codigo = ord(caracter_braille) - 0x2800
    mapa_bits = [
        (0, 0), (1, 0), (2, 0),
        (0, 1), (1, 1), (2, 1),
    ]
    puntos_activos = []
    for i, posicion in enumerate(mapa_bits):
        if codigo & (1 << i):
            puntos_activos.append(posicion)
    return puntos_activos


# -----------------------------------------------------------
# FUNCIÓN 3: Genera la imagen .png
# -----------------------------------------------------------
def braille_a_imagen(texto_braille, archivo_salida="braille.png"):

    radio      = mm(DIAMETRO_PUNTO_MM / 2)
    sep        = mm(SEPARACION_MM)
    paso_celda = mm(ESPACIO_ENTRE_CELDAS_MM)
    paso_linea = mm(ESPACIO_ENTRE_LINEAS_MM)
    margen     = mm(MARGEN_MM)

    lineas       = texto_braille.split("\n")
    max_celdas   = max(len(linea) for linea in lineas)
    ancho_imagen = margen * 2 + paso_celda * max_celdas
    alto_celda   = sep * 2 + mm(DIAMETRO_PUNTO_MM)
    alto_imagen  = margen * 2 + paso_linea * (len(lineas) - 1) + alto_celda

    imagen = Image.new("RGB", (ancho_imagen, alto_imagen), COLOR_FONDO)
    draw   = ImageDraw.Draw(imagen)

    for num_linea, linea in enumerate(lineas):
        y_linea = margen + num_linea * paso_linea
        for indice, caracter in enumerate(linea):
            x_celda = margen + indice * paso_celda
            for fila in range(3):
                for columna in range(2):
                    cx = x_celda + columna * sep
                    cy = y_linea  + fila    * sep
                    draw.ellipse([cx-radio, cy-radio, cx+radio, cy+radio], fill=COLOR_GUIA)
            for (fila, columna) in obtener_puntos(caracter):
                cx = x_celda + columna * sep
                cy = y_linea  + fila    * sep
                draw.ellipse([cx-radio, cy-radio, cx+radio, cy+radio], fill=COLOR_PUNTO)

    imagen.save(archivo_salida)
    print(f"  Imagen guardada: {archivo_salida}  ({ancho_imagen}×{alto_imagen} px  a {DPI} DPI)")


# -----------------------------------------------------------
# FUNCIÓN 4: Genera el modelo 3D .stl
# -----------------------------------------------------------
def braille_a_stl(texto_braille, archivo_salida="braille.stl"):

    GROSOR_BASE  = 1.5
    ALTURA_PUNTO = 1.6   # se divide a la mitad internamente por CadQuery
    RADIO_PUNTO  = DIAMETRO_PUNTO_MM / 2

    sep        = SEPARACION_MM
    paso_celda = ESPACIO_ENTRE_CELDAS_MM
    paso_linea = ESPACIO_ENTRE_LINEAS_MM
    margen     = MARGEN_MM

    lineas     = texto_braille.split("\n")
    max_celdas = max(len(linea) for linea in lineas)

    ancho_base = margen * 2 + paso_celda * max_celdas
    # 12 mm extra abajo para los textos de marca
    alto_base  = margen * 2 + paso_linea * (len(lineas) - 1) + sep * 2 + DIAMETRO_PUNTO_MM + 12

    modelo = cq.Workplane("XY").box(ancho_base, alto_base, GROSOR_BASE)

    for num_linea, linea in enumerate(lineas):
        for indice, caracter in enumerate(linea):
            x_celda = -ancho_base / 2 + margen + indice * paso_celda
            y_celda =  alto_base  / 2 - margen - num_linea * paso_linea
            for (fila, columna) in obtener_puntos(caracter):
                cx = x_celda + columna * sep
                cy = y_celda - fila    * sep
                cz = GROSOR_BASE / 2
                cilindro = (
                    cq.Workplane("XY")
                    .transformed(offset=(cx, cy, cz))
                    .cylinder(ALTURA_PUNTO, RADIO_PUNTO)
                )
                modelo = modelo.union(cilindro)

    # --- Texto "LA MALEZA CAFE" arriba de ECODOT ---
    texto_marca2 = (
        cq.Workplane("XY")
        .transformed(offset=(0, -alto_base / 2 + margen + 6, GROSOR_BASE / 2))
        .text("LA MALEZA CAFE", fontsize=6, distance=0.6, halign="center", valign="center")
    )
    modelo = modelo.union(texto_marca2)

    # --- Texto "ECODOT" abajo ---
    texto_marca = (
        cq.Workplane("XY")
        .transformed(offset=(0, -alto_base / 2 + margen, GROSOR_BASE / 2))
        .text("ECODOT", fontsize=6, distance=0.6, halign="center", valign="center")
    )
    modelo = modelo.union(texto_marca)

    cq.exporters.export(modelo, archivo_salida)
    print(f"  Modelo 3D guardado: {archivo_salida}  (base {ancho_base:.1f}×{alto_base:.1f} mm)")


# -----------------------------------------------------------
# PROGRAMA PRINCIPAL
# -----------------------------------------------------------
if __name__ == "__main__":

    print()
    print("╔══════════════════════════════════════════╗")
    print("║  CONVERTIDOR DE TEXTO A BRAILLE (IMAGEN) ║")
    print("╚══════════════════════════════════════════╝")
    print()
    print("Escribe 'salir' para terminar.")
    print()

    while True:

        print("➤ Escribe tu texto (Enter vacío para terminar, 'salir' para salir):")
        lineas = []
        while True:
            linea = input()
            if linea.strip().lower() == "salir":
                print("\n¡Hasta luego!")
                exit()
            if linea == "":
                break
            lineas.append(linea)
        entrada = "\n".join(lineas)

        if entrada.strip() == "":
            print("  Por favor escribe algo antes de continuar.")
            continue

        # Paso 1: texto → Braille
        braille = texto_a_braille(entrada)

        # Paso 1.5: ajustar líneas al ancho de media carta (140 mm)
        braille = ajustar_lineas(braille)

        # Paso 2: mostrar en consola
        print()
        print(f"  Texto original : {entrada}")
        print(f"  En Braille     : {braille}")

        # Paso 3: generar imagen .png
        palabras    = entrada.strip().replace("\n", " ").split()
        nombre_base = "_".join(palabras[:4])
        braille_a_imagen(braille, nombre_base + ".png")

        # Paso 4: generar modelo 3D .stl
        braille_a_stl(braille, nombre_base + ".stl")
        print()

        
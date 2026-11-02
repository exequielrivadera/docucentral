import sys

import re

import sqlite3

import os

import html
import json
import tempfile
import uuid
import urllib.request
import urllib.error

from pathlib import Path

from datetime import datetime
import time



from PySide6.QtWidgets import (

    QApplication,

    QMainWindow,

    QWidget,

    QVBoxLayout,

    QHBoxLayout,

    QPushButton,

    QLabel,

    QFileDialog,

    QTableWidget,

    QTableWidgetItem,

    QMessageBox,

    QProgressDialog,

    QTextEdit,

    QHeaderView,

    QSplitter,

    QAbstractItemView,

    QLineEdit,

    QComboBox,
    QFrame,
    QGridLayout,
    QScrollArea,
    QSizePolicy,
    QDialog,
    QFormLayout,
    QDialogButtonBox,
    QTreeWidget,
    QTreeWidgetItem,
    QInputDialog,
    QCheckBox,

)

from PySide6.QtCore import Qt, QPoint, QTimer

from PySide6.QtGui import QPainter, QPolygon, QIcon, QPixmap

from pypdf import PdfReader, PdfWriter
from nucleo_seguridad import GestorSeguridad, ErrorSeguridad
from gestion_organizacion import DialogoOrganizacion


class ComboBoxVisible(QComboBox):
    """QComboBox con una flecha blanca visible y bien integrada."""

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(Qt.GlobalColor.white)

        centro_x = self.width() - 15
        centro_y = self.height() // 2

        flecha = QPolygon([
            QPoint(centro_x - 5, centro_y - 2),
            QPoint(centro_x + 5, centro_y - 2),
            QPoint(centro_x, centro_y + 4),
        ])

        painter.drawPolygon(flecha)
        painter.end()




class VentanaInicioDocuCentral(QDialog):
    """Pantalla inicial para vincular al cliente antes de abrir la biblioteca compartida."""
    def __init__(self, ventana_app, parent=None):
        super().__init__(parent or ventana_app)
        self.ventana_app = ventana_app
        self.accion = ""
        self.setWindowTitle("Bienvenido a DocuCentral")
        self.setMinimumWidth(560)
        self.setModal(True)

        principal = QVBoxLayout(self)
        principal.setContentsMargins(28, 24, 28, 24)
        principal.setSpacing(14)

        titulo = QLabel("DocuCentral")
        titulo.setStyleSheet("font-size: 26px; font-weight: 700; color: #ffffff;")
        principal.addWidget(titulo)

        subtitulo = QLabel("Vinculación del cliente")
        subtitulo.setStyleSheet("font-size: 15px; font-weight: 600; color: #d0d0d0;")
        principal.addWidget(subtitulo)

        descripcion = QLabel(
            "Ingresá o vinculá la cuenta de la persona que va a utilizar DocuCentral. "
            "La biblioteca de esta computadora es compartida. Cambiar o quitar la cuenta "
            "no elimina PDF ni cambia sus contraseñas o la recuperación de documentos protegidos."
        )
        descripcion.setWordWrap(True)
        descripcion.setStyleSheet("color: #bdbdbd; line-height: 1.4;")
        principal.addWidget(descripcion)

        self.estado = QLabel()
        self.estado.setWordWrap(True)
        self.estado.setStyleSheet(
            "padding: 12px; border: 1px solid #454545; border-radius: 8px; color: #eeeeee;"
        )
        principal.addWidget(self.estado)

        self.boton_continuar = QPushButton("Ingresar con usuario vinculado")
        self.boton_continuar.setMinimumHeight(40)
        self.boton_continuar.clicked.connect(self._continuar)
        principal.addWidget(self.boton_continuar)

        self.boton_vincular = QPushButton("Vincular / ingresar con otra cuenta")
        self.boton_vincular.setMinimumHeight(40)
        self.boton_vincular.clicked.connect(self._vincular)
        principal.addWidget(self.boton_vincular)

        self.boton_quitar = QPushButton("Quitar usuario de esta computadora…")
        self.boton_quitar.setMinimumHeight(36)
        self.boton_quitar.clicked.connect(self._quitar_usuario)
        principal.addWidget(self.boton_quitar)

        self.boton_eliminar_cuenta = QPushButton("Eliminar cuenta definitivamente…")
        self.boton_eliminar_cuenta.setMinimumHeight(36)
        self.boton_eliminar_cuenta.setStyleSheet("color: #ff8b8b;")
        self.boton_eliminar_cuenta.clicked.connect(self._eliminar_cuenta)
        principal.addWidget(self.boton_eliminar_cuenta)

        fila = QHBoxLayout()
        fila.addStretch(1)
        salir = QPushButton("Salir")
        salir.setMinimumWidth(100)
        salir.clicked.connect(self._salir)
        fila.addWidget(salir)
        principal.addLayout(fila)
        self._actualizar_estado()

    def _sesion_actual(self):
        return self.ventana_app._leer_json_local(self.ventana_app._ruta_sesion_cuenta(), {})

    def _actualizar_estado(self):
        sesion = self._sesion_actual()
        correo = str(sesion.get("correo", "")).strip() if sesion.get("activa") else ""
        if correo:
            self.estado.setText(f"Usuario vinculado en esta computadora:\n{correo}")
            self.boton_continuar.setEnabled(True)
            self.boton_quitar.setEnabled(True)
            self.boton_eliminar_cuenta.setEnabled(True)
        else:
            self.estado.setText(
                "No hay ningún usuario vinculado en esta computadora.\n"
                "Vinculá una cuenta para abrir la biblioteca compartida."
            )
            self.boton_continuar.setEnabled(False)
            self.boton_quitar.setEnabled(False)
            self.boton_eliminar_cuenta.setEnabled(False)

    def _continuar(self):
        self.accion = "autenticar_actual"
        self.accept()

    def _vincular(self):
        self.accion = "vincular"
        self.accept()

    def _quitar_usuario(self):
        if self.ventana_app.quitar_usuario_vinculado(confirmar=True):
            self._actualizar_estado()

    def _eliminar_cuenta(self):
        if self.ventana_app.eliminar_cuenta_remota():
            self._actualizar_estado()

    def _salir(self):
        self.accion = "salir"
        self.reject()


class DialogoDestinoCarpeta(QDialog):
    """Selector de destino para documentos marcados."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Elegir carpeta de destino")
        self.setModal(True)
        self.resize(560, 430)
        self.carpeta_id = None
        layout = QVBoxLayout(self)
        titulo = QLabel("¿Dónde querés guardar los documentos seleccionados?")
        titulo.setStyleSheet("font-size: 14px; font-weight: 600; padding: 4px;")
        layout.addWidget(titulo)
        self.arbol = QTreeWidget()
        self.arbol.setHeaderHidden(True)
        self.arbol.setMinimumHeight(250)
        self.arbol.itemDoubleClicked.connect(lambda item, col: self.aceptar())
        layout.addWidget(self.arbol)
        fila = QHBoxLayout()
        self.boton_nueva = QPushButton("➕ Nueva carpeta")
        self.boton_sub = QPushButton("↳ Nueva subcarpeta")
        fila.addWidget(self.boton_nueva); fila.addWidget(self.boton_sub); fila.addStretch()
        layout.addLayout(fila)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setStyleSheet("color: #aaaaaa; padding: 4px;")
        layout.addWidget(self.info)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Guardar aquí")
        botones.accepted.connect(self.aceptar); botones.rejected.connect(self.reject)
        layout.addWidget(botones)
        self.boton_nueva.clicked.connect(self.crear_carpeta)
        self.boton_sub.clicked.connect(self.crear_subcarpeta)
        self.cargar_arbol()

    def cargar_arbol(self, seleccionar_id=None):
        self.arbol.clear()
        conexion=conectar_db(); cursor=conexion.cursor()
        cursor.execute("SELECT id, nombre, padre_id FROM carpetas ORDER BY nombre COLLATE NOCASE")
        filas=cursor.fetchall(); conexion.close()
        nodos={}; pendientes=list(filas)
        while pendientes:
            progreso=False
            for fila in pendientes[:]:
                carpeta_id,nombre,padre_id=fila
                if padre_id is None: padre=self.arbol.invisibleRootItem()
                elif padre_id in nodos: padre=nodos[padre_id]
                else: continue
                item=QTreeWidgetItem([f"📁 {nombre}"]); item.setData(0,Qt.ItemDataRole.UserRole,carpeta_id)
                padre.addChild(item); nodos[carpeta_id]=item; pendientes.remove(fila); progreso=True
            if not progreso: break
        self.arbol.expandAll()
        if seleccionar_id is not None and seleccionar_id in nodos:
            self.arbol.setCurrentItem(nodos[seleccionar_id])
        self.info.setText("Elegí una carpeta existente o creá una nueva. También podés crear una subcarpeta dentro de la seleccionada." if filas else "Todavía no hay carpetas. Creá una y luego, si querés, una subcarpeta dentro de ella.")

    def _seleccionada_id(self):
        item=self.arbol.currentItem()
        return item.data(0,Qt.ItemDataRole.UserRole) if item else None

    def crear_carpeta(self):
        nombre,ok=QInputDialog.getText(self,"Nueva carpeta","Nombre de la carpeta:"); nombre=nombre.strip()
        if not ok or not nombre: return
        conexion=conectar_db(); cursor=conexion.cursor()
        try:
            cursor.execute("INSERT INTO carpetas (nombre, padre_id, fecha_creacion) VALUES (?, NULL, ?)",(nombre,datetime.now().strftime("%d/%m/%Y %H:%M:%S")))
            nuevo_id=cursor.lastrowid; conexion.commit()
        except sqlite3.IntegrityError:
            conexion.rollback(); conexion.close(); QMessageBox.warning(self,"Carpeta","Ya existe una carpeta con ese nombre."); return
        conexion.close(); self.cargar_arbol(nuevo_id)

    def crear_subcarpeta(self):
        padre_id=self._seleccionada_id()
        if padre_id is None:
            QMessageBox.information(self,"Nueva subcarpeta","Seleccioná primero la carpeta dentro de la cual querés crearla."); return
        nombre,ok=QInputDialog.getText(self,"Nueva subcarpeta","Nombre de la subcarpeta:"); nombre=nombre.strip()
        if not ok or not nombre: return
        conexion=conectar_db(); cursor=conexion.cursor()
        try:
            cursor.execute("INSERT INTO carpetas (nombre, padre_id, fecha_creacion) VALUES (?, ?, ?)",(nombre,padre_id,datetime.now().strftime("%d/%m/%Y %H:%M:%S")))
            nuevo_id=cursor.lastrowid; conexion.commit()
        except sqlite3.IntegrityError:
            conexion.rollback(); conexion.close(); QMessageBox.warning(self,"Subcarpeta","Ya existe una subcarpeta con ese nombre en ese nivel."); return
        conexion.close(); self.cargar_arbol(nuevo_id)

    def aceptar(self):
        carpeta_id=self._seleccionada_id()
        if carpeta_id is None:
            QMessageBox.information(self,"Destino","Seleccioná una carpeta de destino."); return
        self.carpeta_id=carpeta_id; self.accept()


# ============================================================

# CONFIGURACIÓN

# ============================================================



BASE_DIR = Path(__file__).resolve().parent


def ruta_recurso_img(nombre_archivo):
    """Localiza imágenes en ejecución normal o empaquetada con PyInstaller."""
    candidatos = [
        BASE_DIR / "img" / nombre_archivo,
        Path(getattr(sys, "_MEIPASS", BASE_DIR)) / "img" / nombre_archivo,
    ]
    for candidato in candidatos:
        if candidato.is_file():
            return candidato
    return candidatos[0]


# Logo cuadrado para iconos de ventanas y cuadros de advertencia.
LOGO_DOCUCENTRAL = ruta_recurso_img("docucentral_logo.png")
# Logo completo para reemplazar el título de texto en la ventana principal.
LOGO_DOCUCENTRAL_COMPLETO = ruta_recurso_img("docucentral_logoletras.png")


CORREO_RECUPERACION_DOCUCENTRAL = "docucentrallr@gmail.com"



DATA_DIR = BASE_DIR / "data"



DB_PATH = DATA_DIR / "documentia.db"



DATA_DIR.mkdir(

    exist_ok=True

)





# ============================================================

# BASE DE DATOS

# ============================================================



def conectar_db():

    return sqlite3.connect(DB_PATH)





def inicializar_base_datos():

    conexion = conectar_db()

    cursor = conexion.cursor()



    cursor.execute("""
        CREATE TABLE IF NOT EXISTS carpetas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            padre_id INTEGER,
            fecha_creacion TEXT,
            UNIQUE(nombre, padre_id),
            FOREIGN KEY(padre_id) REFERENCES carpetas(id) ON DELETE CASCADE
        )
    """)


    cursor.execute("""

        CREATE TABLE IF NOT EXISTS documentos (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            nombre TEXT NOT NULL,

            ruta TEXT UNIQUE NOT NULL,

            ruta_original TEXT,

            fecha_carga TEXT,

            paginas INTEGER,

            texto TEXT,

            fecha_documento TEXT,

            resumen TEXT,

            sensible INTEGER DEFAULT 0,

            carpeta_id INTEGER

        )

    """)



    conexion.commit()

    conexion.close()





def actualizar_estructura_base_datos():

    conexion = conectar_db()

    cursor = conexion.cursor()



    cursor.execute(

        "PRAGMA table_info(documentos)"

    )



    columnas = [

        fila[1]

        for fila in cursor.fetchall()

    ]



    if "ruta_original" not in columnas:
        cursor.execute("""
            ALTER TABLE documentos
            ADD COLUMN ruta_original TEXT
        """)

    if "fecha_carga" not in columnas:

        cursor.execute("""

            ALTER TABLE documentos

            ADD COLUMN fecha_carga TEXT

        """)



    if "paginas" not in columnas:

        cursor.execute("""

            ALTER TABLE documentos

            ADD COLUMN paginas INTEGER

        """)



    if "texto" not in columnas:

        cursor.execute("""

            ALTER TABLE documentos

            ADD COLUMN texto TEXT

        """)



    if "fecha_documento" not in columnas:

        cursor.execute("""

            ALTER TABLE documentos

            ADD COLUMN fecha_documento TEXT

        """)



    if "resumen" not in columnas:

        cursor.execute("""

            ALTER TABLE documentos

            ADD COLUMN resumen TEXT

        """)



    if "sensible" not in columnas:

        cursor.execute("""

            ALTER TABLE documentos

            ADD COLUMN sensible INTEGER DEFAULT 0

        """)


    if "carpeta_id" not in columnas:

        cursor.execute("""

            ALTER TABLE documentos

            ADD COLUMN carpeta_id INTEGER

        """)


    conexion.commit()

    conexion.close()





# ============================================================

# LECTURA DE PDF

# ============================================================



def leer_pdf(ruta_pdf):



    try:

        lector = PdfReader(ruta_pdf)



        textos = []



        for pagina in lector.pages:



            try:

                texto = pagina.extract_text()



            except Exception as e:

                print(

                    f"Error leyendo página de "

                    f"{ruta_pdf}: {e}"

                )



                texto = ""



            if texto:

                textos.append(texto)



        texto_final = "\n\n".join(textos)



        return (

            texto_final,

            len(lector.pages)

        )



    except Exception as e:



        print(

            f"Error leyendo PDF: {ruta_pdf}"

        )



        print(e)



        return (

            "",

            0

        )





# ============================================================

# FECHAS

# ============================================================



MESES = {

    "enero": "01",

    "febrero": "02",

    "marzo": "03",

    "abril": "04",

    "mayo": "05",

    "junio": "06",

    "julio": "07",

    "agosto": "08",

    "septiembre": "09",

    "setiembre": "09",

    "octubre": "10",

    "noviembre": "11",

    "diciembre": "12",

}





def normalizar_fecha(

    dia,

    mes,

    anio

):



    try:

        dia = int(dia)

        mes = int(mes)

        anio = int(anio)



        if (

            1 <= dia <= 31

            and

            1 <= mes <= 12

            and

            1900 <= anio <= 2100

        ):

            return (

                f"{dia:02d}/"

                f"{mes:02d}/"

                f"{anio}"

            )



    except ValueError:

        pass



    return None





def detectar_fecha(texto):



    if not texto:

        return None



    texto_normalizado = (

        texto

        .replace("\r", "\n")

    )



    # --------------------------------------------------------

    # FECHAS ESCRITAS

    # --------------------------------------------------------



    patron_escrito = re.compile(

        r"\b(\d{1,2})\s+de\s+"

        r"(enero|febrero|marzo|abril|mayo|junio|julio|"

        r"agosto|septiembre|setiembre|octubre|noviembre|diciembre)"

        r"(?:\s+de)?\s+(\d{4})\b",

        re.IGNORECASE

    )



    coincidencias = list(

        patron_escrito.finditer(

            texto_normalizado

        )

    )



    # --------------------------------------------------------

    # FECHA ESCRITA CON CONTEXTO

    # --------------------------------------------------------



    for coincidencia in coincidencias:



        inicio = max(

            0,

            coincidencia.start() - 150

        )



        fin = min(

            len(texto_normalizado),

            coincidencia.end() + 100

        )



        contexto = (

            texto_normalizado[

                inicio:fin

            ]

            .lower()

        )



        if (

            "la rioja" in contexto

            or "fecha" in contexto

            or "lugar" in contexto

        ):



            dia = coincidencia.group(1)



            nombre_mes = (

                coincidencia

                .group(2)

                .lower()

            )



            anio = coincidencia.group(3)



            mes = MESES.get(

                nombre_mes

            )



            if mes:



                fecha = normalizar_fecha(

                    dia,

                    mes,

                    anio

                )



                if fecha:

                    return fecha



    # --------------------------------------------------------

    # PRIMERA FECHA ESCRITA

    # --------------------------------------------------------



    if coincidencias:



        coincidencia = coincidencias[0]



        dia = coincidencia.group(1)



        nombre_mes = (

            coincidencia

            .group(2)

            .lower()

        )



        anio = coincidencia.group(3)



        mes = MESES.get(

            nombre_mes

        )



        if mes:



            fecha = normalizar_fecha(

                dia,

                mes,

                anio

            )



            if fecha:

                return fecha



    # --------------------------------------------------------

    # FECHAS NUMÉRICAS

    # --------------------------------------------------------



    patron_numerico = re.compile(

        r"\b(\d{1,2})[\\/.-]"

        r"(\d{1,2})[\\/.-]"

        r"(\d{4})\b"

    )



    coincidencias = list(

        patron_numerico.finditer(

            texto_normalizado

        )

    )



    # --------------------------------------------------------

    # FECHA NUMÉRICA CON CONTEXTO

    # --------------------------------------------------------



    for coincidencia in coincidencias:



        inicio = max(

            0,

            coincidencia.start() - 150

        )



        fin = min(

            len(texto_normalizado),

            coincidencia.end() + 100

        )



        contexto = (

            texto_normalizado[

                inicio:fin

            ]

            .lower()

        )



        if (

            "la rioja" in contexto

            or "fecha" in contexto

            or "lugar" in contexto

        ):



            dia = coincidencia.group(1)

            mes = coincidencia.group(2)

            anio = coincidencia.group(3)



            fecha = normalizar_fecha(

                dia,

                mes,

                anio

            )



            if fecha:

                return fecha



    # --------------------------------------------------------

    # PRIMERA FECHA NUMÉRICA

    # --------------------------------------------------------



    for coincidencia in coincidencias:



        dia = coincidencia.group(1)

        mes = coincidencia.group(2)

        anio = coincidencia.group(3)



        fecha = normalizar_fecha(

            dia,

            mes,

            anio

        )



        if fecha:

            return fecha



    return None





# ============================================================

# LIMPIAR TEXTO

# ============================================================



def limpiar_texto(texto):



    if not texto:

        return ""



    texto = texto.replace(

        "\r",

        "\n"

    )



    texto = re.sub(

        r"[ \t]+",

        " ",

        texto

    )



    texto = re.sub(

        r"\n\s*\n\s*\n+",

        "\n\n",

        texto

    )



    return texto.strip()





# ============================================================

# GENERAR RESUMEN PROVISIONAL

# ============================================================



def generar_resumen(texto):



    """

    Genera un resumen local provisional.



    Esta función será reemplazada posteriormente por

    un modelo de IA local capaz de comprender el contenido

    completo del documento.

    """



    if not texto:



        return (

            "No se puede generar un resumen porque "

            "el documento no contiene texto extraíble."

        )



    texto_limpio = limpiar_texto(

        texto

    )



    if not texto_limpio:



        return (

            "No se puede generar un resumen porque "

            "el documento no contiene texto extraíble."

        )



    # --------------------------------------------------------

    # Convertir el contenido en oraciones

    # --------------------------------------------------------



    texto_plano = re.sub(

        r"\s+",

        " ",

        texto_limpio

    ).strip()



    oraciones = re.split(

        r"(?<=[.!?])\s+",

        texto_plano

    )



    oraciones_limpias = []



    for oracion in oraciones:



        oracion = oracion.strip()



        if len(oracion) < 20:

            continue



        oraciones_limpias.append(

            oracion

        )



    if not oraciones_limpias:



        resumen = texto_plano[:700]



        if len(texto_plano) > 700:



            resumen = (

                resumen

                .rsplit(

                    " ",

                    1

                )[0]

                + "..."

            )



        return resumen



    # --------------------------------------------------------

    # Palabras que indican información importante

    # --------------------------------------------------------



    palabras_clave = [



        "elevar",

        "eleva",

        "elevación",



        "solicitar",

        "solicita",

        "solicitud",



        "informar",

        "informa",

        "informe",



        "remitir",

        "remite",



        "presentar",

        "presenta",

        "presentación",



        "listado",

        "nómina",

        "nomina",



        "cobro",

        "pago",



        "incentivo",

        "provincial",

        "educativo",



        "municipal",



        "expediente",



        "nota",



        "pedido",



        "documentación",

        "documentacion",

    ]



    # --------------------------------------------------------

    # Puntuar oraciones

    # --------------------------------------------------------



    oraciones_puntuadas = []



    for indice, oracion in enumerate(

        oraciones_limpias

    ):



        minuscula = (

            oracion.lower()

        )



        puntuacion = 0



        for palabra in palabras_clave:



            if palabra in minuscula:

                puntuacion += 2



        if indice < 3:

            puntuacion += 2



        if len(oracion) > 500:

            puntuacion -= 1



        oraciones_puntuadas.append(

            (

                puntuacion,

                indice,

                oracion

            )

        )



    # --------------------------------------------------------

    # Seleccionar las más relevantes

    # --------------------------------------------------------



    oraciones_puntuadas.sort(

        key=lambda x: (

            -x[0],

            x[1]

        )

    )



    seleccionadas = (

        oraciones_puntuadas[:3]

    )



    seleccionadas.sort(

        key=lambda x: x[1]

    )



    resumen_partes = [

        item[2]

        for item in seleccionadas

    ]



    resumen = " ".join(

        resumen_partes

    )



    resumen = re.sub(

        r"\s+",

        " ",

        resumen

    ).strip()



    if len(resumen) > 900:



        resumen = (

            resumen[:900]

            .rsplit(

                " ",

                1

            )[0]

            + "..."

        )



    return resumen





# ============================================================

# VISTA PREVIA

# ============================================================



def preparar_vista_previa(

    texto,

    cantidad=120

):



    if not texto:

        return "Sin texto extraído"



    texto = limpiar_texto(

        texto

    )



    if len(texto) <= cantidad:

        return texto



    return (

        texto[:cantidad]

        .rsplit(

            " ",

            1

        )[0]

        + "..."

    )





# ============================================================

# VENTANA PRINCIPAL

# ============================================================



class DocuCentral(QMainWindow):



    def __init__(self):



        super().__init__()



        self.setWindowTitle(

            "DocuCentral"

        )



        self.resize(

            1500,

            850

        )



        self.documentos_actuales = []
        self.carpeta_actual_id = None
        self.seguridad = GestorSeguridad(DATA_DIR)
        self._temporary_files = []
        self.correo_cuenta_activa = ""

        # Limpieza de seguridad al iniciar.
        try:
            self.seguridad.limpiar_archivos_temporales()
        except ErrorSeguridad:
            pass

        self.limpiar_temporales_pdf_antiguos()

        self.crear_interfaz()
        self.cargar_arbol_carpetas()

        self.cargar_documentos()



    # ========================================================

    # INTERFAZ

    # ========================================================



    def crear_interfaz(self):

        # La cuenta de usuario es independiente de la configuración criptográfica
        # local: cambiar de cuenta nunca modifica la contraseña maestra ni el correo
        # de recuperación asociado a los PDF protegidos.
        menu_cuenta = self.menuBar().addMenu("Cuenta")
        accion_cambiar_cuenta = menu_cuenta.addAction("Cerrar sesión / Cambiar cuenta…")
        accion_cambiar_cuenta.triggered.connect(self.cerrar_sesion_y_cambiar_cuenta)
        accion_eliminar_cuenta = menu_cuenta.addAction("Eliminar cuenta definitivamente…")
        accion_eliminar_cuenta.triggered.connect(self._eliminar_cuenta_desde_menu)
        menu_cuenta.addSeparator()
        menu_organizacion = self.menuBar().addMenu("Organización")
        accion_organizacion = menu_organizacion.addAction("Organización y equipos…")
        accion_organizacion.triggered.connect(self._abrir_gestion_organizacion)
        accion_salir = menu_cuenta.addAction("Salir de DocuCentral")
        accion_salir.triggered.connect(self.close)

        # Contenedor desplazable de toda la pantalla principal.
        # Permite recorrer verticalmente la interfaz cuando la ventana no
        # tiene suficiente altura para mostrar toda la información.
        widget_principal = QWidget()

        self.scroll_principal = QScrollArea()
        self.scroll_principal.setObjectName("scrollPrincipal")
        self.scroll_principal.setWidgetResizable(True)
        self.scroll_principal.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_principal.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_principal.setWidget(widget_principal)

        self.setCentralWidget(

            self.scroll_principal

        )



        layout_principal = QVBoxLayout(

            widget_principal

        )



        layout_principal.setContentsMargins(

            12,

            10,

            12,

            10

        )



        layout_principal.setSpacing(

            8

        )



        # ----------------------------------------------------
        # LOGO COMPLETO DE DOCUCENTRAL
        # ----------------------------------------------------

        encabezado_titulo = QHBoxLayout()
        encabezado_titulo.setContentsMargins(4, 2, 0, 0)
        encabezado_titulo.setSpacing(10)

        self.logo_titulo = QLabel()
        self.logo_titulo.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        pixmap_logo_completo = QPixmap(str(LOGO_DOCUCENTRAL_COMPLETO))
        if not pixmap_logo_completo.isNull():
            pixmap_completo_escalado = pixmap_logo_completo.scaledToHeight(
                48,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.logo_titulo.setPixmap(pixmap_completo_escalado)
            self.logo_titulo.setFixedSize(pixmap_completo_escalado.size())
        else:
            # Respaldo si el logo completo no se encuentra: mantiene el título legible.
            self.logo_titulo.setText("DocuCentral")
            self.logo_titulo.setStyleSheet(
                "color: #ffffff; font-size: 28px; font-weight: bold; padding: 6px;"
            )
        encabezado_titulo.addWidget(self.logo_titulo, 0, Qt.AlignmentFlag.AlignVCenter)
        encabezado_titulo.addStretch()
        layout_principal.addLayout(encabezado_titulo)


        # DESCRIPCIÓN

        # ----------------------------------------------------



        descripcion = QLabel(

            "Gestión inteligente de documentos"

        )



        descripcion.setStyleSheet(

            """

            QLabel {

                color: #b8b8b8;

                font-size: 14px;

                padding-left: 8px;

                padding-bottom: 4px;

            }

            """

        )



        layout_principal.addWidget(

            descripcion

        )



        # BUSCADOR

        # ----------------------------------------------------



        layout_busqueda = QHBoxLayout()



        layout_busqueda.setSpacing(

            6

        )



        self.campo_busqueda = QLineEdit()



        self.campo_busqueda.setPlaceholderText(

            "Buscar por nombre, contenido, resumen, fecha o ruta..."

        )



        self.campo_busqueda.setMinimumHeight(

            38

        )



        self.boton_buscar = QPushButton(

            "🔍 Buscar"

        )



        self.boton_buscar.setMinimumHeight(

            38

        )



        self.boton_limpiar_busqueda = QPushButton(

            "✖ Limpiar"

        )



        self.boton_limpiar_busqueda.setMinimumHeight(

            38

        )



        self.filtro_tipo = ComboBoxVisible()



        self.filtro_tipo.addItems([

            "Todos",

            "Normales",

            "Sensibles",

        ])



        self.filtro_tipo.setMinimumHeight(

            38

        )



        layout_busqueda.addWidget(

            self.campo_busqueda,

            1

        )



        layout_busqueda.addWidget(

            self.boton_buscar

        )



        layout_busqueda.addWidget(

            self.boton_limpiar_busqueda

        )



        layout_busqueda.addWidget(

            self.filtro_tipo

        )



        layout_principal.addLayout(

            layout_busqueda

        )



        # ----------------------------------------------------

        # BOTONES

        # ----------------------------------------------------



        layout_botones = QHBoxLayout()



        layout_botones.setSpacing(

            6

        )



        self.boton_agregar_pdf = QPushButton(

            "Agregar PDF"

        )


        self.boton_agregar_pdf_carpeta = QPushButton(

            "Agregar PDF a carpeta"

        )


        self.boton_agregar_carpeta = QPushButton(

            "Agregar carpeta"

        )



        self.boton_actualizar = QPushButton(

            "Actualizar"

        )



        self.boton_bloquear = QPushButton(

            "🔒 Bloquear seleccionados"

        )



        self.boton_desbloquear = QPushButton(

            "🔓 Desbloquear seleccionados"

        )



        self.boton_recuperar = QPushButton(

            "🔑 Recuperar contraseña"

        )



        self.boton_eliminar = QPushButton(

            "Eliminar seleccionados"

        )



        for boton in [

            self.boton_agregar_pdf,
            self.boton_agregar_pdf_carpeta,

            self.boton_agregar_carpeta,

            self.boton_actualizar,

            self.boton_bloquear,

            self.boton_desbloquear,

            self.boton_eliminar,

        ]:



            boton.setMinimumHeight(

                36

            )



        layout_botones.addWidget(

            self.boton_agregar_pdf

        )


        layout_botones.addWidget(

            self.boton_agregar_pdf_carpeta

        )


        layout_botones.addWidget(

            self.boton_agregar_carpeta

        )



        layout_botones.addWidget(

            self.boton_actualizar

        )



        layout_botones.addWidget(

            self.boton_bloquear

        )



        layout_botones.addWidget(

            self.boton_desbloquear

        )



        layout_botones.addWidget(

            self.boton_recuperar

        )



        layout_botones.addWidget(

            self.boton_eliminar

        )



        layout_botones.addStretch()



        layout_principal.addLayout(

            layout_botones

        )



        # ----------------------------------------------------

        # CONTADOR DE RESULTADOS

        # ----------------------------------------------------



        self.label_resultados = QLabel(

            "Documentos: 0"

        )



        self.label_resultados.setStyleSheet(

            """

            QLabel {

                color: #ffffff;

                padding: 4px;

                font-weight: bold;

            }

            """

        )



        layout_principal.addWidget(

            self.label_resultados

        )



        # ----------------------------------------------------

        # CONTADOR DE SELECCIÓN

        # ----------------------------------------------------



        self.label_seleccion = QLabel(

            "0 documentos seleccionados"

        )



        self.label_seleccion.setStyleSheet(

            """

            QLabel {

                color: #b8b8b8;

                padding: 3px 4px;

                font-weight: bold;

            }

            """

        )



        layout_principal.addWidget(

            self.label_seleccion

        )



        # ----------------------------------------------------

        # TABLA

        # ----------------------------------------------------



        self.tabla = QTableWidget()



        self.tabla.setColumnCount(

            9

        )



        self.tabla.setHorizontalHeaderLabels([

            "Documento",

            "Tipo",

            "Fecha documento",

            "Fecha de carga",

            "Páginas",

            "Resumen",

            "Texto extraído",

            "Ruta",

            "ID",

        ])



        self.tabla.setSelectionMode(

            QAbstractItemView.SelectionMode.ExtendedSelection

        )



        self.tabla.setSelectionBehavior(

            QAbstractItemView.SelectionBehavior.SelectRows

        )



        self.tabla.setEditTriggers(

            QAbstractItemView.EditTrigger.NoEditTriggers

        )



        self.tabla.setAlternatingRowColors(

            True

        )



        self.tabla.setWordWrap(

            True

        )



        self.tabla.setSortingEnabled(

            True

        )



        # ----------------------------------------------------

        # ALTURA MANUAL DE FILAS

        # ----------------------------------------------------



        encabezado_vertical = (

            self.tabla.verticalHeader()

        )



        encabezado_vertical.setDefaultSectionSize(

            55

        )



        encabezado_vertical.setMinimumSectionSize(

            25

        )



        encabezado_vertical.setSectionResizeMode(

            QHeaderView.ResizeMode.Interactive

        )



        # ----------------------------------------------------

        # ENCABEZADOS HORIZONTALES

        # ----------------------------------------------------



        encabezado = (

            self.tabla.horizontalHeader()

        )



        encabezado.setSectionResizeMode(

            0,

            QHeaderView.ResizeMode.Interactive

        )



        encabezado.setSectionResizeMode(

            1,

            QHeaderView.ResizeMode.Interactive

        )



        encabezado.setSectionResizeMode(

            2,

            QHeaderView.ResizeMode.Interactive

        )



        encabezado.setSectionResizeMode(

            3,

            QHeaderView.ResizeMode.Interactive

        )



        encabezado.setSectionResizeMode(

            4,

            QHeaderView.ResizeMode.Interactive

        )



        encabezado.setSectionResizeMode(

            5,

            QHeaderView.ResizeMode.Interactive

        )



        encabezado.setSectionResizeMode(

            6,

            QHeaderView.ResizeMode.Interactive

        )



        encabezado.setSectionResizeMode(

            7,

            QHeaderView.ResizeMode.Interactive

        )



        encabezado.setSectionResizeMode(

            8,

            QHeaderView.ResizeMode.Interactive

        )



        # Anchos iniciales



        encabezado.resizeSection(

            0,

            260

        )



        encabezado.resizeSection(

            1,

            110

        )



        encabezado.resizeSection(

            2,

            130

        )



        encabezado.resizeSection(

            3,

            155

        )



        encabezado.resizeSection(

            4,

            75

        )



        encabezado.resizeSection(

            5,

            420

        )



        encabezado.resizeSection(

            6,

            300

        )



        encabezado.resizeSection(

            7,

            450

        )



        encabezado.resizeSection(

            8,

            55

        )



        # ----------------------------------------------------

        # DETALLE

        # ----------------------------------------------------



        # ----------------------------------------------------
        # PANEL DE DETALLE
        # ----------------------------------------------------

        self.detalle = QWidget()
        self.detalle_layout = QVBoxLayout(self.detalle)
        self.detalle_layout.setContentsMargins(12, 12, 12, 12)
        self.detalle_layout.setSpacing(10)

        self.detalle_titulo = QLabel("Detalle del documento")
        self.detalle_titulo.setObjectName("detalleTitulo")
        self.detalle_layout.addWidget(self.detalle_titulo)

        self.detalle_contenido = QFrame()
        self.detalle_contenido.setObjectName("detalleContenido")
        contenido_layout = QVBoxLayout(self.detalle_contenido)
        contenido_layout.setContentsMargins(14, 14, 14, 14)
        contenido_layout.setSpacing(10)

        # ----------------------------------------------------
        # INFORMACION + RESUMEN
        # ----------------------------------------------------
        self.detalle_superior = QWidget()
        superior_layout = QVBoxLayout(self.detalle_superior)
        superior_layout.setContentsMargins(0, 0, 0, 0)
        superior_layout.setSpacing(12)
        self.detalle_superior.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum
        )

        self.detalle_info = QFrame()
        self.detalle_info.setObjectName("detalleCardPlano")
        self.detalle_info.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum
        )
        info_layout = QVBoxLayout(self.detalle_info)
        info_layout.setContentsMargins(18, 18, 18, 18)
        info_layout.setSpacing(10)

        info_titulo = QLabel("INFORMACIÓN DEL DOCUMENTO")
        info_titulo.setObjectName("detalleSeccion")
        info_layout.addWidget(info_titulo)

        info_grid = QGridLayout()
        info_grid.setContentsMargins(0, 0, 0, 0)
        info_grid.setHorizontalSpacing(10)
        info_grid.setVerticalSpacing(10)

        self.detalle_nombre = QLabel("Documento: —")
        self.detalle_tipo = QLabel("Tipo: —")
        self.detalle_fecha = QLabel("Fecha del documento: —")
        self.detalle_carga = QLabel("Fecha de carga: —")
        self.detalle_paginas = QLabel("Páginas: —")
        self.detalle_caracteres = QLabel("Caracteres extraídos: —")

        etiquetas = [
            self.detalle_nombre,
            self.detalle_tipo,
            self.detalle_fecha,
            self.detalle_carga,
            self.detalle_paginas,
            self.detalle_caracteres,
        ]

        for etiqueta in etiquetas:
            etiqueta.setObjectName("detalleInfoItem")
            etiqueta.setWordWrap(True)
            etiqueta.setMinimumHeight(52)
            etiqueta.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )

        info_grid.addWidget(self.detalle_nombre, 0, 0)
        info_grid.addWidget(self.detalle_tipo, 0, 1)
        info_grid.addWidget(self.detalle_fecha, 1, 0)
        info_grid.addWidget(self.detalle_carga, 1, 1)
        info_grid.addWidget(self.detalle_paginas, 2, 0)
        info_grid.addWidget(self.detalle_caracteres, 2, 1)
        info_grid.setColumnStretch(0, 1)
        info_grid.setColumnStretch(1, 1)

        info_layout.addLayout(info_grid)
        superior_layout.addWidget(self.detalle_info)

        self.detalle_resumen_card = QFrame()
        self.detalle_resumen_card.setObjectName("detalleCardPlano")
        self.detalle_resumen_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum
        )
        resumen_layout = QVBoxLayout(self.detalle_resumen_card)
        resumen_layout.setContentsMargins(18, 18, 18, 18)
        resumen_layout.setSpacing(10)

        resumen_titulo = QLabel("RESUMEN")
        resumen_titulo.setObjectName("detalleSeccion")
        resumen_layout.addWidget(resumen_titulo)

        self.detalle_resumen = QLabel("Seleccioná un documento para ver su información.")
        self.detalle_resumen.setObjectName("detalleResumenTexto")
        self.detalle_resumen.setProperty("placeholder", True)
        self.detalle_resumen.setWordWrap(True)
        self.detalle_resumen.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        resumen_layout.addWidget(self.detalle_resumen)
        superior_layout.addWidget(self.detalle_resumen_card)

        # ----------------------------------------------------
        # CONTENIDO DEL DETALLE
        # ----------------------------------------------------
        # El detalle forma parte del contenido desplazable PRINCIPAL.
        # No usamos otro splitter que pueda sacar el texto fuera del
        # recorrido de la ventana. Cada tarjeta conserva su altura y
        # el scroll principal recorre todo el conjunto.

        self.detalle_texto_card = QFrame()
        self.detalle_texto_card.setObjectName("detalleCard")
        texto_layout = QVBoxLayout(self.detalle_texto_card)
        texto_layout.setContentsMargins(18, 18, 18, 18)
        texto_layout.setSpacing(10)

        texto_titulo = QLabel("TEXTO EXTRAÍDO")
        texto_titulo.setObjectName("detalleSeccion")
        texto_layout.addWidget(texto_titulo)

        self.detalle_texto = QTextEdit()
        self.detalle_texto.setObjectName("detalleTextoDocumento")
        self.detalle_texto.setReadOnly(True)
        # Altura inicial pequeña; después se ajusta automáticamente al contenido.
        self.detalle_texto.setMinimumHeight(0)
        self.detalle_texto.setFixedHeight(220)
        self.detalle_texto.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.detalle_texto.setPlaceholderText("Texto extraído del PDF...")
        texto_layout.addWidget(self.detalle_texto, 1)

        # El detalle completo tiene una altura real dentro del scroll principal.
        # Así la tarjeta de texto tiene comienzo Y final visibles al desplazarse.
        # Sin altura mínima artificial: INFORMACIÓN y RESUMEN ocupan solo el espacio real de su contenido.
        self.detalle_superior.setMinimumHeight(0)
        self.detalle_texto_card.setMinimumHeight(0)
        self.detalle_texto_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum
        )

        contenido_layout.addWidget(self.detalle_superior, 0)
        contenido_layout.addSpacing(0)
        contenido_layout.addWidget(self.detalle_texto_card, 0)
        contenido_layout.addSpacing(24)

        self.detalle_layout.addWidget(self.detalle_contenido, 0)
        self.detalle.setMinimumHeight(0)
        self.tabla.setMinimumHeight(300)

        self.splitter = QSplitter(

            Qt.Orientation.Vertical

        )



        self.splitter.setChildrenCollapsible(

            False

        )

        # Conservamos una altura amplia para que tabla y detalle no se
        # compriman. El scroll principal permite recorrer toda la interfaz.
        self.splitter.setMinimumHeight(0)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 0)



        self.splitter.setHandleWidth(

            16

        )



        self.panel_documentos = QWidget()
        panel_documentos_layout = QHBoxLayout(self.panel_documentos)
        panel_documentos_layout.setContentsMargins(0, 0, 0, 0)
        panel_documentos_layout.setSpacing(8)

        self.panel_carpetas = QFrame()
        self.panel_carpetas.setObjectName("panelCarpetas")
        carpetas_layout = QVBoxLayout(self.panel_carpetas)
        carpetas_layout.setContentsMargins(10, 10, 10, 10)
        carpetas_layout.setSpacing(7)

        titulo_carpetas = QLabel("CARPETAS")
        titulo_carpetas.setObjectName("tituloCarpetas")
        carpetas_layout.addWidget(titulo_carpetas)

        self.arbol_carpetas = QTreeWidget()
        self.arbol_carpetas.setObjectName("arbolCarpetas")
        self.arbol_carpetas.setHeaderHidden(True)
        self.arbol_carpetas.setAnimated(True)
        self.arbol_carpetas.setIndentation(18)
        self.arbol_carpetas.setMinimumWidth(220)
        self.arbol_carpetas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.arbol_carpetas.itemClicked.connect(self.seleccionar_carpeta)
        carpetas_layout.addWidget(self.arbol_carpetas, 1)

        botones_carpetas = QHBoxLayout()
        botones_carpetas.setSpacing(5)
        self.boton_nueva_carpeta = QPushButton("+")
        self.boton_nueva_carpeta.setToolTip("Nueva carpeta")
        self.boton_nueva_subcarpeta = QPushButton("↳+")
        self.boton_nueva_subcarpeta.setToolTip("Nueva subcarpeta")
        self.boton_renombrar_carpeta = QPushButton("✎")
        self.boton_renombrar_carpeta.setToolTip("Renombrar carpeta")
        self.boton_eliminar_carpeta = QPushButton("🗑")
        self.boton_eliminar_carpeta.setToolTip("Eliminar carpeta")
        for b in [self.boton_nueva_carpeta, self.boton_nueva_subcarpeta, self.boton_renombrar_carpeta, self.boton_eliminar_carpeta]:
            b.setMinimumHeight(32)
            botones_carpetas.addWidget(b)
        carpetas_layout.addLayout(botones_carpetas)

        panel_documentos_layout.addWidget(self.panel_carpetas, 0)
        panel_documentos_layout.addWidget(self.tabla, 1)
        self.splitter.addWidget(self.panel_documentos)

        self.boton_agregar_pdf_carpeta.clicked.connect(self.agregar_pdf_a_carpeta)
        self.boton_nueva_carpeta.clicked.connect(self.crear_carpeta_virtual)
        self.boton_nueva_subcarpeta.clicked.connect(self.crear_subcarpeta_virtual)
        self.boton_renombrar_carpeta.clicked.connect(self.renombrar_carpeta)
        self.boton_eliminar_carpeta.clicked.connect(self.eliminar_carpeta)

        self.splitter.addWidget(

            self.detalle

        )



        # Altura inicial:

        # tabla grande + detalle más pequeño



        self.splitter.setSizes([

            300,

            700

        ])

        QTimer.singleShot(0, self.ajustar_altura_panel_detalle)



        layout_principal.addWidget(

            self.splitter

        )



        # ----------------------------------------------------

        # EVENTOS

        # ----------------------------------------------------



        self.boton_agregar_pdf.clicked.connect(

            self.agregar_pdf

        )

        self.boton_agregar_pdf_carpeta.clicked.connect(

            self.agregar_documentos_marcados_a_carpeta

        )



        self.boton_agregar_carpeta.clicked.connect(

            self.agregar_carpeta

        )



        self.boton_actualizar.clicked.connect(

            self.cargar_documentos

        )



        self.boton_eliminar.clicked.connect(

            self.eliminar_seleccionados

        )



        self.boton_buscar.clicked.connect(

            self.buscar_documentos

        )



        self.boton_limpiar_busqueda.clicked.connect(

            self.limpiar_busqueda

        )



        self.campo_busqueda.returnPressed.connect(

            self.buscar_documentos

        )



        self.filtro_tipo.currentIndexChanged.connect(

            self.buscar_documentos

        )



        self.tabla.itemSelectionChanged.connect(

            self.mostrar_documento_seleccionado

        )



        self.tabla.cellDoubleClicked.connect(

            self.abrir_documento

        )



        self.boton_bloquear.clicked.connect(

            self.bloquear_seleccionados

        )



        self.boton_desbloquear.clicked.connect(

            self.desbloquear_seleccionados

        )



        self.boton_recuperar.clicked.connect(

            self.recuperar_contrasena

        )



    # ========================================================

    # BÚSQUEDA

    # ========================================================



    def buscar_documentos(self):



        termino = (

            self.campo_busqueda

            .text()

            .strip()

        )



        tipo = (

            self.filtro_tipo

            .currentText()

        )



        conexion = conectar_db()

        cursor = conexion.cursor()



        consulta = """

            SELECT

                id,

                nombre,

                ruta,

                ruta_original,

                fecha_carga,

                paginas,

                texto,

                fecha_documento,

                resumen,

                sensible

            FROM documentos

            WHERE 1 = 1

        """



        parametros = []



        # ----------------------------------------------------

        # BUSCAR TEXTO

        # ----------------------------------------------------



        if termino:



            patron = f"%{termino}%"



            consulta += """

                AND (

                    nombre LIKE ?

                    OR ruta LIKE ?

                    OR texto LIKE ?

                    OR fecha_documento LIKE ?

                    OR fecha_carga LIKE ?

                    OR resumen LIKE ?

                )

            """



            parametros.extend([

                patron,

                patron,

                patron,

                patron,

                patron,

                patron,

            ])



        # ----------------------------------------------------

        # FILTRO DE TIPO

        # ----------------------------------------------------



        if tipo == "Normales":



            consulta += """

                AND sensible = 0

            """



        elif tipo == "Sensibles":



            consulta += """

                AND sensible = 1

            """



        if self.carpeta_actual_id is not None:
            if self.carpeta_actual_id == -1:
                consulta += " AND carpeta_id IS NULL "
            else:
                consulta += " AND carpeta_id = ? "
                parametros.append(self.carpeta_actual_id)

        consulta += """

            ORDER BY id DESC

        """



        cursor.execute(

            consulta,

            parametros

        )



        documentos = cursor.fetchall()



        conexion.close()



        self.mostrar_documentos(

            documentos

        )



        if termino:



            self.label_resultados.setText(

                f"Resultados encontrados: "

                f"{len(documentos)}"

            )



        else:



            self.label_resultados.setText(

                f"Documentos: "

                f"{len(documentos)}"

            )



    def limpiar_busqueda(self):



        self.campo_busqueda.clear()



        self.filtro_tipo.setCurrentIndex(

            0

        )



        self.cargar_documentos()



    # ========================================================

    # CARPETAS Y SUBCARPETAS

    def cargar_arbol_carpetas(self):
        if not hasattr(self, "arbol_carpetas"):
            return
        self.arbol_carpetas.blockSignals(True)
        self.arbol_carpetas.clear()
        todos = QTreeWidgetItem(["📚 Todos los documentos"])
        todos.setData(0, Qt.ItemDataRole.UserRole, None)
        self.arbol_carpetas.addTopLevelItem(todos)
        sin = QTreeWidgetItem(["📄 Sin carpeta"])
        sin.setData(0, Qt.ItemDataRole.UserRole, -1)
        self.arbol_carpetas.addTopLevelItem(sin)
        conexion = conectar_db(); cursor = conexion.cursor()
        cursor.execute("SELECT id, nombre, padre_id FROM carpetas ORDER BY nombre COLLATE NOCASE")
        filas = cursor.fetchall(); conexion.close()
        nodos = {}
        pendientes = list(filas)
        while pendientes:
            progreso = False
            for fila in pendientes[:]:
                carpeta_id, nombre, padre_id = fila
                if padre_id is None:
                    padre = self.arbol_carpetas.invisibleRootItem()
                elif padre_id in nodos:
                    padre = nodos[padre_id]
                else:
                    continue
                item = QTreeWidgetItem([f"📁 {nombre}"])
                item.setData(0, Qt.ItemDataRole.UserRole, carpeta_id)
                padre.addChild(item); nodos[carpeta_id] = item
                pendientes.remove(fila); progreso = True
            if not progreso:
                break
        self.arbol_carpetas.expandAll()
        self.arbol_carpetas.blockSignals(False)

    def seleccionar_carpeta(self, item, columna=0):
        self.carpeta_actual_id = item.data(0, Qt.ItemDataRole.UserRole)
        self.cargar_documentos()

    def _carpeta_seleccionada_id(self):
        item = self.arbol_carpetas.currentItem()
        return item.data(0, Qt.ItemDataRole.UserRole) if item else None

    def crear_carpeta_virtual(self):
        nombre, ok = QInputDialog.getText(self, "Nueva carpeta", "Nombre de la carpeta:")
        if not ok or not nombre.strip(): return
        conexion = conectar_db(); cursor = conexion.cursor()
        try:
            cursor.execute("INSERT INTO carpetas (nombre, padre_id, fecha_creacion) VALUES (?, NULL, ?)", (nombre.strip(), datetime.now().strftime("%d/%m/%Y %H:%M:%S")))
            conexion.commit()
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Carpeta", "Ya existe una carpeta con ese nombre.")
        finally: conexion.close()
        self.cargar_arbol_carpetas()

    def crear_subcarpeta_virtual(self):
        padre_id = self._carpeta_seleccionada_id()
        if padre_id in (None, -1):
            QMessageBox.information(self, "Subcarpeta", "Seleccioná primero una carpeta."); return
        nombre, ok = QInputDialog.getText(self, "Nueva subcarpeta", "Nombre de la subcarpeta:")
        if not ok or not nombre.strip(): return
        conexion = conectar_db(); cursor = conexion.cursor()
        try:
            cursor.execute("INSERT INTO carpetas (nombre, padre_id, fecha_creacion) VALUES (?, ?, ?)", (nombre.strip(), padre_id, datetime.now().strftime("%d/%m/%Y %H:%M:%S")))
            conexion.commit()
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Subcarpeta", "Ya existe una subcarpeta con ese nombre.")
        finally: conexion.close()
        self.cargar_arbol_carpetas()

    def renombrar_carpeta(self):
        carpeta_id = self._carpeta_seleccionada_id()
        if carpeta_id in (None, -1):
            QMessageBox.information(self, "Carpeta", "Seleccioná una carpeta para renombrarla."); return
        conexion = conectar_db(); cursor = conexion.cursor(); cursor.execute("SELECT nombre FROM carpetas WHERE id=?", (carpeta_id,)); fila = cursor.fetchone(); conexion.close()
        if not fila: return
        nombre, ok = QInputDialog.getText(self, "Renombrar carpeta", "Nuevo nombre:", text=fila[0])
        if not ok or not nombre.strip(): return
        conexion = conectar_db(); cursor = conexion.cursor()
        try:
            cursor.execute("UPDATE carpetas SET nombre=? WHERE id=?", (nombre.strip(), carpeta_id)); conexion.commit()
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Carpeta", "Ya existe una carpeta con ese nombre en ese nivel.")
        finally: conexion.close()
        self.cargar_arbol_carpetas()

    def eliminar_carpeta(self):
        carpeta_id = self._carpeta_seleccionada_id()
        if carpeta_id in (None, -1):
            QMessageBox.information(self, "Carpeta", "Seleccioná una carpeta para eliminarla."); return
        respuesta = QMessageBox.question(self, "Eliminar carpeta", "La carpeta y sus subcarpetas se eliminarán de DocuCentral.\n\nLos PDF físicos NO se eliminarán.\n\n¿Continuar?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if respuesta != QMessageBox.StandardButton.Yes: return
        conexion = conectar_db(); cursor = conexion.cursor()
        cursor.execute("UPDATE documentos SET carpeta_id=NULL WHERE carpeta_id=?", (carpeta_id,))
        cursor.execute("DELETE FROM carpetas WHERE id=?", (carpeta_id,)); conexion.commit(); conexion.close()
        self.carpeta_actual_id = None; self.cargar_arbol_carpetas(); self.cargar_documentos()

    # AGREGAR PDF

    # ========================================================



    def _filas_marcadas_documentos(self):
        marcadas=[]
        for fila in range(self.tabla.rowCount()):
            widget=self.tabla.cellWidget(fila,0)
            if widget is not None:
                checkbox=widget.findChild(QCheckBox)
                if checkbox is not None and checkbox.isChecked(): marcadas.append(fila)
        return [self.documentos_actuales[fila] for fila in marcadas if 0 <= fila < len(self.documentos_actuales)]

    def actualizar_marcados(self):
        cantidad=len(self._filas_marcadas_documentos())
        self.label_seleccion.setText(f"{cantidad} documento{'s' if cantidad != 1 else ''} marcado{'s' if cantidad != 1 else ''}")

    def _desmarcar_todos(self):
        for fila in range(self.tabla.rowCount()):
            widget=self.tabla.cellWidget(fila,0)
            if widget is not None:
                checkbox=widget.findChild(QCheckBox)
                if checkbox is not None:
                    checkbox.blockSignals(True); checkbox.setChecked(False); checkbox.blockSignals(False)
        self.actualizar_marcados()

    def agregar_documentos_marcados_a_carpeta(self):
        documentos=self._filas_marcadas_documentos()
        if not documentos:
            QMessageBox.information(self,"Agregar a carpeta","Marcá con el tilde los PDFs que querés organizar y después pulsá este botón.")
            return
        dialogo=DialogoDestinoCarpeta(self)
        if dialogo.exec() != QDialog.DialogCode.Accepted or dialogo.carpeta_id is None: return
        ids=[doc[0] for doc in documentos]
        conexion=conectar_db(); cursor=conexion.cursor(); placeholders=','.join('?' for _ in ids)
        cursor.execute(f"UPDATE documentos SET carpeta_id = ? WHERE id IN ({placeholders})",[dialogo.carpeta_id,*ids]); conexion.commit(); conexion.close()
        self._desmarcar_todos(); self.cargar_arbol_carpetas(); self.cargar_documentos()
        QMessageBox.information(self,"Documentos organizados",f"Se organizaron {len(ids)} documento{'s' if len(ids)!=1 else ''} correctamente.")

    def agregar_pdf_a_carpeta(self):
        self.agregar_documentos_marcados_a_carpeta()

    def agregar_pdf(self):



        rutas, _ = QFileDialog.getOpenFileNames(

            self,

            "Seleccionar archivos PDF",

            "",

            "Archivos PDF (*.pdf)"

        )



        if not rutas:

            return



        archivos = [

            Path(ruta)

            for ruta in rutas

        ]



        self.procesar_documentos(

            archivos

        )



    # ========================================================

    # AGREGAR CARPETA

    # ========================================================



    def agregar_carpeta(self):



        carpeta = QFileDialog.getExistingDirectory(

            self,

            "Seleccionar carpeta"

        )



        if not carpeta:

            return



        ruta_carpeta = Path(

            carpeta

        )



        archivos = list(

            ruta_carpeta.rglob(

                "*.pdf"

            )

        )



        if not archivos:



            QMessageBox.information(

                self,

                "DocuCentral",

                (

                    "No se encontraron archivos PDF "

                    "en la carpeta seleccionada."

                )

            )



            return



        self.procesar_documentos(

            archivos

        )



    # ========================================================

    # PROCESAR DOCUMENTOS

    # ========================================================



    def procesar_documentos(

        self,

        archivos,

        carpeta_id_forzosa=None

    ):



        progreso = QProgressDialog(

            "Procesando documentos...",

            "Cancelar",

            0,

            len(archivos),

            self

        )



        progreso.setWindowTitle(

            "DocuCentral"

        )



        progreso.setWindowModality(

            Qt.WindowModality.ApplicationModal

        )



        conexion = conectar_db()

        cursor = conexion.cursor()



        nuevos = 0

        actualizados = 0

        errores = 0



        for indice, archivo in enumerate(

            archivos

        ):



            if progreso.wasCanceled():

                break



            progreso.setValue(

                indice

            )



            progreso.setLabelText(

                f"Leyendo:\n{archivo.name}"

            )



            QApplication.processEvents()



            try:



                # ------------------------------------------------

                # COMPROBAR EXISTENCIA

                # ------------------------------------------------



                cursor.execute(

                    """

                    SELECT id

                    FROM documentos

                    WHERE ruta = ?

                    """,

                    (

                        str(archivo),

                    )

                )



                existente = cursor.fetchone()

                if existente and carpeta_id_forzosa is not None:
                    cursor.execute(
                        "UPDATE documentos SET carpeta_id = ? WHERE id = ?",
                        (carpeta_id_forzosa, existente[0])
                    )



                # ------------------------------------------------

                # LEER PDF

                # ------------------------------------------------



                texto, paginas = leer_pdf(

                    archivo

                )



                # ------------------------------------------------

                # FECHA

                # ------------------------------------------------



                fecha_documento = detectar_fecha(

                    texto

                )



                # ------------------------------------------------

                # RESUMEN

                # ------------------------------------------------



                resumen = generar_resumen(

                    texto

                )



                # ------------------------------------------------

                # ACTUALIZAR EXISTENTE

                # ------------------------------------------------



                if existente:



                    cursor.execute(

                        """

                        UPDATE documentos

                        SET

                            nombre = ?,

                            paginas = ?,

                            texto = ?,

                            fecha_documento = ?,

                            resumen = ?

                        WHERE ruta = ?

                        """,

                        (

                            archivo.name,

                            paginas,

                            texto,

                            fecha_documento,

                            resumen,

                            str(archivo),

                        )

                    )



                    actualizados += 1



                    continue



                # ------------------------------------------------

                # DOCUMENTO NUEVO

                # ------------------------------------------------



                fecha_carga = (

                    datetime.now()

                    .strftime(

                        "%d/%m/%Y %H:%M:%S"

                    )

                )



                cursor.execute(

                    """

                    INSERT INTO documentos

                    (

                        nombre,

                        ruta,

                        ruta_original,

                        fecha_carga,

                        paginas,

                        texto,

                        fecha_documento,

                        resumen,

                        sensible

                    )

                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

                    """,

                    (

                        archivo.name,

                        str(archivo),

                        str(archivo),

                        fecha_carga,

                        paginas,

                        texto,

                        fecha_documento,

                        resumen,

                        0,

                        carpeta_id_forzosa,

                    )

                )



                nuevos += 1



            except Exception as e:



                errores += 1



                print(

                    f"Error procesando "

                    f"{archivo}: {e}"

                )



        conexion.commit()

        conexion.close()



        progreso.setValue(

            len(archivos)

        )



        self.cargar_documentos()



        QMessageBox.information(

            self,

            "DocuCentral",

            (

                f"Proceso terminado.\n\n"

                f"Documentos nuevos: {nuevos}\n"

                f"Documentos actualizados: "

                f"{actualizados}\n"

                f"Errores: {errores}"

            )

        )



    # ========================================================

    # CARGAR DOCUMENTOS

    # ========================================================



    def cargar_documentos(self):



        conexion = conectar_db()

        cursor = conexion.cursor()



        consulta = """

            SELECT

                id,

                nombre,

                ruta,

                ruta_original,

                fecha_carga,

                paginas,

                texto,

                fecha_documento,

                resumen,

                sensible

            FROM documentos

            WHERE 1 = 1

        """



        parametros = []



        # ----------------------------------------------------
        # FILTRO POR CARPETA
        #
        # None = Todos los documentos
        # -1   = Documentos sin carpeta
        # otro = Solo documentos que pertenecen directamente
        #        a la carpeta seleccionada.
        # ----------------------------------------------------

        if self.carpeta_actual_id is not None:

            if self.carpeta_actual_id == -1:

                consulta += " AND carpeta_id IS NULL "

            else:

                consulta += " AND carpeta_id = ? "

                parametros.append(self.carpeta_actual_id)



        consulta += " ORDER BY id DESC "



        cursor.execute(

            consulta,

            parametros

        )



        documentos = cursor.fetchall()



        conexion.close()



        self.documentos_actuales = documentos



        self.mostrar_documentos(

            documentos

        )



        self.label_resultados.setText(

            f"Documentos: {len(documentos)}"

        )



    # ========================================================

    # MOSTRAR DOCUMENTOS EN TABLA

    # ========================================================



    def mostrar_documentos(

        self,

        documentos

    ):



        self.documentos_actuales = documentos



        sorting = (

            self.tabla.isSortingEnabled()

        )



        self.tabla.setSortingEnabled(

            False

        )



        self.tabla.setRowCount(

            len(documentos)

        )



        for fila, documento in enumerate(

            documentos

        ):



            (

                id_documento,

                nombre,

                ruta,

                ruta_original,

                fecha_carga,

                paginas,

                texto,

                fecha_documento,

                resumen,

                sensible,

            ) = documento



            # ------------------------------------------------

            # NOMBRE

            # ------------------------------------------------
            contenedor_nombre = QWidget()
            layout_nombre = QHBoxLayout(contenedor_nombre)
            layout_nombre.setContentsMargins(6, 0, 6, 0)
            layout_nombre.setSpacing(8)
            check = QCheckBox()
            check.setToolTip("Marcar documento para organizarlo en una carpeta")
            check.stateChanged.connect(lambda _estado, self=self: self.actualizar_marcados())
            layout_nombre.addWidget(check)
            etiqueta_nombre = QLabel(nombre or "")
            etiqueta_nombre.setWordWrap(True)
            layout_nombre.addWidget(etiqueta_nombre, 1)
            self.tabla.setCellWidget(fila, 0, contenedor_nombre)



            # ------------------------------------------------

            # TIPO

            # ------------------------------------------------



            tipo = (

                "🔒 Sensible"

                if sensible

                else "📄 Normal"

            )



            item_tipo = QTableWidgetItem(

                tipo

            )



            item_tipo.setToolTip(

                "Documento protegido"

                if sensible

                else "Documento normal"

            )



            self.tabla.setItem(

                fila,

                1,

                item_tipo

            )



            # ------------------------------------------------

            # FECHA DOCUMENTO

            # ------------------------------------------------



            self.tabla.setItem(

                fila,

                2,

                QTableWidgetItem(

                    fecha_documento

                    or

                    "No encontrada"

                )

            )



            # ------------------------------------------------

            # FECHA CARGA

            # ------------------------------------------------



            self.tabla.setItem(

                fila,

                3,

                QTableWidgetItem(

                    fecha_carga or ""

                )

            )



            # ------------------------------------------------

            # PÁGINAS

            # ------------------------------------------------



            self.tabla.setItem(

                fila,

                4,

                QTableWidgetItem(

                    str(

                        paginas or 0

                    )

                )

            )



            # ------------------------------------------------

            # RESUMEN

            # ------------------------------------------------



            if resumen:



                item_resumen = QTableWidgetItem(

                    resumen

                )



                item_resumen.setToolTip(

                    resumen

                )



            else:



                item_resumen = QTableWidgetItem(

                    "Sin resumen"

                )



            self.tabla.setItem(

                fila,

                5,

                item_resumen

            )



            # ------------------------------------------------

            # TEXTO EXTRAÍDO

            # ------------------------------------------------



            if texto:



                cantidad = len(

                    texto

                )



                vista_previa = (

                    preparar_vista_previa(

                        texto,

                        120

                    )

                )



                item_texto = QTableWidgetItem(

                    (

                        f"{cantidad:,} caracteres\n"

                        f"{vista_previa}"

                    )

                )



            else:



                item_texto = QTableWidgetItem(

                    "Sin texto extraído"

                )



            item_texto.setToolTip(

                texto

                or

                "Sin texto extraído"

            )



            self.tabla.setItem(

                fila,

                6,

                item_texto

            )



            # ------------------------------------------------

            # RUTA

            # ------------------------------------------------



            item_ruta = QTableWidgetItem(

                ruta or ""

            )



            item_ruta.setToolTip(

                ruta or ""

            )



            self.tabla.setItem(

                fila,

                7,

                item_ruta

            )



            # ------------------------------------------------

            # ID

            # ------------------------------------------------



            self.tabla.setItem(

                fila,

                8,

                QTableWidgetItem(

                    str(

                        id_documento

                    )

                )

            )



        # ----------------------------------------------------

        # IMPORTANTE:

        # NO utilizamos resizeRowsToContents().

        #

        # Las filas ahora quedan con altura manual.

        # ----------------------------------------------------



        self.tabla.setSortingEnabled(

            sorting

        )



        self.detalle_texto.clear()



        self.actualizar_contador_seleccion()



    # ========================================================

    # MOSTRAR DOCUMENTO

    # ========================================================



    def ajustar_altura_panel_detalle(self):
        """Ajusta el alto del panel tabla + detalle al contenido real, sin huecos artificiales."""
        if not hasattr(self, "splitter"):
            return

        filas = self.tabla.rowCount()
        altura_tabla = max(300, self.tabla.horizontalHeader().height() + (filas * 55 if filas else 0) + 10)
        altura_detalle = max(120, self.detalle.sizeHint().height())
        self.splitter.setFixedHeight(altura_tabla + altura_detalle + self.splitter.handleWidth())

    def ajustar_altura_texto_extraido(self, altura_inicial=220):
        """Ajusta automáticamente la altura del cuadro de texto al contenido.

        Al iniciar, o cuando no hay un documento seleccionado, mantiene un
        espacio pequeño y útil. Cuando se carga un PDF, el cuadro crece hasta
        contener todo el texto y el scroll principal de DocuCentral se encarga
        del desplazamiento del documento completo.
        """
        if not hasattr(self, "detalle_texto"):
            return

        texto = self.detalle_texto.toPlainText().strip()
        if not texto:
            self.detalle_texto.setFixedHeight(altura_inicial)
            return

        viewport_width = self.detalle_texto.viewport().width()
        if viewport_width <= 0:
            QTimer.singleShot(0, self.ajustar_altura_texto_extraido)
            return

        documento = self.detalle_texto.document()
        documento.setTextWidth(viewport_width)
        documento.documentLayout().documentSize()
        altura_documento = documento.documentLayout().documentSize().height()

        # Pequeño margen para que el último renglón no quede pegado al borde.
        altura = max(altura_inicial, int(altura_documento + 18))
        self.detalle_texto.setFixedHeight(altura)
        self.detalle_texto_card.adjustSize()
        self.detalle_contenido.adjustSize()

    def actualizar_resumen_detalle(self, texto, placeholder=False):
        """Actualiza el resumen y diferencia visualmente el texto placeholder."""
        self.detalle_resumen.setText(texto)
        self.detalle_resumen.setProperty("placeholder", placeholder)
        self.detalle_resumen.style().unpolish(self.detalle_resumen)
        self.detalle_resumen.style().polish(self.detalle_resumen)
        self.detalle_resumen.update()

    def mostrar_documento_seleccionado(self):

        self.actualizar_contador_seleccion()
        filas = self.tabla.selectedItems()
        if not filas:
            self.detalle_titulo.setText("Detalle del documento")
            self.detalle_nombre.setText("Documento: —")
            self.detalle_tipo.setText("Tipo: —")
            self.detalle_fecha.setText("Fecha del documento: —")
            self.detalle_carga.setText("Fecha de carga: —")
            self.detalle_paginas.setText("Páginas: —")
            self.detalle_caracteres.setText("Caracteres extraídos: —")
            self.actualizar_resumen_detalle(
                "Seleccioná un documento para ver su información.",
                placeholder=True
            )
            self.detalle_texto.clear()
            self.ajustar_altura_texto_extraido()
            QTimer.singleShot(0, self.ajustar_altura_panel_detalle)
            return

        filas_unicas = sorted(set(item.row() for item in filas))
        if len(filas_unicas) > 1:
            cantidad = len(filas_unicas)
            self.detalle_titulo.setText(f"{cantidad} documentos seleccionados")
            self.detalle_nombre.setText("Documento: selección múltiple")
            self.detalle_tipo.setText("Tipo: —")
            self.detalle_fecha.setText("Fecha del documento: —")
            self.detalle_carga.setText("Fecha de carga: —")
            self.detalle_paginas.setText("Páginas: —")
            self.detalle_caracteres.setText("Caracteres extraídos: —")
            self.actualizar_resumen_detalle(
                'Podés utilizar "Eliminar seleccionados" para quitar estos documentos de DocuCentral.',
                placeholder=False
            )
            self.detalle_texto.clear()
            self.ajustar_altura_texto_extraido()
            QTimer.singleShot(0, self.ajustar_altura_panel_detalle)
            return

        fila = filas_unicas[0]
        if fila < 0 or fila >= len(self.documentos_actuales):
            return
        documento = self.documentos_actuales[fila]
        (id_documento, nombre, ruta, ruta_original, fecha_carga, paginas, texto, fecha_documento, resumen, sensible) = documento
        tipo = "Sensible" if sensible else "Normal"
        self.detalle_titulo.setText(nombre or "Detalle del documento")
        self.detalle_nombre.setText(f"Documento: {nombre or 'Sin nombre'}")
        self.detalle_tipo.setText(f"Tipo: {tipo}")
        self.detalle_fecha.setText(f"Fecha del documento: {fecha_documento or 'No encontrada'}")
        self.detalle_carga.setText(f"Fecha de carga: {fecha_carga or 'No disponible'}")
        self.detalle_paginas.setText(f"Páginas: {paginas or 0}")
        self.detalle_caracteres.setText(f"Caracteres extraídos: {len(texto or ''):,}")
        self.actualizar_resumen_detalle(
            resumen or "Sin resumen",
            placeholder=False
        )
        if texto:
            self.mostrar_texto_extraido_formateado(texto)
            QTimer.singleShot(0, self.ajustar_altura_texto_extraido)
        else:
            self.detalle_texto.setHtml(
                "<div style=\"font-family: Segoe UI, Arial; font-size: 12pt; "
                "color: #eeeeee; line-height: 150%; margin: 0 0 14px 0; "
                "text-align: left;\">"
                "Este documento no contiene texto extraíble.<br><br>"
                "Probablemente sea un PDF escaneado o compuesto por imágenes.<br><br>"
                "Más adelante incorporaremos OCR para poder leer este tipo de documentos."
                "</div>"
            )
            QTimer.singleShot(0, self.ajustar_altura_texto_extraido)

        QTimer.singleShot(0, self.ajustar_altura_panel_detalle)

    def mostrar_texto_extraido_formateado(self, texto):
        """Muestra el texto como un documento continuo, con márgenes,
        justificación e interlineado. Se eliminan saltos de línea
        artificiales producidos por la extracción del PDF.
        """
        if not texto:
            self.detalle_texto.clear()
            return

        texto = texto.replace("\r\n", "\n").replace("\r", "\n")

        # Normalizamos espacios sin tocar el contenido.
        lineas = [re.sub(r"[ \t]+", " ", linea).strip() for linea in texto.split("\n")]

        # Construimos bloques de texto. Un salto simple nunca fuerza un
        # nuevo renglón: el QTextEdit decide dónde cortar según el ancho.
        # Esto evita el problema típico de pypdf de entregar cada línea
        # visual del PDF como un salto independiente.
        bloques = []
        actual = []

        for linea in lineas:
            if linea:
                actual.append(linea)
            else:
                if actual:
                    bloques.append(" ".join(actual))
                    actual = []

        if actual:
            bloques.append(" ".join(actual))

        # Si la extracción generó demasiados bloques pequeños, los unimos
        # para reconstruir párrafos reales. Los títulos cortos se conservan.
        bloques_reconstruidos = []
        acumulado = ""
        for bloque in bloques:
            limpio = bloque.strip()
            es_titulo = (
                len(limpio) <= 90 and
                (limpio.isupper() or limpio.endswith(":") or
                 limpio.lower().startswith((
                     "artículo ", "articulo ", "considerando",
                     "resuelve", "resolución", "resolucion",
                     "visto", "vistos", "anexo"
                 )))
            )

            if es_titulo:
                if acumulado:
                    bloques_reconstruidos.append(acumulado.strip())
                    acumulado = ""
                bloques_reconstruidos.append(limpio)
            else:
                if acumulado:
                    acumulado += " " + limpio
                else:
                    acumulado = limpio

                # Evitamos que una sucesión de bloques cortos produzca
                # el efecto de una palabra o dos por renglón.
                if len(acumulado) >= 350:
                    bloques_reconstruidos.append(acumulado.strip())
                    acumulado = ""

        if acumulado:
            bloques_reconstruidos.append(acumulado.strip())

        if not bloques_reconstruidos:
            self.detalle_texto.setPlainText(texto.strip())
            return

        bloques_html = []
        for bloque in bloques_reconstruidos:
            seguro = html.escape(bloque)
            if (len(bloque) <= 90 and (
                bloque.isupper() or bloque.endswith(":") or
                bloque.lower().startswith(("artículo ", "articulo ", "visto", "considerando", "resuelve"))
            )):
                bloques_html.append(
                    f'<p style="margin: 10px 0 14px 0; text-align: left; '
                    f'font-weight: 600; line-height: 150%;">{seguro}</p>'
                )
            else:
                bloques_html.append(
                    f'<p style="margin: 0 0 18px 0; text-align: justify; '
                    f'line-height: 165%;">{seguro}</p>'
                )

        documento_html = (
            '<div style="font-family: Segoe UI, Arial, sans-serif; '
            'font-size: 12pt; color: #eeeeee; '
            'text-align: justify; margin: 0; padding: 8px 34px 30px 34px;">'
            + "".join(bloques_html)
            + "</div>"
        )

        self.detalle_texto.setHtml(documento_html)
        self.detalle_texto.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        QTimer.singleShot(0, self.ajustar_altura_texto_extraido)


    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "detalle_texto"):
            QTimer.singleShot(0, self.ajustar_altura_texto_extraido)


    # CONTADOR

    # ========================================================



    def actualizar_contador_seleccion(self):
        self.actualizar_marcados()


    # ========================================================

    # ELIMINAR SELECCIONADOS

    # ========================================================



    def eliminar_seleccionados(

        self

    ):



        filas = sorted(

            set(

                item.row()

                for item in

                self.tabla.selectedItems()

            )

        )



        if not filas:



            QMessageBox.information(

                self,

                "DocuCentral",

                "No seleccionaste ningún documento."

            )



            return



        documentos = []



        for fila in filas:



            if (

                fila >= 0

                and

                fila < len(

                    self.documentos_actuales

                )

            ):



                documentos.append(

                    self.documentos_actuales[

                        fila

                    ]

                )



        if not documentos:

            return



        cantidad = len(

            documentos

        )



        nombres = []



        for documento in documentos[:10]:



            nombres.append(

                f"• {documento[1]}"

            )



        if cantidad > 10:



            nombres.append(

                (

                    f"• ... y "

                    f"{cantidad - 10} más"

                )

            )



        mensaje = (

            f"Vas a eliminar "

            f"{cantidad} documento"

            f"{'s' if cantidad != 1 else ''} "

            f"de DocuCentral.\n\n"

            f"{chr(10).join(nombres)}\n\n"

            f"IMPORTANTE:\n"

            f"Los documentos se quitarán de la biblioteca. "

            f"Si un PDF está protegido y almacenado dentro de DocuCentral, su copia protegida también se eliminará. "

            f"Los PDF originales externos a DocuCentral no se borran.\n\n"

            f"¿Querés continuar?"

        )



        respuesta = QMessageBox.question(

            self,

            "Confirmar eliminación",

            mensaje,

            QMessageBox.StandardButton.Yes

            |

            QMessageBox.StandardButton.No,

            QMessageBox.StandardButton.No

        )



        if (

            respuesta

            !=

            QMessageBox.StandardButton.Yes

        ):



            return



        if not self.pedir_contrasena_maestra("Autorizar eliminación de documentos"):
            return

        respuesta_final = QMessageBox.question(
            self,
            "Confirmación final",
            "La contraseña fue aceptada. ¿Confirmás eliminar estos documentos de la biblioteca?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if respuesta_final != QMessageBox.StandardButton.Yes:
            return

        conexion = conectar_db()

        cursor = conexion.cursor()



        eliminados = 0

        errores = 0



        for documento in documentos:



            id_documento = documento[0]



            try:



                # Los documentos sensibles ahora son PDF reales protegidos con contraseña.
                if len(documento) > 9 and documento[9]:
                    try:
                        archivo_protegido = Path(documento[2])
                        if archivo_protegido.exists():
                            archivo_protegido.unlink()
                    except Exception as exc:
                        print(f"No se pudo eliminar el PDF protegido {documento[2]}: {exc}")

                cursor.execute(

                    """

                    DELETE FROM documentos

                    WHERE id = ?

                    """,

                    (

                        id_documento,

                    )

                )



                eliminados += 1



            except Exception as e:



                errores += 1



                print(

                    f"Error eliminando "

                    f"{id_documento}: {e}"

                )



        conexion.commit()

        conexion.close()



        self.cargar_documentos()



        QMessageBox.information(

            self,

            "DocuCentral",

            (

                f"Eliminación terminada.\n\n"

                f"Documentos eliminados: "

                f"{eliminados}\n"

                f"Errores: {errores}\n\n"

                f"Los archivos PDF originales "

                f"permanecen en sus ubicaciones."

            )

        )



    # ========================================================

    # ========================================================
    # SEGURIDAD Y RECUPERACIÓN
    # ========================================================

    def _abrir_gestion_organizacion(self):
        """Abre el panel de organización, licencias y vinculación de equipos."""
        try:
            dialogo = DialogoOrganizacion(self, DATA_DIR, self)
            dialogo.exec()
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Organización y equipos",
                f"No se pudo abrir el panel de organización.\\n\\n{exc}",
            )

    def _recovery_url(self):
        """Usa el backend de producción; permite sobrescribirlo por variable de entorno."""
        return os.environ.get(
            "DOCUCENTRAL_RECOVERY_URL",
            "https://docucentral.vercel.app"
        ).rstrip("/")

    def _api_post(self, endpoint, payload):
        base_url = self._recovery_url()
        url = base_url + (endpoint if endpoint.startswith("/") else "/" + endpoint)
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            try:
                raw_detail = exc.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw_detail) if raw_detail else {}
                detail = parsed.get("detail", parsed.get("message", raw_detail or str(exc)))
            except Exception:
                detail = str(exc)
            # Include the requested URL/status so a Vercel routing 404 is distinguishable
            # from a 404 returned intentionally by an endpoint for a missing account.
            raise ErrorSeguridad(
                f"Error HTTP {exc.code} al consultar {url}: {detail}"
            ) from exc
        except Exception as exc:
            raise ErrorSeguridad(
                "No se pudo contactar al servidor de recuperación.\n\n"
                f"URL: {self._recovery_url()}\n\n{exc}"
            ) from exc

    def verificar_configuracion_seguridad(self):
        """Registra/verifica la cuenta en el primer inicio o migra instalaciones antiguas."""
        correo_actual = (self.seguridad.correo or "").strip().lower()
        correo_antiguo = CORREO_RECUPERACION_DOCUCENTRAL.strip().lower()

        if (
            self.seguridad.configurado
            and self.seguridad.email_verificado
            and correo_actual
            and correo_actual != correo_antiguo
            and self.seguridad.id_instalacion
        ):
            return True

        if self.seguridad.configurado:
            titulo = "Actualizar cuenta de DocuCentral"
            mensaje = (
                "Esta instalación tiene una configuración de seguridad anterior o un correo sin verificar.\n\n"
                "Vamos a asociarla a tu cuenta de DocuCentral. Tus PDF protegidos y su contraseña maestra no se modificarán."
            )
        else:
            titulo = "Registro de DocuCentral"
            mensaje = (
                "Antes de usar DocuCentral por primera vez, registrá tu cuenta.\n\n"
                "La contraseña de tu cuenta será la contraseña de autorización de DocuCentral "
                "para proteger documentos, desprotegerlos y eliminarlos de la biblioteca. "
                "Cada PDF conserva su contraseña propia. El correo de recuperación se fija "
                "con esta primera configuración y no cambia al cambiar de usuario."
            )

        respuesta = QMessageBox.question(
            self,
            titulo,
            mensaje + "\n\n¿Querés continuar con el registro?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return False

        return self.configurar_seguridad_inicial()

    def _id_instalacion_pendiente(self):
        """Devuelve un ID estable por PC para que reintentar el registro no cree instalaciones duplicadas."""
        archivo_id = DATA_DIR / "id_instalacion.txt"
        try:
            if self.seguridad.configurado and self.seguridad.id_instalacion:
                return self.seguridad.id_instalacion
            if archivo_id.exists():
                valor = archivo_id.read_text(encoding="utf-8").strip()
                if valor and re.fullmatch(r"[a-fA-F0-9]{32}", valor):
                    return valor
            valor = uuid.uuid4().hex
            archivo_id.write_text(valor, encoding="utf-8")
            return valor
        except OSError as exc:
            raise ErrorSeguridad(f"No se pudo guardar el identificador de esta instalación: {exc}") from exc

    def configurar_seguridad_inicial(self):
        """Registra la cuenta y, si es una instalación nueva, configura la clave maestra local."""
        migracion = self.seguridad.configurado
        dialogo = QDialog(self)
        dialogo.setWindowTitle("Cuenta de DocuCentral" if not migracion else "Actualizar cuenta de DocuCentral")
        dialogo.setMinimumWidth(520)

        layout = QFormLayout(dialogo)
        layout.setSpacing(12)

        correo = QLineEdit(self.seguridad.correo if migracion and self.seguridad.correo != CORREO_RECUPERACION_DOCUCENTRAL else "")
        correo.setPlaceholderText("tunombre@correo.com")

        contrasena_cuenta = QLineEdit()
        contrasena_cuenta.setEchoMode(QLineEdit.EchoMode.Password)
        contrasena_cuenta.setPlaceholderText("Mínimo 8 caracteres")

        confirmar_cuenta = QLineEdit()
        confirmar_cuenta.setEchoMode(QLineEdit.EchoMode.Password)

        layout.addRow("Correo base:", correo)
        layout.addRow("Contraseña de la cuenta:", contrasena_cuenta)
        layout.addRow("Confirmar contraseña de cuenta:", confirmar_cuenta)

        aviso_seguridad = QLabel(
            "Esta contraseña también autoriza las acciones sensibles de DocuCentral. "
            "Las contraseñas propias de cada PDF no se reemplazan por ella."
        )
        aviso_seguridad.setWordWrap(True)
        aviso_seguridad.setStyleSheet("color: #aaaaaa; padding-top: 6px;")
        layout.addRow(aviso_seguridad)

        botones = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Continuar")
        botones.accepted.connect(dialogo.accept)
        botones.rejected.connect(dialogo.reject)
        layout.addRow(botones)

        if dialogo.exec() != QDialog.DialogCode.Accepted:
            return False

        mail = correo.text().strip().lower()
        pwd_cuenta = contrasena_cuenta.text()
        pwd_cuenta2 = confirmar_cuenta.text()

        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", mail):
            QMessageBox.warning(self, "Cuenta", "Ingresá un correo electrónico válido.")
            return False
        if len(pwd_cuenta) < 8:
            QMessageBox.warning(self, "Cuenta", "La contraseña de la cuenta debe tener al menos 8 caracteres.")
            return False
        if pwd_cuenta != pwd_cuenta2:
            QMessageBox.warning(self, "Cuenta", "Las contraseñas de la cuenta no coinciden.")
            return False

        pwd_maestra = pwd_cuenta

        try:
            correo_anterior = (self.seguridad.correo or "").strip().lower()
            correo_central = CORREO_RECUPERACION_DOCUCENTRAL.strip().lower()
            if migracion and correo_anterior == correo_central:
                # Las instalaciones antiguas guardaban el correo del remitente como destinatario.
                # Usamos un ID nuevo para no sobrescribir una asociación antigua en el servidor.
                archivo_migracion = DATA_DIR / "id_instalacion_migracion.txt"
                valor_id = archivo_migracion.read_text(encoding="utf-8").strip() if archivo_migracion.exists() else ""
                if not re.fullmatch(r"[a-fA-F0-9]{32}", valor_id):
                    valor_id = uuid.uuid4().hex
                    archivo_migracion.write_text(valor_id, encoding="utf-8")
                id_instalacion = valor_id
            else:
                id_instalacion = self._id_instalacion_pendiente()
            respuesta = self._api_post(
                "/registrar",
                {
                    "id_instalacion": id_instalacion,
                    "correo": mail,
                    "contrasena_cuenta": pwd_cuenta,
                },
            )
        except ErrorSeguridad as exc:
            QMessageBox.critical(self, "Registro de DocuCentral", str(exc))
            return False

        if respuesta.get("requiere_verificacion", True):
            token, ok = QInputDialog.getText(
                self,
                "Verificar correo",
                "Ingresá el código de 6 dígitos que enviamos a:\n" + mail,
                QLineEdit.EchoMode.Normal,
            )
            if not ok or not token.strip():
                QMessageBox.information(
                    self,
                    "Verificación pendiente",
                    "El registro quedó pendiente. Volvé a abrir DocuCentral y continuá el registro con el mismo correo y contraseña de cuenta.",
                )
                return False

            try:
                self._api_post(
                    "/verificar",
                    {
                        "id_instalacion": id_instalacion,
                        "token": token.strip(),
                        "proposito": "verificación",
                    },
                )
            except ErrorSeguridad as exc:
                QMessageBox.warning(self, "Verificación", str(exc))
                return False

        try:
            if migracion:
                # Solo se actualizan los datos de cuenta e instalación; no se toca la clave maestra ni los PDF.
                self.seguridad.config["correo"] = mail
                self.seguridad.config["id_instalacion"] = id_instalacion
                self.seguridad.config["correo_verificado"] = True
                self.seguridad._guardar()
                # En instalaciones antiguas, asociar la cuenta nueva a la clave
                # existente exige desbloquearla primero. No se modifica ni se recrea
                # la clave maestra ni se re-encripta ningún PDF.
                self._asegurar_vinculo_seguridad_cuenta(mail, pwd_cuenta)
                try:
                    archivo_migracion = DATA_DIR / "id_instalacion_migracion.txt"
                    if archivo_migracion.exists():
                        archivo_migracion.unlink()
                except OSError:
                    pass
            else:
                codigo_recuperacion = self.seguridad.inicializar(pwd_maestra, mail)
                self.seguridad.config["id_instalacion"] = id_instalacion
                self.seguridad.marcar_email_verificado()
                self.seguridad.vincular_contrasena_cuenta(mail, pwd_cuenta)
                try:
                    archivo_id = DATA_DIR / "id_instalacion.txt"
                    if archivo_id.exists():
                        archivo_id.unlink()
                except OSError:
                    pass
        except ErrorSeguridad as exc:
            QMessageBox.critical(self, "Seguridad", str(exc))
            return False

        # Mantener el mismo ID de instalación para esta cuenta al volver a ingresar.
        try:
            cuentas_locales = self._leer_json_local(self._ruta_cuentas_instalacion(), {})
            cuentas_locales[mail] = id_instalacion
            self._guardar_json_local(self._ruta_cuentas_instalacion(), cuentas_locales)
        except ErrorSeguridad as exc:
            QMessageBox.warning(self, "Cuenta", f"La cuenta quedó configurada, pero no se pudo guardar su vínculo local: {exc}")

        if migracion:
            QMessageBox.information(
                self,
                "Cuenta actualizada",
                f"La instalación quedó asociada a {mail}.\n\nLa contraseña de esta cuenta ya autoriza las acciones sensibles. La clave de seguridad existente y las contraseñas reales de los PDF no se modificaron.",
            )
        else:
            QMessageBox.information(
                self,
                "Registro completado",
                f"La cuenta quedó registrada y verificada: {mail}\n\n"
                "La contraseña de esta cuenta autoriza las operaciones sensibles de DocuCentral. "
                "Cada PDF mantiene su contraseña real independiente.\n\n"
                "GUARDÁ ESTE CÓDIGO DE RECUPERACIÓN DE EMERGENCIA EN UN LUGAR SEGURO:\n\n"
                f"{codigo_recuperacion}\n\n"
                "No se volverá a mostrar. Te servirá como alternativa si no podés recuperar la clave desde Windows.",
            )
        return True

    # ========================================================
    # SESIÓN DE CUENTA (INDEPENDIENTE DE LA SEGURIDAD DE PDF)
    # ========================================================

    def _ruta_sesion_cuenta(self):
        return DATA_DIR / "sesion_cuenta.json"

    def _ruta_cuentas_instalacion(self):
        return DATA_DIR / "cuentas_instalacion.json"

    def _leer_json_local(self, ruta, predeterminado):
        try:
            if ruta.exists():
                valor = json.loads(ruta.read_text(encoding="utf-8"))
                return valor if isinstance(valor, type(predeterminado)) else predeterminado
        except Exception:
            pass
        return predeterminado

    def _guardar_json_local(self, ruta, datos):
        temporal = ruta.with_suffix(ruta.suffix + ".tmp")
        try:
            ruta.parent.mkdir(parents=True, exist_ok=True)
            temporal.write_text(json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporal, ruta)
        except Exception as exc:
            try:
                temporal.unlink(missing_ok=True)
            except Exception:
                pass
            raise ErrorSeguridad(f"No se pudo guardar la sesión local de DocuCentral: {exc}") from exc

    def _guardar_sesion_cuenta(self, correo, activa=True):
        correo = (correo or "").strip().lower()
        self._guardar_json_local(
            self._ruta_sesion_cuenta(),
            {"correo": correo, "activa": bool(activa), "actualizada_en": datetime.now().isoformat()},
        )
        self.correo_cuenta_activa = correo if activa else ""
        if activa:
            self.setWindowTitle(f"DocuCentral — {correo}")
        else:
            self.setWindowTitle("DocuCentral")

    def asegurar_sesion_cuenta(self):
        """Mantiene la sesión de usuario aparte de la clave maestra y su recuperación."""
        ruta = self._ruta_sesion_cuenta()
        if ruta.exists():
            sesion = self._leer_json_local(ruta, {})
            if sesion.get("activa") and sesion.get("correo"):
                self.correo_cuenta_activa = sesion["correo"].strip().lower()
                self.setWindowTitle(f"DocuCentral — {self.correo_cuenta_activa}")
                return True
            # Si existe una sesión cerrada, no se reactiva automáticamente la cuenta anterior.
            return self.autenticar_cuenta()

        # Migración de instalaciones anteriores: se conserva la cuenta que ya estaba
        # verificada, sin tocar la clave maestra ni reasignar su recuperación.
        if self.seguridad.email_verificado and self.seguridad.correo:
            try:
                self._guardar_sesion_cuenta(self.seguridad.correo, True)
                return True
            except ErrorSeguridad as exc:
                QMessageBox.critical(self, "Sesión", str(exc))
                return False
        return self.autenticar_cuenta()

    def _limpiar_revocacion_local(self, correo):
        correo = (correo or "").strip().lower()
        revocadas = self.seguridad.config.get("cuentas_revocadas", [])
        if isinstance(revocadas, list) and correo in revocadas:
            self.seguridad.config["cuentas_revocadas"] = [x for x in revocadas if x != correo]
            self.seguridad._guardar()

    def _eliminar_cuenta_desde_menu(self):
        if self.eliminar_cuenta_remota():
            self.close()

    def _asegurar_vinculo_seguridad_cuenta(self, correo, contrasena):
        """Valida la cuenta y abre/vincula la clave local sin usar cuentas eliminadas como autorizantes."""
        correo = (correo or "").strip().lower()
        if not self.seguridad.configurado:
            raise ErrorSeguridad("La seguridad local todavía no está configurada.")

        if self.seguridad.tiene_contrasena_cuenta(correo):
            try:
                clave = self.seguridad.desbloquear_con_cuenta(correo, contrasena)
                self._limpiar_revocacion_local(correo)
                return clave
            except ErrorSeguridad:
                # Puede ocurrir después de restablecer la contraseña o recrear explícitamente
                # una cuenta eliminada. Intentamos reenvolver la clave local con DPAPI.
                try:
                    self.seguridad.desbloquear_con_recuperacion_windows()
                    self.seguridad.vincular_contrasena_cuenta(correo, contrasena)
                    self._limpiar_revocacion_local(correo)
                    return self.seguridad.clave_maestra
                except ErrorSeguridad:
                    pass

        if self.seguridad.clave_maestra:
            self.seguridad.vincular_contrasena_cuenta(correo, contrasena)
            self._limpiar_revocacion_local(correo)
            return self.seguridad.clave_maestra

        envolturas = self.seguridad.config.get("envolturas_cuenta", {})
        revocadas = self.seguridad.config.get("cuentas_revocadas", [])
        revocadas = set(x.strip().lower() for x in revocadas if isinstance(x, str)) if isinstance(revocadas, list) else set()
        cuentas_ya_vinculadas = sorted(
            email for email in envolturas.keys()
            if isinstance(envolturas, dict) and email and email != correo and email.strip().lower() not in revocadas
        ) if isinstance(envolturas, dict) else []
        if cuentas_ya_vinculadas:
            cuenta_autorizante, ok = QInputDialog.getItem(
                self,
                "Autorizar nueva cuenta",
                "Elegí una cuenta vinculada que siga activa para autorizar la biblioteca compartida:",
                cuentas_ya_vinculadas,
                0,
                False,
            )
            if not ok or not cuenta_autorizante:
                raise ErrorSeguridad("No se autorizó la vinculación de esta cuenta a la biblioteca compartida.")
            clave, ok = QInputDialog.getText(
                self,
                "Autorizar nueva cuenta",
                f"Ingresá la contraseña de la cuenta existente {cuenta_autorizante}:",
                QLineEdit.EchoMode.Password,
            )
            if not ok or not clave:
                raise ErrorSeguridad("No se autorizó la vinculación de esta cuenta a la biblioteca compartida.")
            # La autorización local por sí sola no alcanza: verificamos en el servidor
            # que la cuenta elegida no haya sido eliminada ni esté sin verificar.
            self._api_post("/validar-cuenta", {"correo": cuenta_autorizante, "contrasena_cuenta": clave})
            self.seguridad.desbloquear_con_cuenta(cuenta_autorizante, clave)
            self.seguridad.vincular_contrasena_cuenta(correo, contrasena)
            self._limpiar_revocacion_local(correo)
            return self.seguridad.clave_maestra

        if isinstance(envolturas, dict) and envolturas:
            raise ErrorSeguridad(
                "No hay otra cuenta activa vinculada que pueda autorizar el acceso a esta biblioteca. "
                "Por seguridad, no se permite que una cuenta nueva herede los PDF automáticamente. "
                "Vinculá primero una cuenta autorizada o recuperá la clave local con el código de emergencia."
            )

        # Instalación anterior a las envolturas por cuenta: intenta primero Windows DPAPI.
        try:
            self.seguridad.desbloquear_con_recuperacion_windows()
        except ErrorSeguridad:
            # Si la contraseña de la cuenta también era la antigua contraseña de la clave,
            # puede abrirla sin solicitar otra contraseña.
            try:
                self.seguridad.desbloquear(contrasena)
            except ErrorSeguridad:
                codigo, ok_codigo = QInputDialog.getText(
                    self,
                    "Recuperar seguridad local",
                    "Windows no pudo recuperar automáticamente la clave local. Ingresá el código de recuperación de emergencia para migrar la seguridad sin usar la contraseña anterior:",
                    QLineEdit.EchoMode.Password,
                )
                if ok_codigo and codigo.strip():
                    try:
                        self.seguridad.desbloquear_con_codigo_recuperacion(codigo.strip().upper())
                    except ErrorSeguridad:
                        QMessageBox.warning(
                            self,
                            "Código no válido",
                            "El código de emergencia no es válido. Para preservar el acceso a los PDF protegidos, podés intentar una última vez con la contraseña de seguridad anterior.",
                        )
                    else:
                        self.seguridad.vincular_contrasena_cuenta(correo, contrasena)
                        self._limpiar_revocacion_local(correo)
                        return self.seguridad.clave_maestra
                else:
                    raise ErrorSeguridad(
                        "No se pudo recuperar automáticamente la clave local. Para no perder acceso a los PDF protegidos, necesitás el código de recuperación de emergencia o, como último recurso de migración, la contraseña de seguridad anterior. No se modificó ningún archivo."
                    )

                anterior, ok = QInputDialog.getText(
                    self,
                    "Último recurso de migración",
                    "Ingresá la contraseña de seguridad anterior. Solo se usa para recuperar la clave local existente; después, las operaciones habituales utilizarán la contraseña de tu cuenta.",
                    QLineEdit.EchoMode.Password,
                )
                if not ok or not anterior:
                    raise ErrorSeguridad("No se autorizó la vinculación de esta cuenta a la biblioteca compartida.")
                try:
                    self.seguridad.desbloquear(anterior)
                except ErrorSeguridad as exc:
                    raise ErrorSeguridad("La contraseña de seguridad anterior no es correcta; no se modificó la clave local ni los PDF.") from exc

        self.seguridad.vincular_contrasena_cuenta(correo, contrasena)
        self._limpiar_revocacion_local(correo)
        return self.seguridad.clave_maestra

    def autenticar_cuenta(self, correo_sugerido=""):
        """Inicia o registra una cuenta sin modificar la configuración de seguridad de los PDF."""
        dialogo = QDialog(self)
        dialogo.setWindowTitle("Ingresar o crear cuenta de DocuCentral")
        dialogo.setMinimumWidth(500)
        layout = QFormLayout(dialogo)
        layout.setSpacing(12)

        texto = QLabel(
            "Ingresá una cuenta existente o registrá una nueva. La biblioteca de PDF es compartida en esta computadora. "
            "La contraseña de esta cuenta autoriza las acciones sensibles de DocuCentral. "
            "Cada PDF conserva su contraseña propia y el correo de recuperación de la seguridad local no cambia al cambiar de cuenta."
        )
        texto.setWordWrap(True)
        layout.addRow(texto)

        modo = QComboBox()
        modo.addItem("Ingresar a una cuenta existente", "ingresar")
        modo.addItem("Crear una cuenta nueva", "crear")
        layout.addRow("¿Qué querés hacer?:", modo)

        correo = QLineEdit(correo_sugerido or "")
        correo.setPlaceholderText("tunombre@correo.com")
        contrasena = QLineEdit()
        contrasena.setEchoMode(QLineEdit.EchoMode.Password)
        contrasena.setPlaceholderText("Mínimo 8 caracteres")
        confirmar = QLineEdit()
        confirmar.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("Correo de la cuenta:", correo)
        layout.addRow("Contraseña de la cuenta:", contrasena)
        fila_confirmar = layout.addRow("Confirmar contraseña:", confirmar)
        def actualizar_modo(indice):
            crear = modo.currentData() == "crear"
            confirmar.setVisible(crear)
            for i in range(layout.rowCount()):
                etiqueta = layout.itemAt(i, QFormLayout.ItemRole.LabelRole)
                campo = layout.itemAt(i, QFormLayout.ItemRole.FieldRole)
                if campo and campo.widget() is confirmar and etiqueta and etiqueta.widget():
                    etiqueta.widget().setVisible(crear)
                    break
            botones.button(QDialogButtonBox.StandardButton.Ok).setText("Crear cuenta" if crear else "Ingresar")

        fila_botones = QHBoxLayout()
        boton_recuperar = QPushButton("Olvidé mi contraseña")
        fila_botones.addWidget(boton_recuperar)
        fila_botones.addStretch(1)
        botones = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        botones.button(QDialogButtonBox.StandardButton.Ok).setText("Ingresar")
        botones.accepted.connect(dialogo.accept)
        botones.rejected.connect(dialogo.reject)
        fila_botones.addWidget(botones)
        layout.addRow(fila_botones)
        modo.currentIndexChanged.connect(actualizar_modo)
        actualizar_modo(modo.currentIndex())
        recuperar_solicitado = {"valor": False}
        def solicitar_recuperacion():
            recuperar_solicitado["valor"] = True
            dialogo.reject()
        boton_recuperar.clicked.connect(solicitar_recuperacion)

        resultado_dialogo = dialogo.exec()
        if resultado_dialogo != QDialog.DialogCode.Accepted:
            if recuperar_solicitado["valor"]:
                self.recuperar_por_email(correo.text().strip().lower())
            return False

        mail = correo.text().strip().lower()
        pwd = contrasena.text()
        pwd2 = confirmar.text()
        modo_acceso = modo.currentData()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", mail):
            QMessageBox.warning(self, "Cuenta", "Ingresá un correo electrónico válido.")
            return False
        if len(pwd) < 8:
            QMessageBox.warning(self, "Cuenta", "La contraseña debe tener al menos 8 caracteres.")
            return False
        if modo_acceso == "crear" and pwd != pwd2:
            QMessageBox.warning(self, "Cuenta", "Las contraseñas no coinciden.")
            return False

        cuentas_locales = self._leer_json_local(self._ruta_cuentas_instalacion(), {})
        id_instalacion_cuenta = cuentas_locales.get(mail)
        if not isinstance(id_instalacion_cuenta, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", id_instalacion_cuenta):
            id_instalacion_cuenta = uuid.uuid4().hex
            cuentas_locales[mail] = id_instalacion_cuenta
            try:
                self._guardar_json_local(self._ruta_cuentas_instalacion(), cuentas_locales)
            except ErrorSeguridad as exc:
                QMessageBox.critical(self, "Cuenta", str(exc))
                return False

        try:
            respuesta = self._api_post(
                "/registrar",
                {"id_instalacion": id_instalacion_cuenta, "correo": mail, "contrasena_cuenta": pwd, "modo": modo_acceso},
            )
            if respuesta.get("requiere_verificacion", False):
                token, ok = QInputDialog.getText(
                    self,
                    "Verificar cuenta",
                    "Ingresá el código de 6 dígitos enviado a:\n" + mail,
                    QLineEdit.EchoMode.Normal,
                )
                if not ok or not token.strip():
                    QMessageBox.information(
                        self, "Verificación pendiente",
                        "La cuenta quedó pendiente de verificación. Volvé a ingresar con el mismo correo y contraseña.",
                    )
                    return False
                self._api_post(
                    "/verificar",
                    {"id_instalacion": id_instalacion_cuenta, "token": token.strip(), "proposito": "verificación"},
                )
        except ErrorSeguridad as exc:
            QMessageBox.warning(self, "Cuenta", str(exc))
            return False

        try:
            self._asegurar_vinculo_seguridad_cuenta(mail, pwd)
        except ErrorSeguridad as exc:
            QMessageBox.warning(self, "Seguridad de la biblioteca", str(exc))
            return False

        # Si la API nueva está desplegada, una instalación revocada por la empresa
        # no puede continuar al área de trabajo. Si la ruta aún no existe en el
        # servidor antiguo, se mantiene la compatibilidad hasta desplegar el backend actualizado.
        try:
            estado_org = self._api_post(
                "/organizaciones/estado-instalacion",
                {
                    "correo": mail,
                    "contrasena_cuenta": pwd,
                    "id_instalacion": id_instalacion_cuenta,
                },
            )
            if estado_org.get("vinculada") and (
                estado_org.get("estado") != "activa"
                or not estado_org.get("organizacion_activa", False)
            ):
                QMessageBox.critical(
                    self, "Acceso revocado",
                    "Esta instalación fue revocada por el administrador de la organización. "
                    "Contactá al administrador para recuperar el acceso."
                )
                return False
        except ErrorSeguridad as exc:
            if "HTTP 404" not in str(exc):
                # La recuperación y el acceso individual se conservan si hay una
                # interrupción temporal; la revocación se volverá a consultar al iniciar.
                pass

        self._guardar_sesion_cuenta(mail, True)

        QMessageBox.information(
            self, "Cuenta activa",
            f"Sesión iniciada como {mail}.\n\nLa biblioteca sigue compartida. Esta contraseña autoriza las acciones sensibles de DocuCentral; cada PDF mantiene su contraseña real. El correo de recuperación de la seguridad local no se cambia al cambiar de cuenta.",
        )
        return True

    def eliminar_cuenta_remota(self):
        """Elimina una cuenta solo después de validar contraseña, token de correo y confirmación."""
        sesion = self._leer_json_local(self._ruta_sesion_cuenta(), {})
        correo = str(sesion.get("correo", "") or self.correo_cuenta_activa or "").strip().lower()
        if not correo:
            correo = (self.seguridad.correo or "").strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", correo):
            QMessageBox.warning(self, "Eliminar cuenta", "No se encontró una cuenta vinculada para eliminar.")
            return False

        aviso = QMessageBox.warning(
            self,
            "Eliminar cuenta definitivamente",
            f"Vas a solicitar la eliminación permanente de la cuenta {correo}.\n\n"
            "La cuenta dejará de poder iniciar sesión en DocuCentral y se eliminarán sus vínculos del servidor. "
            "Los PDF y carpetas locales NO se borrarán, y sus contraseñas reales no cambiarán.\n\n"
            "Para continuar, necesitarás la contraseña de la cuenta y un código enviado al correo registrado.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if aviso != QMessageBox.StandardButton.Yes:
            return False

        contrasena, ok = QInputDialog.getText(
            self, "Confirmar identidad", f"Ingresá la contraseña de la cuenta {correo}:", QLineEdit.EchoMode.Password
        )
        if not ok or not contrasena:
            return False

        cuentas = self._leer_json_local(self._ruta_cuentas_instalacion(), {})
        id_instalacion = cuentas.get(correo)
        if not isinstance(id_instalacion, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", id_instalacion):
            if correo == (self.seguridad.correo or "").strip().lower():
                id_instalacion = self.seguridad.id_instalacion
        if not isinstance(id_instalacion, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", id_instalacion or ""):
            QMessageBox.warning(self, "Eliminar cuenta", "No se encontró el identificador de instalación asociado a esta cuenta.")
            return False

        try:
            self._api_post(
                "/solicitar-eliminacion-cuenta",
                {"id_instalacion": id_instalacion, "correo": correo, "contrasena_cuenta": contrasena},
            )
        except ErrorSeguridad as exc:
            QMessageBox.warning(self, "Eliminar cuenta", str(exc))
            return False

        token, ok = QInputDialog.getText(
            self,
            "Token de eliminación de cuenta",
            f"Ingresá el código enviado a {correo}. Vence en 10 minutos:",
            QLineEdit.EchoMode.Normal,
        )
        if not ok or not token.strip():
            QMessageBox.information(self, "Eliminación cancelada", "La cuenta no fue eliminada. Podés volver a solicitar un código cuando quieras.")
            return False

        confirmacion, ok = QInputDialog.getText(
            self,
            "Confirmación final",
            f"Para confirmar, escribí exactamente el correo de la cuenta:\n{correo}",
            QLineEdit.EchoMode.Normal,
        )
        if not ok or confirmacion.strip().lower() != correo:
            QMessageBox.information(self, "Eliminación cancelada", "El correo no coincide. La cuenta no fue eliminada.")
            return False

        try:
            self._api_post(
                "/eliminar-cuenta",
                {"id_instalacion": id_instalacion, "correo": correo, "contrasena_cuenta": contrasena, "token": token.strip()},
            )
        except ErrorSeguridad as exc:
            QMessageBox.critical(self, "Eliminación no completada", str(exc) + "\n\nLa cuenta no se eliminó si el servidor no confirmó la operación.")
            return False

        try:
            self._guardar_sesion_cuenta("", False)
            cuentas.pop(correo, None)
            self._guardar_json_local(self._ruta_cuentas_instalacion(), cuentas)
            revocadas = self.seguridad.config.get("cuentas_revocadas", [])
            if not isinstance(revocadas, list):
                revocadas = []
            if correo not in revocadas:
                revocadas.append(correo)
            self.seguridad.config["cuentas_revocadas"] = revocadas
            self.seguridad._guardar()
        except ErrorSeguridad as exc:
            QMessageBox.warning(self, "Cuenta eliminada", f"El servidor eliminó la cuenta, pero no se pudo limpiar toda la sesión local: {exc}")
        self.seguridad.clave_maestra = None
        for temp_path in list(self._temporary_files):
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
        self._temporary_files.clear()
        try:
            self.seguridad.limpiar_archivos_temporales()
        except ErrorSeguridad:
            pass
        self.correo_cuenta_activa = ""
        QMessageBox.information(
            self,
            "Cuenta eliminada",
            f"La cuenta {correo} fue eliminada tras validar la contraseña y el token por correo.\n\n"
            "El servidor conserva un registro de seguridad de la solicitud y su resultado. "
            "La biblioteca local y las contraseñas de los PDF permanecen intactas.",
        )
        return True

    def quitar_usuario_vinculado(self, confirmar=True):
        """Quita el vínculo local de cuenta sin borrar la biblioteca ni la seguridad de los PDF."""
        sesion = self._leer_json_local(self._ruta_sesion_cuenta(), {})
        correo = str(sesion.get("correo", "") or self.correo_cuenta_activa or "").strip().lower()
        if not correo and not sesion.get("activa"):
            QMessageBox.information(self, "Usuario", "No hay ningún usuario vinculado en esta computadora.")
            return False

        if confirmar:
            contrasena, ok_pwd = QInputDialog.getText(
                self,
                "Autorizar quitar usuario",
                f"Ingresá la contraseña de la cuenta {correo} para quitar su vínculo local:",
                QLineEdit.EchoMode.Password,
            )
            if not ok_pwd or not contrasena:
                return False
            try:
                if self.seguridad.tiene_contrasena_cuenta(correo):
                    self.seguridad.desbloquear_con_cuenta(correo, contrasena)
                elif correo == (self.seguridad.correo or "").strip().lower():
                    self._asegurar_vinculo_seguridad_cuenta(correo, contrasena)
                else:
                    raise ErrorSeguridad("Esta cuenta no está vinculada a la seguridad local.")
            except ErrorSeguridad as exc:
                QMessageBox.warning(self, "Quitar usuario", str(exc))
                return False
            respuesta = QMessageBox.question(
                self,
                "Quitar usuario de esta computadora",
                "¿Querés quitar el vínculo local de este usuario?\n\n"
                "Esto no elimina la cuenta del servidor, no borra PDF ni carpetas y no cambia "
                "la contraseña maestra, las contraseñas reales de los PDF ni su correo de recuperación.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if respuesta != QMessageBox.StandardButton.Yes:
                return False

        # Vaciar cualquier clave maestra en memoria y retirar temporales abiertos.
        self.seguridad.clave_maestra = None
        for temp_path in list(self._temporary_files):
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
        self._temporary_files.clear()
        try:
            self.seguridad.limpiar_archivos_temporales()
        except ErrorSeguridad:
            pass

        try:
            self._guardar_sesion_cuenta("", False)
            cuentas = self._leer_json_local(self._ruta_cuentas_instalacion(), {})
            if correo and correo in cuentas:
                cuentas.pop(correo, None)
                self._guardar_json_local(self._ruta_cuentas_instalacion(), cuentas)
        except ErrorSeguridad as exc:
            QMessageBox.critical(self, "Quitar usuario", str(exc))
            return False

        self.correo_cuenta_activa = ""
        self.setWindowTitle("DocuCentral")
        return True

    def cerrar_sesion_y_cambiar_cuenta(self):
        respuesta = QMessageBox.question(
            self,
            "Cerrar sesión",
            "¿Querés cerrar la sesión actual e ingresar con otra cuenta?\n\nLos PDF y las carpetas locales no se borrarán. La seguridad y recuperación de los PDF permanecerán sin cambios.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if respuesta != QMessageBox.StandardButton.Yes:
            return
        # Bloquear la clave maestra en memoria antes de entregar la sesión a otra persona.
        # Los PDF en disco y la configuración criptográfica no se modifican.
        self.seguridad.clave_maestra = None
        for temp_path in list(self._temporary_files):
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
        self._temporary_files.clear()
        try:
            self.seguridad.limpiar_archivos_temporales()
        except ErrorSeguridad:
            pass

        try:
            self._guardar_sesion_cuenta("", False)
        except ErrorSeguridad as exc:
            QMessageBox.critical(self, "Cerrar sesión", str(exc))
            return
        if not self.autenticar_cuenta():
            # Al cancelar o fallar el acceso no dejamos abierta la biblioteca con
            # una sesión que el usuario ya decidió cerrar.
            self.close()

    def pedir_clave_maestra(self):
        """Desbloquea la clave criptográfica usando la contraseña de la cuenta activa."""
        if self.seguridad.clave_maestra:
            return self.seguridad.clave_maestra
        if not self.seguridad.configurado:
            QMessageBox.warning(self, "Seguridad", "Primero completá el registro inicial de DocuCentral.")
            return None

        correo = (self.correo_cuenta_activa or "").strip().lower()
        if not correo:
            sesion = self._leer_json_local(self._ruta_sesion_cuenta(), {})
            correo = str(sesion.get("correo", "")).strip().lower() if sesion.get("activa") else ""
        if not correo:
            QMessageBox.warning(self, "Cuenta", "No hay una cuenta activa para desbloquear la seguridad local.")
            return None

        contrasena, ok = QInputDialog.getText(
            self,
            "Autorizar acceso a PDF protegidos",
            f"Ingresá la contraseña de la cuenta {correo}:",
            QLineEdit.EchoMode.Password,
        )
        if not ok or not contrasena:
            return None
        try:
            return self._asegurar_vinculo_seguridad_cuenta(correo, contrasena)
        except ErrorSeguridad as exc:
            QMessageBox.warning(self, "Seguridad", str(exc))
            return None

    def recuperar_contrasena(self):
        dialogo = QMessageBox(self)
        dialogo.setWindowTitle("Recuperar acceso")
        dialogo.setText("¿Qué necesitás recuperar?")
        boton_email = dialogo.addButton("Restablecer contraseña de cuenta por email", QMessageBox.ButtonRole.AcceptRole)
        boton_codigo = dialogo.addButton("Recuperar clave local con código de emergencia", QMessageBox.ButtonRole.ActionRole)
        dialogo.addButton("Cancelar", QMessageBox.ButtonRole.RejectRole)
        dialogo.exec()
        elegido = dialogo.clickedButton()
        if elegido is boton_email:
            self.recuperar_por_email()
        elif elegido is boton_codigo:
            self.recuperar_por_codigo()

    def recuperar_por_email(self, correo_objetivo=None):
        if not self.seguridad.configurado:
            QMessageBox.warning(self, "Recuperación", "La seguridad local todavía no está configurada.")
            return

        correo = (correo_objetivo or self.correo_cuenta_activa or "").strip().lower()
        if not correo:
            sesion = self._leer_json_local(self._ruta_sesion_cuenta(), {})
            correo = str(sesion.get("correo", "")).strip().lower() if sesion.get("activa") else ""
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", correo):
            QMessageBox.warning(self, "Recuperación", "Ingresá el correo de la cuenta que querés recuperar.")
            return

        cuentas_locales = self._leer_json_local(self._ruta_cuentas_instalacion(), {})
        id_instalacion = cuentas_locales.get(correo)
        if not isinstance(id_instalacion, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", id_instalacion):
            if correo == (self.seguridad.correo or "").strip().lower():
                id_instalacion = self.seguridad.id_instalacion
            else:
                QMessageBox.warning(
                    self,
                    "Recuperación",
                    "Esta cuenta no tiene un vínculo local registrado en esta computadora. "
                    "Ingresá con la cuenta desde esta instalación al menos una vez o contactá al administrador de DocuCentral.",
                )
                return

        try:
            respuesta_recuperacion = self._api_post(
                "/solicitar-recuperacion",
                {
                    "id_instalacion": id_instalacion,
                    "correo": correo,
                    "proposito": "recuperación",
                },
            )
            # El servidor devuelve el ID canónico asociado a la cuenta. Esto corrige
            # automáticamente un mapeo local antiguo sin cambiar datos protegidos.
            id_servidor = respuesta_recuperacion.get("id_instalacion")
            if isinstance(id_servidor, str) and re.fullmatch(r"[a-fA-F0-9]{32}", id_servidor):
                id_instalacion = id_servidor
                cuentas_locales[correo] = id_instalacion
                self._guardar_json_local(self._ruta_cuentas_instalacion(), cuentas_locales)
        except ErrorSeguridad as exc:
            QMessageBox.critical(self, "Recuperación", str(exc))
            return

        token, ok = QInputDialog.getText(
            self,
            "Código de recuperación",
            f"Ingresá el código de 6 dígitos enviado al correo de la cuenta:\n{correo}",
        )
        if not ok or not token.strip():
            return

        # Se necesita la clave local para volver a crear el vínculo criptográfico
        # de esta cuenta. Primero intentamos Windows DPAPI y, si no está disponible,
        # permitimos utilizar el código de emergencia local.
        clave_maestra = self.seguridad.clave_maestra
        if not clave_maestra:
            try:
                clave_maestra = self.seguridad.desbloquear_con_recuperacion_windows()
            except ErrorSeguridad:
                codigo, ok_codigo = QInputDialog.getText(
                    self,
                    "Código de emergencia",
                    "Windows no pudo recuperar la clave local. Ingresá el código de emergencia para continuar:",
                )
                if not ok_codigo or not codigo.strip():
                    return
                try:
                    clave_maestra = self.seguridad.desbloquear_con_codigo_recuperacion(codigo.strip().upper())
                except ErrorSeguridad as exc:
                    QMessageBox.warning(self, "Recuperación", str(exc))
                    return

        nueva, ok = QInputDialog.getText(
            self,
            "Nueva contraseña de cuenta",
            "Nueva contraseña de la cuenta (mínimo 8 caracteres):",
            QLineEdit.EchoMode.Password,
        )
        if not ok:
            return
        confirmacion, ok = QInputDialog.getText(
            self,
            "Nueva contraseña de cuenta",
            "Repetí la nueva contraseña:",
            QLineEdit.EchoMode.Password,
        )
        if not ok or len(nueva) < 8 or nueva != confirmacion:
            QMessageBox.warning(self, "Recuperación", "Las contraseñas no coinciden o tienen menos de 8 caracteres.")
            return

        try:
            self._api_post(
                "/restablecer-contrasena",
                {"id_instalacion": id_instalacion, "token": token.strip(), "nueva_contrasena": nueva},
            )
            self.seguridad.clave_maestra = clave_maestra
            self.seguridad.vincular_contrasena_cuenta(correo, nueva)
            QMessageBox.information(
                self,
                "Recuperación completada",
                f"La contraseña de la cuenta {correo} se restableció correctamente.\n\n"
                "La clave de seguridad local, el correo de recuperación de los documentos y las contraseñas reales de los PDF no se modificaron.",
            )
        except ErrorSeguridad as exc:
            QMessageBox.critical(self, "Recuperación", str(exc))

    def recuperar_por_codigo(self):
        if not self.seguridad.configurado:
            return
        code, ok = QInputDialog.getText(
            self,
            "Código de recuperación de emergencia",
            "Ingresá el código de recuperación:",
        )
        if not ok:
            return
        try:
            self.seguridad.desbloquear_con_codigo_recuperacion(code.strip().upper())
            QMessageBox.information(
                self,
                "Seguridad recuperada",
                "La clave de seguridad local se recuperó correctamente.\n\n"
                "El código de emergencia recupera la clave local, pero no cambia la contraseña de la cuenta. "
                "Si olvidaste la contraseña de tu cuenta, elegí ‘Olvidé mi contraseña’ e ingresá el código enviado al correo de esa cuenta.",
            )
        except ErrorSeguridad as exc:
            QMessageBox.warning(self, "Recuperación", str(exc))

    # ========================================================
    # BLOQUEAR / DESBLOQUEAR
    # ========================================================

    def _filas_seleccionadas_documentos(self):
        filas = sorted(set(item.row() for item in self.tabla.selectedItems()))
        return [
            self.documentos_actuales[fila]
            for fila in filas
            if 0 <= fila < len(self.documentos_actuales)
        ]

    def pedir_contrasena_maestra(self, titulo="Autorizar acción"):
        """Solicita y valida la contraseña de la cuenta activa para una acción sensible."""
        correo = (self.correo_cuenta_activa or "").strip().lower()
        if not correo:
            sesion = self._leer_json_local(self._ruta_sesion_cuenta(), {})
            correo = str(sesion.get("correo", "")).strip().lower() if sesion.get("activa") else ""
        if not correo:
            QMessageBox.warning(self, "Cuenta", "No hay una cuenta activa. Ingresá nuevamente a DocuCentral.")
            return None

        contrasena, ok = QInputDialog.getText(
            self,
            titulo,
            f"Ingresá la contraseña de la cuenta {correo} para autorizar esta acción:",
            QLineEdit.EchoMode.Password,
        )
        if not ok or not contrasena:
            return None

        try:
            self._asegurar_vinculo_seguridad_cuenta(correo, contrasena)
            return contrasena
        except ErrorSeguridad as exc:
            QMessageBox.warning(self, "Autorización", str(exc))
            return None

    def _pedir_nueva_contrasena_pdf(self, titulo="Proteger PDF"):
        """Pide una contraseña propia para el PDF; no reutiliza la contraseña de cuenta."""
        contrasena, ok = QInputDialog.getText(
            self, titulo, "Elegí la contraseña real que tendrá el PDF:", QLineEdit.EchoMode.Password
        )
        if not ok or not contrasena:
            return None
        confirmar, ok = QInputDialog.getText(
            self, titulo, "Confirmá la contraseña del PDF:", QLineEdit.EchoMode.Password
        )
        if not ok or not confirmar:
            return None
        if contrasena != confirmar:
            QMessageBox.warning(self, "Contraseña del PDF", "Las contraseñas del PDF no coinciden.")
            return None
        if len(contrasena) < 4:
            QMessageBox.warning(self, "Contraseña del PDF", "Usá una contraseña de al menos 4 caracteres.")
            return None
        return contrasena

    def _crear_pdf_protegido(self, origen, destino, contrasena):
        """Crea un PDF real protegido con contraseña, de forma atómica.

        El PDF se reconstruye página por página en lugar de utilizar
        clone_document_from_reader(). Esto evita problemas de pypdf con
        determinados objetos de cadenas/metadatos de PDFs existentes.
        """
        origen = Path(origen)
        destino = Path(destino)

        try:
            lector = PdfReader(str(origen))
        except Exception as exc:
            raise ErrorSeguridad(
                f"No se pudo leer el PDF de origen: {exc}"
            ) from exc

        if lector.is_encrypted:
            raise ErrorSeguridad(
                "El PDF de origen ya está protegido con contraseña."
            )

        if len(lector.pages) == 0:
            raise ErrorSeguridad(
                "El PDF de origen no contiene páginas."
            )

        escritor = PdfWriter()

        try:
            # Reconstrucción página por página. No copiamos el documento
            # completo ni sus metadatos porque algunos PDFs contienen
            # objetos que provocan el error "Strings must be encoded before
            # hashing" durante el clonado completo.
            for pagina in lector.pages:
                escritor.add_page(pagina)

            escritor.encrypt(
                user_password=contrasena,
                owner_password=contrasena,
                use_128bit=True,
            )
        except Exception as exc:
            raise ErrorSeguridad(
                f"No se pudo preparar el PDF para protección: {exc}"
            ) from exc

        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_name(
            f".{destino.stem}_{uuid.uuid4().hex}.tmp.pdf"
        )

        try:
            with temporal.open("wb") as archivo_salida:
                escritor.write(archivo_salida)
                archivo_salida.flush()
                os.fsync(archivo_salida.fileno())

            # Verificamos que el resultado sea realmente un PDF cifrado y
            # que la contraseña permita abrirlo antes de reemplazar el
            # original.
            verificador = PdfReader(str(temporal))
            if not verificador.is_encrypted:
                raise ErrorSeguridad(
                    "El PDF generado no quedó protegido."
                )

            if verificador.decrypt(contrasena) == 0:
                raise ErrorSeguridad(
                    "No se pudo verificar la contraseña del PDF protegido."
                )

            if len(verificador.pages) == 0:
                raise ErrorSeguridad(
                    "El PDF protegido generado no contiene páginas."
                )

            # El original solo se reemplaza después de verificar el archivo.
            os.replace(temporal, destino)

        except ErrorSeguridad:
            raise
        except Exception as exc:
            raise ErrorSeguridad(
                f"No se pudo crear el PDF protegido: {exc}"
            ) from exc
        finally:
            try:
                if temporal.exists():
                    temporal.unlink()
            except Exception:
                pass

        return destino

    def _crear_pdf_desprotegido(self, origen, destino, contrasena):
        """Quita la contraseña del PDF y lo reemplaza de forma atómica.

        También reconstruye el documento página por página para evitar el
        mismo problema de pypdf que puede aparecer al clonar el documento
        completo.
        """
        origen = Path(origen)
        destino = Path(destino)

        try:
            lector = PdfReader(str(origen))
        except Exception as exc:
            raise ErrorSeguridad(
                f"No se pudo leer el PDF protegido: {exc}"
            ) from exc

        if not lector.is_encrypted:
            raise ErrorSeguridad(
                "El PDF seleccionado no está protegido."
            )

        if lector.decrypt(contrasena) == 0:
            raise ErrorSeguridad(
                "La contraseña del PDF es incorrecta."
            )

        if len(lector.pages) == 0:
            raise ErrorSeguridad(
                "El PDF protegido no contiene páginas."
            )

        escritor = PdfWriter()

        try:
            for pagina in lector.pages:
                escritor.add_page(pagina)
        except Exception as exc:
            raise ErrorSeguridad(
                f"No se pudo reconstruir el PDF desprotegido: {exc}"
            ) from exc

        destino.parent.mkdir(parents=True, exist_ok=True)
        temporal = destino.with_name(
            f".{destino.stem}_{uuid.uuid4().hex}.tmp.pdf"
        )

        try:
            with temporal.open("wb") as archivo_salida:
                escritor.write(archivo_salida)
                archivo_salida.flush()
                os.fsync(archivo_salida.fileno())

            verificador = PdfReader(str(temporal))
            if verificador.is_encrypted:
                raise ErrorSeguridad(
                    "No se pudo quitar la protección del PDF."
                )

            if len(verificador.pages) == 0:
                raise ErrorSeguridad(
                    "El PDF desprotegido generado no contiene páginas."
                )

            os.replace(temporal, destino)

        except ErrorSeguridad:
            raise
        except Exception as exc:
            raise ErrorSeguridad(
                f"No se pudo crear el PDF desprotegido: {exc}"
            ) from exc
        finally:
            try:
                if temporal.exists():
                    temporal.unlink()
            except Exception:
                pass

        return destino

    def bloquear_seleccionados(self):
        documentos = self._filas_seleccionadas_documentos()
        if not documentos:
            QMessageBox.information(self, "Seguridad", "No seleccionaste ningún documento.")
            return

        pendientes = [d for d in documentos if not d[9]]
        if not pendientes:
            QMessageBox.information(self, "Seguridad", "Los documentos seleccionados ya están protegidos.")
            return

        if not self.pedir_contrasena_maestra("Autorizar protección de documentos"):
            return
        contrasena_pdf = self._pedir_nueva_contrasena_pdf("Proteger PDF")
        if not contrasena_pdf:
            return

        conexion = conectar_db()
        cursor = conexion.cursor()
        protegidos = 0
        errores = []

        for documento in pendientes:
            id_documento, nombre, ruta, ruta_original, fecha_carga, paginas, texto, fecha_documento, resumen, sensible = documento
            source = Path(ruta)
            try:
                if not source.exists():
                    raise ErrorSeguridad(f"No existe el archivo:\n{source}")
                if source.suffix.lower() != ".pdf":
                    raise ErrorSeguridad("El archivo seleccionado no es un PDF.")

                # El PDF protegido reemplaza al original en la misma ubicación.
                # Se verifica primero y recién después se hace os.replace().
                self._crear_pdf_protegido(source, source, contrasena_pdf)

                cursor.execute(
                    """
                    UPDATE documentos
                    SET ruta=?, ruta_original=?, texto=NULL, resumen=NULL, sensible=1
                    WHERE id=?
                    """,
                    (str(source), str(source), id_documento),
                )
                protegidos += 1
            except Exception as exc:
                errores.append(f"{nombre}: {exc}")

        conexion.commit()
        conexion.close()
        self.cargar_documentos()

        mensaje = (
            f"Documentos protegidos: {protegidos}\n\n"
            "Los PDF seleccionados fueron reemplazados por versiones protegidas.\n"
            "La contraseña real del PDF es la que acabás de elegir, independiente de la contraseña de tu cuenta.\n\n"
            "Al abrirlos fuera de DocuCentral, el visor de PDF también solicitará la contraseña propia del PDF."
        )
        if errores:
            mensaje += "\n\nErrores:\n" + "\n".join(errores)
        QMessageBox.information(self, "Seguridad", mensaje)

    def desbloquear_seleccionados(self):
        documentos = self._filas_seleccionadas_documentos()
        if not documentos:
            QMessageBox.information(self, "Seguridad", "No seleccionaste ningún documento.")
            return

        pendientes = [d for d in documentos if d[9]]
        if not pendientes:
            QMessageBox.information(self, "Seguridad", "No seleccionaste documentos protegidos.")
            return

        if not self.pedir_contrasena_maestra("Autorizar desprotección de documentos"):
            return

        conexion = conectar_db()
        cursor = conexion.cursor()
        desbloqueados = 0
        errores = []

        for documento in pendientes:
            id_documento, nombre, ruta, ruta_original, fecha_carga, paginas, texto, fecha_documento, resumen, sensible = documento
            try:
                secure_path = Path(ruta)
                if not secure_path.exists():
                    raise ErrorSeguridad(f"No existe el archivo protegido:\n{secure_path}")

                # --------------------------------------------------------
                # COMPATIBILIDAD CON EL FORMATO .DCP ANTIGUO
                # --------------------------------------------------------
                # Los documentos protegidos por versiones anteriores de
                # DocuCentral no son PDF: son contenedores DC01 cifrados.
                # Primero los desciframos con la clave maestra y los
                # convertimos nuevamente en un PDF normal.
                if secure_path.suffix.lower() == ".dcp":
                    clave_maestra = self.seguridad.clave_maestra
                    if not clave_maestra:
                        raise ErrorSeguridad("No hay una clave maestra disponible para migrar el documento antiguo.")

                    datos_pdf = self.seguridad.descifrar_archivo_a_bytes(
                        secure_path,
                        clave_maestra,
                    )

                    destino = Path(ruta_original) if ruta_original else (
                        DATA_DIR / "restored" / nombre
                    )
                    if destino.suffix.lower() != ".pdf":
                        destino = destino.with_suffix(".pdf")
                    destino.parent.mkdir(parents=True, exist_ok=True)

                    if destino.exists():
                        respuesta = QMessageBox.question(
                            self,
                            "Archivo existente",
                            f"El PDF original ya existe en:\n{destino}\n\n"
                            "¿Querés reemplazarlo con la copia recuperada desde DocuCentral?",
                            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                            QMessageBox.StandardButton.No,
                        )
                        if respuesta != QMessageBox.StandardButton.Yes:
                            continue

                    temporal = destino.with_name(
                        f".{destino.stem}_{uuid.uuid4().hex}.tmp.pdf"
                    )
                    try:
                        temporal.write_bytes(datos_pdf)

                        # Verificamos que los datos recuperados sean realmente
                        # un PDF válido antes de eliminar el .dcp.
                        verificador = PdfReader(str(temporal))
                        if verificador.is_encrypted:
                            raise ErrorSeguridad(
                                "El documento antiguo fue recuperado, pero el PDF resultante todavía está protegido."
                            )
                        if len(verificador.pages) == 0:
                            raise ErrorSeguridad("El PDF recuperado no contiene páginas.")

                        os.replace(temporal, destino)
                    finally:
                        try:
                            if temporal.exists():
                                temporal.unlink()
                        except Exception:
                            pass

                    texto_restaurado, paginas_restauradas = leer_pdf(destino)
                    fecha_restaurada = detectar_fecha(texto_restaurado)
                    resumen_restaurado = generar_resumen(texto_restaurado)

                    cursor.execute(
                        """
                        UPDATE documentos
                        SET ruta=?, ruta_original=?, paginas=?, texto=?, fecha_documento=?, resumen=?, sensible=0
                        WHERE id=?
                        """,
                        (
                            str(destino), str(destino),
                            paginas_restauradas or paginas,
                            texto_restaurado,
                            fecha_restaurada or fecha_documento,
                            resumen_restaurado,
                            id_documento,
                        ),
                    )

                    # El .dcp queda eliminado solamente después de verificar
                    # que el PDF recuperado existe y puede abrirse.
                    try:
                        secure_path.unlink()
                    except Exception as exc:
                        # El PDF ya fue migrado y la base quedó actualizada.
                        # Si Windows impide borrar el .dcp, informamos el
                        # inconveniente pero no destruimos el PDF recuperado.
                        errores.append(
                            f"{nombre}: PDF migrado correctamente, pero no se pudo eliminar el .dcp antiguo: {exc}"
                        )

                    desbloqueados += 1
                    continue

                # --------------------------------------------------------
                # PDF PROTEGIDO CON EL SISTEMA NUEVO
                # --------------------------------------------------------
                # La cuenta autoriza la operación, pero el PDF conserva su contraseña real.
                # Se pide la contraseña propia del archivo, no la de la cuenta.
                contrasena_pdf, ok_pdf = QInputDialog.getText(
                    self,
                    "Contraseña del PDF",
                    f"Ingresá la contraseña real del PDF:\n{nombre}",
                    QLineEdit.EchoMode.Password,
                )
                if not ok_pdf or not contrasena_pdf:
                    continue
                self._crear_pdf_desprotegido(secure_path, secure_path, contrasena_pdf)
                texto_restaurado, paginas_restauradas = leer_pdf(secure_path)
                fecha_restaurada = detectar_fecha(texto_restaurado)
                resumen_restaurado = generar_resumen(texto_restaurado)
                cursor.execute(
                    """
                    UPDATE documentos
                    SET ruta=?, ruta_original=?, paginas=?, texto=?, fecha_documento=?, resumen=?, sensible=0
                    WHERE id=?
                    """,
                    (
                        str(secure_path), str(secure_path), paginas_restauradas or paginas,
                        texto_restaurado, fecha_restaurada or fecha_documento,
                        resumen_restaurado, id_documento,
                    ),
                )
                desbloqueados += 1
            except Exception as exc:
                errores.append(f"{nombre}: {exc}")

        conexion.commit()
        conexion.close()
        self.cargar_documentos()

        mensaje = f"Documentos desprotegidos: {desbloqueados}"
        if errores:
            mensaje += "\n\nErrores:\n" + "\n".join(errores)
        QMessageBox.information(self, "Seguridad", mensaje)

    # ========================================================
    # ABRIR PDF
    # ========================================================

    def abrir_documento(self, fila, columna):
        if fila < 0 or fila >= len(self.documentos_actuales):
            return

        documento = self.documentos_actuales[fila]
        id_documento, nombre, ruta, ruta_original, fecha_carga, paginas, texto, fecha_documento, resumen, sensible = documento

        archivo = Path(ruta)
        if not archivo.exists():
            QMessageBox.warning(
                self,
                "DocuCentral",
                f"El archivo ya no existe en esa ubicación.\n\n{ruta}",
            )
            return

        if sensible:
            # Los .dcp pertenecen al formato de seguridad anterior. No se
            # abren directamente porque no son PDF. Primero deben migrarse
            # mediante "Desbloquear seleccionados".
            if archivo.suffix.lower() == ".dcp":
                QMessageBox.information(
                    self,
                    "Documento protegido antiguo",
                    "Este documento fue protegido con una versión anterior de DocuCentral.\n\n"
                    "No se puede abrir directamente porque el archivo .dcp no es un PDF.\n\n"
                    "Usá «Desbloquear seleccionados» para recuperarlo y convertirlo al nuevo sistema de protección.",
                )
                return

            # El archivo protegido es ahora un PDF real con contraseña.
            # Se abre directamente para que el visor PDF solicite la contraseña;
            # de esta forma nunca se crea un PDF temporal sin protección.
            try:
                os.startfile(str(archivo))
                return
            except Exception as exc:
                QMessageBox.warning(self, "Documento protegido", f"No se pudo abrir el PDF protegido.\n\n{exc}")
                return

        try:
            os.startfile(str(archivo))
        except Exception as exc:
            QMessageBox.warning(self, "DocuCentral", f"No se pudo abrir el documento.\n\n{exc}")

    def limpiar_temporales_pdf_antiguos(self):
        """Elimina copias temporales de PDF con mas de 24 horas."""
        try:
            temp_dir = Path(tempfile.gettempdir()) / "DocuCentral"
            if not temp_dir.exists():
                return

            ahora = time.time()
            antiguedad_maxima = 24 * 60 * 60

            for archivo in temp_dir.iterdir():
                if not archivo.is_file():
                    continue
                try:
                    if ahora - archivo.stat().st_mtime > antiguedad_maxima:
                        archivo.unlink()
                except Exception:
                    pass
        except Exception:
            pass

    def closeEvent(self, event):
        for temp_path in list(self._temporary_files):
            try:
                if temp_path.exists():
                    temp_path.unlink()
            except Exception:
                pass
        self._temporary_files.clear()
        super().closeEvent(event)
# ============================================================

# ESTILO GENERAL

# ============================================================



def aplicar_estilo_oscuro(app):



    app.setStyleSheet(

        """

        /* ==================================================

           GENERAL

           ================================================== */



        QWidget {

            background-color: #0f0f0f;

            color: #ffffff;

            font-size: 13px;

        }



        QMainWindow {

            background-color: #0f0f0f;

        }



        /* ==================================================

           BOTONES

           ================================================== */



        QPushButton {

            background-color: #2f2f2f;

            color: #ffffff;

            border: 1px solid #454545;

            border-radius: 6px;

            padding: 7px 12px;

        }



        QPushButton:hover {

            background-color: #3a3a3a;

            border: 1px solid #606060;

        }



        QPushButton:pressed {

            background-color: #242424;

        }



        QPushButton:disabled {

            background-color: #1c1c1c;

            color: #666666;

            border: 1px solid #292929;

        }



        /* ==================================================

           CAMPO DE BÚSQUEDA

           ================================================== */



        QLineEdit {

            background-color: #2f2f2f;

            color: #ffffff;

            border: 1px solid #474747;

            border-radius: 6px;

            padding: 8px 10px;

            selection-background-color: #5a5a5a;

            selection-color: #ffffff;

        }



        QLineEdit:focus {

            border: 1px solid #707070;

        }



        QLineEdit::placeholder {

            color: #999999;

        }



        /* ==================================================

           COMBOBOX

           ================================================== */



        QComboBox {

            background-color: #2f2f2f;

            color: #ffffff;

            border: 1px solid #474747;

            border-radius: 6px;

            padding: 7px 34px 7px 10px;
        }

        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 30px;
            border: none;
            border-left: 1px solid #454545;
            background-color: #2f2f2f;
            border-top-right-radius: 6px;
            border-bottom-right-radius: 6px;
        }

        QComboBox::drop-down:hover {
            background-color: #3a3a3a;
        }

        QComboBox::down-arrow {
            image: none;
        }

        QComboBox:hover {

            border: 1px solid #606060;

        }



        QComboBox QAbstractItemView {

            background-color: #2f2f2f;

            color: #ffffff;

            selection-background-color: #4a4a4a;

            selection-color: #ffffff;

            border: 1px solid #555555;

        }



        /* ==================================================

           TABLA

           ================================================== */



        QTableWidget {

            background-color: #1b1b1b;

            alternate-background-color: #222222;

            color: #ffffff;

            gridline-color: #383838;

            border: 1px solid #3f3f3f;

            border-radius: 5px;

            selection-background-color: #454545;

            selection-color: #ffffff;

        }



        QTableWidget::item {

            padding: 5px;
            border: none;
            outline: none;

        }

        QTableWidget::item:focus {

            border: none;
            outline: none;

        }

        QTableWidget::item:selected {

            background-color: #4a4a4a;

            color: #ffffff;

        }



        QHeaderView::section {

            background-color: #2f2f2f;

            color: #ffffff;

            padding: 7px;

            border: 1px solid #454545;

            font-weight: bold;

        }



        QHeaderView::section:hover {

            background-color: #3a3a3a;

        }



        /* ==================================================

           PANEL DE DETALLE

           ================================================== */



        QTextEdit {

            background-color: #2f2f2f;

            color: #ffffff;

            border: 1px solid #454545;

            border-radius: 5px;

            padding: 8px;

            selection-background-color: #5a5a5a;

            selection-color: #ffffff;

        }




        /* ==================================================
           CARPETAS
           ================================================== */

        QFrame#panelCarpetas {
            background-color: #2a2a2a;
            border: 1px solid #3b3b3b;
            border-radius: 10px;
        }

        QLabel#tituloCarpetas {
            color: #ffffff;
            font-weight: bold;
            padding: 2px 4px;
        }

        QTreeWidget#arbolCarpetas {
            background-color: #1b1b1b;
            color: #ffffff;
            border: 1px solid #3f3f3f;
            border-radius: 7px;
            padding: 4px;
            outline: none;
        }

        QTreeWidget#arbolCarpetas::item {
            padding: 5px 4px;
            border-radius: 5px;
        }

        QTreeWidget#arbolCarpetas::item:selected {
            background-color: #4a4a4a;
            color: #ffffff;
        }

        QTreeWidget#arbolCarpetas::item:hover {
            background-color: #343434;
        }

        /* ==================================================

           SPLITTER

           ================================================== */



        QScrollArea#scrollPrincipal {
            background-color: #0f0f0f;
            border: none;
        }

        QScrollArea#scrollPrincipal > QWidget > QWidget {
            background-color: #0f0f0f;
        }

        QFrame#detalleCard {
            background-color: #2a2a2a;
            border: 1px solid #3b3b3b;
            border-radius: 12px;
        }

        QTextEdit#detalleTextoDocumento {
            background-color: #171717;
            color: #eeeeee;
            border: 1px solid #3b3b3b;
            border-radius: 9px;
            padding: 12px;
            selection-background-color: #4a4a4a;
            selection-color: #ffffff;
        }

        QScrollBar:vertical {
            background-color: #181818;
            width: 12px;
            margin: 2px;
            border-radius: 6px;
        }

        QScrollBar::handle:vertical {
            background-color: #4a4a4a;
            min-height: 40px;
            border-radius: 6px;
        }

        QScrollBar::handle:vertical:hover {
            background-color: #606060;
        }

        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {
            height: 0px;
        }

        QSplitter::handle {
            background-color: transparent;
        }

        QSplitter::handle:hover {
            background-color: transparent;
        }

        /* Divisor interno del detalle: visible y arrastrable. */
        #detalleSplitter::handle {
            background-color: #454545;
            border-radius: 4px;
            margin: 2px 80px;
        }

        #detalleSplitter::handle:hover {
            background-color: #666666;
        }

        #detalleSplitter::handle:vertical {
            height: 8px;
        }



        /* ==================================================
           PANEL DE DETALLE
           ================================================== */

        #detalleTitulo {
            color: #ffffff;
            font-size: 18px;
            font-weight: bold;
            padding: 2px 4px;
        }

        #detalleContenido {
            background-color: transparent;
            border: none;
            border-radius: 10px;
        }

        #detalleCard {
            background-color: #2a2a2a;
            border: 1px solid #3b3b3b;
            border-radius: 8px;
        }

        #detalleCardPlano {
            background-color: #2a2a2a;
            border: 1px solid #3b3b3b;
            border-radius: 8px;
        }

        #detalleCardPlano QLabel {
            color: #eeeeee;
            font-size: 12px;
        }

        #detalleSeccion {
            background-color: transparent;
            color: #b8b8b8;
            font-size: 12px;
            font-weight: bold;
            letter-spacing: 0px;
            padding: 12px;
            margin: 0px;
        }

        #detalleCard QLabel {
            color: #eeeeee;
            font-size: 12px;
        }

        #detalleInfoItem {
            background-color: #242424;
            border: 1px solid #3e3e3e;
            border-radius: 7px;
            color: #eeeeee;
            font-size: 12px;
            padding: 8px 10px;
        }

        #detalleInfoItem:hover {
            border: 1px solid #555555;
            background-color: #292929;
        }

        #detalleResumenTexto {
            color: #eeeeee;
            font-size: 12px;
            line-height: 1.35em;
            background-color: transparent;
            padding: 0px 10px;
        }

        #detalleResumenTexto[placeholder="true"] {
            color: #777777;
        }

        #detalleSuperiorScroll {
            background-color: transparent;
            border: none;
        }

        #detalleCard QTextEdit {
            background-color: #202020;
            color: #eeeeee;
            border: 1px solid #3f3f3f;
            border-radius: 6px;
            padding: 12px 16px;
            selection-background-color: #4a4a4a;
            selection-color: #ffffff;
            font-size: 12pt;
        }

        /* ==================================================

           SCROLLBARS

           ================================================== */



        QScrollBar:vertical {

            background-color: #181818;

            width: 12px;

            margin: 0px;

        }



        QScrollBar::handle:vertical {

            background-color: #4a4a4a;

            min-height: 30px;

            border-radius: 5px;

        }



        QScrollBar::handle:vertical:hover {

            background-color: #606060;

        }



        QScrollBar::add-line:vertical,

        QScrollBar::sub-line:vertical {

            background: none;

            border: none;

        }



        QScrollBar:horizontal {

            background-color: #181818;

            height: 12px;

            margin: 0px;

        }



        QScrollBar::handle:horizontal {

            background-color: #4a4a4a;

            min-width: 30px;

            border-radius: 5px;

        }



        QScrollBar::handle:horizontal:hover {

            background-color: #606060;

        }



        QScrollBar::add-line:horizontal,

        QScrollBar::sub-line:horizontal {

            background: none;

            border: none;

        }



        /* ==================================================

           PROGRESS DIALOG

           ================================================== */



        QProgressDialog {

            background-color: #1b1b1b;

            color: #ffffff;

        }



        QProgressBar {

            background-color: #2f2f2f;

            color: #ffffff;

            border: 1px solid #454545;

            border-radius: 5px;

            text-align: center;

        }



        QProgressBar::chunk {

            background-color: #666666;

            border-radius: 4px;

        }



        /* ==================================================

           MENSAJES

           ================================================== */



        QMessageBox {

            background-color: #1b1b1b;

            color: #ffffff;

        }



        QMessageBox QLabel {

            color: #ffffff;

        }

        """

    )





# ============================================================

# INICIO

# ============================================================



def main():
    inicializar_base_datos()
    actualizar_estructura_base_datos()

    app = QApplication(sys.argv)
    pixmap_icono = QPixmap(str(LOGO_DOCUCENTRAL))
    if not pixmap_icono.isNull():
        app.setWindowIcon(QIcon(pixmap_icono))
    aplicar_estilo_oscuro(app)

    ventana = DocuCentral()

    # La pantalla de inicio se muestra en cada arranque. No se abre la biblioteca
    # automáticamente aunque haya una sesión local guardada.
    while True:
        inicio = VentanaInicioDocuCentral(ventana)
        resultado = inicio.exec()
        accion = inicio.accion
        if accion == "salir" or resultado != QDialog.DialogCode.Accepted:
            return

        if accion == "autenticar_actual":
            if not ventana.verificar_configuracion_seguridad():
                continue
            sesion = ventana._leer_json_local(ventana._ruta_sesion_cuenta(), {})
            correo_actual = str(sesion.get("correo", "")).strip().lower() if sesion.get("activa") else ""
            if not correo_actual:
                QMessageBox.information(
                    ventana, "Vinculación requerida",
                    "No hay un usuario vinculado. Elegí la opción para vincular o ingresar con otra cuenta."
                )
                continue
            if ventana.autenticar_cuenta(correo_sugerido=correo_actual):
                break
            continue

        if accion == "vincular":
            seguridad_lista_antes = (
                ventana.seguridad.configurado
                and ventana.seguridad.email_verificado
                and bool(ventana.seguridad.id_instalacion)
                and (ventana.seguridad.correo or "").strip().lower()
                    != CORREO_RECUPERACION_DOCUCENTRAL.strip().lower()
            )
            if not ventana.verificar_configuracion_seguridad():
                continue

            if seguridad_lista_antes:
                # Instalación ya configurada: validar la cuenta del cliente por separado.
                if not ventana.autenticar_cuenta():
                    continue
            else:
                # En la primera configuración, el asistente registra/verifica la cuenta
                # y crea la seguridad local. No se vuelve a pedir el registro inmediatamente.
                correo_seguridad = (ventana.seguridad.correo or "").strip().lower()
                if not correo_seguridad or not ventana.seguridad.email_verificado:
                    QMessageBox.warning(
                        ventana, "Vinculación incompleta",
                        "No se pudo confirmar la cuenta. Volvé a intentar la vinculación."
                    )
                    continue
                try:
                    ventana._guardar_sesion_cuenta(correo_seguridad, True)
                except ErrorSeguridad as exc:
                    QMessageBox.critical(ventana, "Sesión", str(exc))
                    continue
            break

    ventana.show()
    sys.exit(app.exec())


# ============================================================

# EJECUCIÓN

# ============================================================



if __name__ == "__main__":

    main()
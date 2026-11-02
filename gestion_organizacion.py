"""Gestión de organización y equipos para DocuCentral."""
import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox,
    QInputDialog, QLineEdit, QFormLayout, QSpinBox, QGroupBox
)


class DialogoOrganizacion(QDialog):
    def __init__(self, ventana_app, data_dir, parent=None):
        super().__init__(parent or ventana_app)
        self.app = ventana_app
        self.data_dir = Path(data_dir)
        self.archivo_estado = self.data_dir / "organizacion_docucentral.json"
        sesion = self.app._leer_json_local(self.app._ruta_sesion_cuenta(), {})
        self.correo = str(sesion.get("correo", "")).strip().lower() if sesion.get("activa") else ""
        cuentas_locales = self.app._leer_json_local(self.app._ruta_cuentas_instalacion(), {})
        self.id_instalacion = str(cuentas_locales.get(self.correo, "")).strip() if self.correo else ""
        self.contrasena = ""
        self.organizacion_id = self._leer_organizacion_id()

        self.setWindowTitle("DocuCentral · Organización y equipos")
        self.setMinimumWidth(620)
        self.setModal(True)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        encabezado = QLabel("Administración de organización")
        encabezado.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(encabezado)

        info = QLabel(
            "Creá una organización desde la PC administradora. En cada PC adicional, "
            "registrá/verificá primero su cuenta de DocuCentral y luego vinculala con un código temporal. "
            "Los PDF permanecen en cada equipo."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #b8b8b8;")
        layout.addWidget(info)

        grupo_org = QGroupBox("Organización")
        form = QFormLayout(grupo_org)
        self.nombre_org = QLineEdit()
        self.nombre_org.setPlaceholderText("Ej.: Administración Central")
        self.cupo = QSpinBox()
        self.cupo.setRange(1, 500)
        self.cupo.setValue(5)
        form.addRow("Nombre:", self.nombre_org)
        form.addRow("Máximo de PC:", self.cupo)
        layout.addWidget(grupo_org)

        fila = QHBoxLayout()
        self._boton(fila, "Crear organización", self.crear_organizacion)
        self._boton(fila, "Vincular esta PC con código", self.vincular_con_codigo)
        layout.addLayout(fila)

        grupo_admin = QGroupBox("Administrar equipos")
        admin_layout = QVBoxLayout(grupo_admin)
        fila2 = QHBoxLayout()
        self._boton(fila2, "Generar código", self.generar_codigo)
        self._boton(fila2, "Ver organización", self.consultar)
        self._boton(fila2, "Actualizar cupo", self.actualizar_cupo)
        admin_layout.addLayout(fila2)
        fila3 = QHBoxLayout()
        self._boton(fila3, "Crear oficina", self.crear_oficina)
        self._boton(fila3, "Asignar PC a oficina", self.asignar_oficina)
        self._boton(fila3, "Revocar PC", self.revocar_instalacion)
        admin_layout.addLayout(fila3)
        fila4 = QHBoxLayout()
        self._boton(fila4, "Agregar miembro", self.agregar_miembro)
        self._boton(fila4, "Quitar miembro", self.quitar_miembro)
        self._boton(fila4, "Ver auditoría", self.ver_auditoria)
        admin_layout.addLayout(fila4)
        fila5 = QHBoxLayout()
        self._boton(fila5, "Comprobar estado de esta PC", self.estado_esta_pc)
        admin_layout.addLayout(fila5)
        layout.addWidget(grupo_admin)

        self.etiqueta_estado = QLabel()
        self.etiqueta_estado.setWordWrap(True)
        self.etiqueta_estado.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.etiqueta_estado)
        self._actualizar_etiqueta()

        cerrar = QPushButton("Cerrar")
        cerrar.clicked.connect(self.accept)
        layout.addWidget(cerrar, alignment=Qt.AlignmentFlag.AlignRight)

        if not self.correo or not self.id_instalacion:
            QMessageBox.warning(
                self, "Cuenta no configurada",
                "Esta instalación no tiene correo e identificador de seguridad configurados. "
                "Completá primero el registro/verificación normal de DocuCentral."
            )
            self.setEnabled(False)
            return

        self._pedir_contrasena()

    def _boton(self, layout, texto, callback):
        boton = QPushButton(texto)
        boton.clicked.connect(callback)
        layout.addWidget(boton)
        return boton

    def _leer_organizacion_id(self):
        try:
            data = json.loads(self.archivo_estado.read_text(encoding="utf-8"))
            return str(data.get("organizacion_id", "")).strip()
        except Exception:
            return ""

    def _guardar_organizacion_id(self, valor):
        self.organizacion_id = str(valor or "").strip()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.archivo_estado.write_text(
            json.dumps({"organizacion_id": self.organizacion_id}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._actualizar_etiqueta()

    def _actualizar_etiqueta(self):
        org = self.organizacion_id or "No vinculada / no seleccionada"
        self.etiqueta_estado.setText(
            f"Cuenta: {self.correo}\nID de esta instalación: {self.id_instalacion}\nOrganización guardada: {org}"
        )

    def _pedir_contrasena(self):
        pwd, ok = QInputDialog.getText(
            self, "Autenticación de organización",
            f"Confirmá la contraseña de la cuenta {self.correo}:",
            QLineEdit.EchoMode.Password,
        )
        if not ok or not pwd:
            self.contrasena = ""
            return
        self.contrasena = pwd

    def _base(self):
        if not self.contrasena:
            raise RuntimeError("Cerrá y volvé a abrir el panel para autenticarte.")
        return {
            "correo": self.correo,
            "contrasena_cuenta": self.contrasena,
            "id_instalacion": self.id_instalacion,
        }

    def _post(self, endpoint, extra=None):
        payload = self._base()
        if extra:
            payload.update(extra)
        return self.app._api_post(endpoint, payload)

    def _requiere_org(self):
        if not self.organizacion_id:
            QMessageBox.information(
                self, "Organización",
                "Primero creá una organización en la PC administradora o vinculá esta PC con un código."
            )
            return False
        return True

    def _error(self, titulo, exc):
        QMessageBox.critical(self, titulo, str(exc))

    def crear_organizacion(self):
        nombre = self.nombre_org.text().strip()
        if len(nombre) < 2:
            QMessageBox.warning(self, "Organización", "Ingresá un nombre de al menos 2 caracteres.")
            return
        try:
            r = self._post("/organizaciones/crear", {
                "nombre": nombre, "max_instalaciones": self.cupo.value()
            })
            self._guardar_organizacion_id(r["organizacion_id"])
            QMessageBox.information(
                self, "Organización creada",
                f"Organización: {r['nombre']}\nID: {r['organizacion_id']}\nCupo: {r['max_instalaciones']} PC\n\n"
                "Guardá el ID por seguridad. Desde esta PC ya podés generar códigos para vincular otros equipos."
            )
        except Exception as exc:
            self._error("No se pudo crear la organización", exc)

    def vincular_con_codigo(self):
        codigo, ok = QInputDialog.getText(
            self, "Vincular equipo", "Pegá el código temporal generado por la PC administradora:"
        )
        if not ok or not codigo.strip():
            return
        try:
            r = self._post("/organizaciones/vincular-instalacion", {"codigo": codigo.strip()})
            self._guardar_organizacion_id(r["organizacion_id"])
            QMessageBox.information(self, "Equipo vinculado", "Esta PC quedó vinculada a la organización.")
        except Exception as exc:
            self._error("No se pudo vincular la PC", exc)

    def generar_codigo(self):
        if not self._requiere_org():
            return
        minutos, ok = QInputDialog.getInt(self, "Código temporal", "Validez en minutos (5–60):", 15, 5, 60)
        if not ok:
            return
        try:
            r = self._post("/organizaciones/codigo-vinculacion", {
                "organizacion_id": self.organizacion_id, "minutos_validez": minutos
            })
            QMessageBox.information(
                self, "Código de vinculación",
                f"Código (un solo uso):\n\n{r['codigo']}\n\nVence: {r['expira_en']}\n\n"
                "Compartilo únicamente con la persona que va a vincular la PC."
            )
        except Exception as exc:
            self._error("No se pudo generar el código", exc)

    def consultar(self):
        if not self._requiere_org():
            return
        try:
            r = self._post("/organizaciones/consultar", {"organizacion_id": self.organizacion_id})
            QMessageBox.information(self, "Organización", json.dumps(r, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:
            self._error("No se pudo consultar la organización", exc)

    def actualizar_cupo(self):
        if not self._requiere_org():
            return
        cupo, ok = QInputDialog.getInt(self, "Cupo de licencia", "Máximo de instalaciones:", 5, 1, 500)
        if not ok:
            return
        try:
            r = self._post("/organizaciones/cupo/actualizar", {
                "organizacion_id": self.organizacion_id, "max_instalaciones": cupo
            })
            QMessageBox.information(self, "Cupo actualizado", f"Nuevo máximo: {r['max_instalaciones']} PC")
        except Exception as exc:
            self._error("No se pudo actualizar el cupo", exc)

    def crear_oficina(self):
        if not self._requiere_org():
            return
        nombre, ok = QInputDialog.getText(self, "Crear oficina", "Nombre de la oficina:")
        if not ok or len(nombre.strip()) < 2:
            return
        try:
            r = self._post("/organizaciones/oficinas/crear", {
                "organizacion_id": self.organizacion_id, "nombre": nombre.strip()
            })
            QMessageBox.information(self, "Oficina creada", f"{r['nombre']}\nID de oficina: {r['oficina_id']}")
        except Exception as exc:
            self._error("No se pudo crear la oficina", exc)

    def asignar_oficina(self):
        if not self._requiere_org():
            return
        iid, ok = QInputDialog.getText(self, "Asignar PC", "ID de instalación de la PC:")
        if not ok or not iid.strip():
            return
        oficina, ok = QInputDialog.getText(self, "Asignar PC", "ID de la oficina:")
        if not ok or not oficina.strip():
            return
        try:
            self._post("/organizaciones/oficinas/asignar-instalacion", {
                "organizacion_id": self.organizacion_id,
                "instalacion_objetivo": iid.strip(), "oficina_id": oficina.strip()
            })
            QMessageBox.information(self, "Asignación", "La PC fue asignada a la oficina.")
        except Exception as exc:
            self._error("No se pudo asignar la PC", exc)

    def revocar_instalacion(self):
        if not self._requiere_org():
            return
        iid, ok = QInputDialog.getText(
            self, "Revocar instalación", "ID de instalación que querés revocar:"
        )
        if not ok or not iid.strip():
            return
        confirmar = QMessageBox.question(
            self, "Confirmar revocación",
            f"¿Revocar la instalación {iid.strip()}? El equipo dejará de estar autorizado al consultar el servidor.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmar != QMessageBox.StandardButton.Yes:
            return
        try:
            self._post("/organizaciones/instalaciones/revocar", {
                "organizacion_id": self.organizacion_id, "instalacion_objetivo": iid.strip()
            })
            QMessageBox.information(self, "Instalación revocada", "La instalación quedó revocada en el servidor.")
        except Exception as exc:
            self._error("No se pudo revocar la instalación", exc)

    def agregar_miembro(self):
        if not self._requiere_org():
            return
        correo, ok = QInputDialog.getText(self, "Agregar miembro", "Correo de la cuenta DocuCentral:")
        if not ok or not correo.strip():
            return
        rol, ok = QInputDialog.getItem(self, "Rol del miembro", "Seleccioná el rol:", ["miembro", "admin"], 0, False)
        if not ok:
            return
        try:
            r = self._post("/organizaciones/miembros/agregar", {
                "organizacion_id": self.organizacion_id,
                "correo_miembro": correo.strip().lower(),
                "rol": rol,
            })
            QMessageBox.information(self, "Miembro agregado", f"{r['correo_miembro']} · rol: {r['rol']}")
        except Exception as exc:
            self._error("No se pudo agregar el miembro", exc)

    def quitar_miembro(self):
        if not self._requiere_org():
            return
        correo, ok = QInputDialog.getText(self, "Quitar miembro", "Correo del miembro:")
        if not ok or not correo.strip():
            return
        confirmar = QMessageBox.question(
            self, "Confirmar", f"¿Desactivar al miembro {correo.strip()}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirmar != QMessageBox.StandardButton.Yes:
            return
        try:
            self._post("/organizaciones/miembros/quitar", {
                "organizacion_id": self.organizacion_id,
                "correo_miembro": correo.strip().lower(),
            })
            QMessageBox.information(self, "Miembro desactivado", "Se quitó el acceso del miembro a la organización.")
        except Exception as exc:
            self._error("No se pudo quitar el miembro", exc)

    def ver_auditoria(self):
        if not self._requiere_org():
            return
        try:
            r = self._post("/organizaciones/auditoria", {"organizacion_id": self.organizacion_id})
            QMessageBox.information(self, "Auditoría de organización", json.dumps(r, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:
            self._error("No se pudo consultar la auditoría", exc)

    def estado_esta_pc(self):
        try:
            extra = {"organizacion_id": self.organizacion_id} if self.organizacion_id else {}
            r = self._post("/organizaciones/estado-instalacion", extra)
            QMessageBox.information(self, "Estado de esta PC", json.dumps(r, ensure_ascii=False, indent=2, default=str))
        except Exception as exc:
            self._error("No se pudo comprobar el estado", exc)

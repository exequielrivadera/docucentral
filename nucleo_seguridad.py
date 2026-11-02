import base64
import ctypes
import json
import os
import secrets
from ctypes import wintypes
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


class ErrorSeguridad(Exception):
    pass


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


crypt32 = ctypes.windll.crypt32
kernel32 = ctypes.windll.kernel32


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    blob = _DATA_BLOB(
        len(data),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
    )
    return blob, buffer


def proteger_con_dpapi(data: bytes) -> bytes:
    in_blob, _ = _blob(data)
    out_blob = _DATA_BLOB()

    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise ErrorSeguridad(
            "Windows no pudo proteger el secreto local."
        )

    try:
        return ctypes.string_at(
            out_blob.pbData,
            out_blob.cbData,
        )
    finally:
        kernel32.LocalFree(out_blob.pbData)


def recuperar_con_dpapi(data: bytes) -> bytes:
    in_blob, _ = _blob(data)
    out_blob = _DATA_BLOB()

    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise ErrorSeguridad(
            "Windows no pudo recuperar el secreto local. "
            "Puede pertenecer a otro usuario de Windows."
        )

    try:
        return ctypes.string_at(
            out_blob.pbData,
            out_blob.cbData,
        )
    finally:
        kernel32.LocalFree(out_blob.pbData)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _unb64(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value.encode("ascii"))
    except Exception as exc:
        raise ErrorSeguridad(
            "La configuración de seguridad está dañada."
        ) from exc


def derivar_clave_contrasena(
    contrasena: str,
    sal: bytes,
) -> bytes:

    if not contrasena:
        raise ErrorSeguridad(
            "La contraseña no puede estar vacía."
        )

    return Scrypt(
        salt=sal,
        length=32,
        n=2**15,
        r=8,
        p=1,
    ).derive(contrasena.encode("utf-8"))


def envolver_clave(
    clave_a_envolver: bytes,
    contrasena: str,
):
    salt = os.urandom(16)
    clave = derivar_clave_contrasena(
        contrasena,
        salt,
    )

    nonce = os.urandom(12)

    ciphertext = AESGCM(clave).encrypt(
        nonce,
        clave_a_envolver,
        b"DocuCentral-key-wrap-v1",
    )

    return salt, nonce, ciphertext


def desenvolver_clave(
    envoltura: bytes,
    contrasena: str,
    sal: bytes,
    nonce: bytes,
) -> bytes:

    clave = derivar_clave_contrasena(
        contrasena,
        sal,
    )

    try:
        return AESGCM(clave).decrypt(
            nonce,
            envoltura,
            b"DocuCentral-key-wrap-v1",
        )
    except InvalidTag as exc:
        raise ErrorSeguridad(
            "Contraseña incorrecta."
        ) from exc


def cifrar_bytes(
    data: bytes,
    clave_maestra: bytes,
    aad: bytes = b"",
) -> bytes:

    if not clave_maestra:
        raise ErrorSeguridad(
            "No hay una clave maestra disponible."
        )

    nonce = os.urandom(12)

    ciphertext = AESGCM(clave_maestra).encrypt(
        nonce,
        data,
        aad,
    )

    return b"DC01" + nonce + ciphertext


def descifrar_bytes(
    blob: bytes,
    clave_maestra: bytes,
    aad: bytes = b"",
) -> bytes:

    if not clave_maestra:
        raise ErrorSeguridad(
            "No hay una clave maestra disponible."
        )

    if not isinstance(blob, bytes):
        raise ErrorSeguridad(
            "El contenido protegido no es válido."
        )

    if not blob.startswith(b"DC01"):
        raise ErrorSeguridad(
            "El archivo protegido no tiene un formato "
            "DocuCentral válido."
        )

    if len(blob) < 4 + 12 + 16:
        raise ErrorSeguridad(
            "El archivo protegido está incompleto o dañado."
        )

    nonce = blob[4:16]
    ciphertext = blob[16:]

    try:
        return AESGCM(clave_maestra).decrypt(
            nonce,
            ciphertext,
            aad,
        )
    except InvalidTag as exc:
        raise ErrorSeguridad(
            "No se pudo descifrar el documento. "
            "La contraseña puede ser incorrecta "
            "o el archivo fue alterado."
        ) from exc


class GestorSeguridad:
    """
    Gestiona la clave maestra y los archivos sensibles
    de DocuCentral.
    """

    FORMATO_ARCHIVO = b"DC01"
    AAD_PDF = b"DocuCentral-PDF-v1"

    def __init__(
        self,
        directorio_datos: Path,
    ):
        self.directorio_datos = Path(
            directorio_datos
        )

        self.directorio_protegido = (
            self.directorio_datos / "protegidos"
        )

        self.ruta_configuracion = (
            self.directorio_datos / "seguridad.json"
        )

        self.directorio_protegido.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.config = self._cargar()
        self.clave_maestra = None

    def _cargar(self):
        if not self.ruta_configuracion.exists():
            return {}

        try:
            return json.loads(
                self.ruta_configuracion.read_text(
                    encoding="utf-8"
                )
            )
        except Exception as exc:
            raise ErrorSeguridad(
                f"No se pudo leer la configuración de seguridad: {exc}"
            ) from exc

    def _guardar(self):
        """
        Guarda la configuración de manera atómica.
        """

        temp = self.ruta_configuracion.with_suffix(
            ".tmp"
        )

        try:
            contenido = json.dumps(
                self.config,
                indent=2,
                ensure_ascii=False,
            )

            with open(
                temp,
                "w",
                encoding="utf-8",
            ) as archivo:

                archivo.write(contenido)
                archivo.flush()
                os.fsync(archivo.fileno())

            os.replace(
                temp,
                self.ruta_configuracion,
            )

        except Exception as exc:

            try:
                if temp.exists():
                    temp.unlink()
            except Exception:
                pass

            raise ErrorSeguridad(
                f"No se pudo guardar la configuración de seguridad: {exc}"
            ) from exc

    @property
    def configurado(self):
        return bool(
            self.config.get("configurado")
        )

    @property
    def correo(self):
        return self.config.get(
            "correo",
            "",
        )

    @property
    def id_instalacion(self):
        return self.config.get(
            "id_instalacion",
            "",
        )

    def inicializar(
        self,
        contrasena: str,
        correo: str,
    ):

        if self.configurado:
            raise ErrorSeguridad(
                "DocuCentral ya tiene una configuración de seguridad."
            )

        if len(contrasena) < 8:
            raise ErrorSeguridad(
                "La contraseña debe tener al menos 8 caracteres."
            )

        correo = correo.strip().lower()

        if "@" not in correo:
            raise ErrorSeguridad(
                "Ingresá un email válido."
            )

        clave_maestra = AESGCM.generate_key(
            bit_length=256
        )

        (
            sal_contrasena,
            nonce_contrasena,
            envoltura_contrasena,
        ) = envolver_clave(
            clave_maestra,
            contrasena,
        )

        codigo_recuperacion = (
            self.generar_codigo_recuperacion()
        )

        (
            sal_recuperacion,
            nonce_recuperacion,
            envoltura_recuperacion,
        ) = envolver_clave(
            clave_maestra,
            codigo_recuperacion,
        )

        # Copia local de emergencia protegida
        # por Windows DPAPI.
        clave_maestra_windows = (
            proteger_con_dpapi(
                clave_maestra
            )
        )

        self.config = {
            "version": 1,
            "configurado": True,
            "id_instalacion": secrets.token_hex(16),
            "correo": correo,
            "correo_verificado": False,

            "sal_contrasena": _b64(
                sal_contrasena
            ),

            "nonce_contrasena": _b64(
                nonce_contrasena
            ),

            "envoltura_contrasena": _b64(
                envoltura_contrasena
            ),

            "sal_recuperacion": _b64(
                sal_recuperacion
            ),

            "nonce_recuperacion": _b64(
                nonce_recuperacion
            ),

            "envoltura_recuperacion": _b64(
                envoltura_recuperacion
            ),

            "clave_maestra_windows": _b64(
                clave_maestra_windows
            ),
        }

        self._guardar()

        self.clave_maestra = clave_maestra

        return codigo_recuperacion

    @staticmethod
    def generar_codigo_recuperacion():

        alphabet = (
            "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        )

        raw = "".join(
            secrets.choice(alphabet)
            for _ in range(20)
        )

        return "-".join(
            raw[i:i + 5]
            for i in range(0, 20, 5)
        )

    def marcar_email_verificado(self):

        self.config[
            "correo_verificado"
        ] = True

        self._guardar()

    @property
    def email_verificado(self):

        return bool(
            self.config.get(
                "correo_verificado"
            )
        )

    def desbloquear_con_recuperacion_windows(
        self,
    ) -> bytes:

        if not self.configurado:
            raise ErrorSeguridad(
                "La seguridad todavía no fue configurada."
            )

        try:

            clave_maestra = recuperar_con_dpapi(
                _unb64(
                    self.config[
                        "clave_maestra_windows"
                    ]
                )
            )

        except Exception as exc:

            if isinstance(
                exc,
                ErrorSeguridad,
            ):
                raise

            raise ErrorSeguridad(
                "No se pudo recuperar la clave maestra de Windows."
            ) from exc

        self.clave_maestra = clave_maestra

        return clave_maestra

    def desbloquear(
        self,
        contrasena: str,
    ) -> bytes:

        if not self.configurado:
            raise ErrorSeguridad(
                "La seguridad todavía no fue configurada."
            )

        clave_maestra = desenvolver_clave(
            _unb64(
                self.config[
                    "envoltura_contrasena"
                ]
            ),
            contrasena,
            _unb64(
                self.config[
                    "sal_contrasena"
                ]
            ),
            _unb64(
                self.config[
                    "nonce_contrasena"
                ]
            ),
        )

        self.clave_maestra = clave_maestra

        return clave_maestra

    def tiene_contrasena_cuenta(self, correo: str) -> bool:
        correo = (correo or "").strip().lower()
        envolturas = self.config.get("envolturas_cuenta", {})
        return isinstance(envolturas, dict) and correo in envolturas

    def vincular_contrasena_cuenta(self, correo: str, contrasena: str) -> None:
        """Asocia la contraseña de una cuenta a la misma clave maestra local.

        No guarda la contraseña en claro: solo almacena una envoltura AES-GCM
        protegida por una clave derivada mediante Scrypt.
        """
        correo = (correo or "").strip().lower()
        if not correo or "@" not in correo:
            raise ErrorSeguridad("El correo de la cuenta no es válido.")
        if len(contrasena or "") < 8:
            raise ErrorSeguridad("La contraseña de la cuenta debe tener al menos 8 caracteres.")
        if not self.clave_maestra:
            raise ErrorSeguridad(
                "Primero debe autorizarse el acceso a la seguridad local para vincular esta cuenta."
            )

        sal, nonce, envoltura = envolver_clave(self.clave_maestra, contrasena)
        envolturas = self.config.setdefault("envolturas_cuenta", {})
        if not isinstance(envolturas, dict):
            envolturas = {}
            self.config["envolturas_cuenta"] = envolturas
        envolturas[correo] = {
            "sal": _b64(sal),
            "nonce": _b64(nonce),
            "envoltura": _b64(envoltura),
        }
        self._guardar()

    def desbloquear_con_cuenta(self, correo: str, contrasena: str) -> bytes:
        """Valida la contraseña de una cuenta local y desbloquea la clave compartida."""
        correo = (correo or "").strip().lower()
        envolturas = self.config.get("envolturas_cuenta", {})
        registro = envolturas.get(correo) if isinstance(envolturas, dict) else None
        if isinstance(registro, dict):
            try:
                clave = desenvolver_clave(
                    _unb64(registro["envoltura"]),
                    contrasena,
                    _unb64(registro["sal"]),
                    _unb64(registro["nonce"]),
                )
            except (KeyError, ErrorSeguridad) as exc:
                raise ErrorSeguridad("La contraseña de la cuenta es incorrecta o su vínculo local está dañado.") from exc
            self.clave_maestra = clave
            return clave

        # Compatibilidad con instalaciones anteriores, donde la clave maestra
        # estaba envuelta directamente por una sola contraseña.
        if correo == (self.config.get("correo", "") or "").strip().lower():
            return self.desbloquear(contrasena)

        raise ErrorSeguridad(
            "Esta cuenta todavía no está vinculada a la seguridad local. "
            "Para vincularla, una persona autorizada debe ingresar la contraseña de seguridad anterior."
        )

    def desbloquear_con_codigo_recuperacion(
        self,
        codigo_recuperacion: str,
    ) -> bytes:

        if not self.configurado:
            raise ErrorSeguridad(
                "La seguridad todavía no fue configurada."
            )

        clave_maestra = desenvolver_clave(
            _unb64(
                self.config[
                    "envoltura_recuperacion"
                ]
            ),
            codigo_recuperacion.strip().upper(),
            _unb64(
                self.config[
                    "sal_recuperacion"
                ]
            ),
            _unb64(
                self.config[
                    "nonce_recuperacion"
                ]
            ),
        )

        self.clave_maestra = clave_maestra

        return clave_maestra

    def restablecer_contrasena(
        self,
        nueva_contrasena: str,
        clave_maestra: bytes,
    ):

        if len(nueva_contrasena) < 8:
            raise ErrorSeguridad(
                "La nueva contraseña debe tener al menos 8 caracteres."
            )

        if not clave_maestra:
            raise ErrorSeguridad(
                "No hay una clave maestra disponible."
            )

        (
            sal,
            nonce,
            envoltura,
        ) = envolver_clave(
            clave_maestra,
            nueva_contrasena,
        )

        self.config[
            "sal_contrasena"
        ] = _b64(sal)

        self.config[
            "nonce_contrasena"
        ] = _b64(nonce)

        self.config[
            "envoltura_contrasena"
        ] = _b64(envoltura)

        self._guardar()

        self.clave_maestra = clave_maestra

    def verificar_codigo_emergencia(
        self,
        codigo_recuperacion: str,
    ) -> bool:

        try:

            self.desbloquear_con_codigo_recuperacion(
                codigo_recuperacion
            )

            return True

        except ErrorSeguridad:
            return False

    def proteger_archivo(
        self,
        ruta_origen: Path,
        clave_maestra: bytes,
    ):
        """
        Cifra un archivo PDF de forma segura.

        Importante:
        - No elimina el original.
        - Escribe primero un archivo temporal.
        - Fuerza la escritura en disco.
        - Verifica que el archivo cifrado pueda
          descifrarse correctamente.
        - Recién entonces mueve el archivo al
          destino definitivo.
        """

        ruta_origen = Path(ruta_origen)

        if not ruta_origen.exists():
            raise ErrorSeguridad(
                "El PDF original no existe."
            )

        if not ruta_origen.is_file():
            raise ErrorSeguridad(
                "La ruta indicada no corresponde a un archivo."
            )

        if not clave_maestra:
            raise ErrorSeguridad(
                "No hay una clave maestra disponible."
            )

        try:

            data = ruta_origen.read_bytes()

        except Exception as exc:

            raise ErrorSeguridad(
                f"No se pudo leer el PDF original: {exc}"
            ) from exc

        if not data:
            raise ErrorSeguridad(
                "El PDF está vacío."
            )

        encrypted = cifrar_bytes(
            data,
            clave_maestra,
            self.AAD_PDF,
        )

        nombre_protegido = (
            secrets.token_hex(20)
            + ".dcp"
        )

        ruta_protegida = (
            self.directorio_protegido
            / nombre_protegido
        )

        ruta_temp = (
            self.directorio_protegido
            / (
                nombre_protegido
                + ".tmp"
            )
        )

        try:

            # Escritura temporal.
            with open(
                ruta_temp,
                "wb",
            ) as archivo:

                archivo.write(encrypted)
                archivo.flush()
                os.fsync(
                    archivo.fileno()
                )

            # Verificación criptográfica ANTES
            # de considerar válido el archivo.
            contenido_verificado = (
                ruta_temp.read_bytes()
            )

            recuperado = descifrar_bytes(
                contenido_verificado,
                clave_maestra,
                self.AAD_PDF,
            )

            if recuperado != data:
                raise ErrorSeguridad(
                    "La verificación de seguridad falló: "
                    "el archivo recuperado no coincide "
                    "con el PDF original."
                )

            # Solo ahora se convierte en definitivo.
            os.replace(
                ruta_temp,
                ruta_protegida,
            )

            # Verificación final después del replace.
            contenido_final = (
                ruta_protegida.read_bytes()
            )

            recuperado_final = (
                descifrar_bytes(
                    contenido_final,
                    clave_maestra,
                    self.AAD_PDF,
                )
            )

            if recuperado_final != data:

                try:
                    ruta_protegida.unlink()
                except Exception:
                    pass

                raise ErrorSeguridad(
                    "La verificación final del archivo protegido falló."
                )

            return ruta_protegida

        except ErrorSeguridad:

            try:
                if ruta_temp.exists():
                    ruta_temp.unlink()
            except Exception:
                pass

            raise

        except Exception as exc:

            try:
                if ruta_temp.exists():
                    ruta_temp.unlink()
            except Exception:
                pass

            # Si se creó un archivo definitivo pero
            # ocurrió un error inesperado durante la
            # validación, intentamos eliminarlo.
            try:
                if ruta_protegida.exists():
                    ruta_protegida.unlink()
            except Exception:
                pass

            raise ErrorSeguridad(
                f"No se pudo proteger el PDF: {exc}"
            ) from exc

    def descifrar_archivo_a_bytes(
        self,
        ruta_protegida: Path,
        clave_maestra: bytes,
    ) -> bytes:

        ruta_protegida = Path(
            ruta_protegida
        )

        if not ruta_protegida.exists():
            raise ErrorSeguridad(
                "No se encontró el archivo protegido."
            )

        if not ruta_protegida.is_file():
            raise ErrorSeguridad(
                "La ruta protegida no corresponde a un archivo."
            )

        try:

            contenido = (
                ruta_protegida.read_bytes()
            )

        except Exception as exc:

            raise ErrorSeguridad(
                f"No se pudo leer el archivo protegido: {exc}"
            ) from exc

        return descifrar_bytes(
            contenido,
            clave_maestra,
            self.AAD_PDF,
        )

    def eliminar_archivo_protegido(
        self,
        ruta_protegida: Path,
    ):

        ruta_protegida = Path(
            ruta_protegida
        )

        if ruta_protegida.exists():

            try:
                ruta_protegida.unlink()

            except Exception as exc:

                raise ErrorSeguridad(
                    f"No se pudo eliminar el archivo protegido: {exc}"
                ) from exc

    def limpiar_archivos_temporales(
        self,
    ):
        """
        Elimina archivos .tmp que hayan quedado
        dentro de la carpeta de archivos protegidos
        por un cierre inesperado del programa.
        """

        if not self.directorio_protegido.exists():
            return

        errores = []

        for archivo in self.directorio_protegido.glob(
            "*.tmp"
        ):

            try:

                if archivo.is_file():
                    archivo.unlink()

            except Exception as exc:
                errores.append(
                    f"{archivo.name}: {exc}"
                )

        if errores:
            raise ErrorSeguridad(
                "No se pudieron limpiar algunos "
                "archivos temporales de seguridad:\n"
                + "\n".join(errores)
            )
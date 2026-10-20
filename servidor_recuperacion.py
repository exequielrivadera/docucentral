import hashlib
import hmac
import os
import re
import secrets
import smtplib
import sqlite3  # Se conserva para compatibilidad con el manejo de errores existente.
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path

from dotenv import load_dotenv
import psycopg
from psycopg.rows import dict_row
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
HOST_SMTP = os.getenv("BREVO_SMTP_HOST", "smtp-relay.brevo.com")
PUERTO_SMTP = int(os.getenv("BREVO_SMTP_PORT", "587"))
USUARIO_SMTP = os.getenv("BREVO_SMTP_USER", "")
CLAVE_SMTP = os.getenv("BREVO_SMTP_KEY", "")
CORREO_REMITENTE = os.getenv("BREVO_SENDER_EMAIL", "docucentrallr@gmail.com")
NOMBRE_REMITENTE = os.getenv("BREVO_SENDER_NAME", "DocuCentral")
MINUTOS_TOKEN = 10

app = FastAPI(title="Servicio de Cuentas y Recuperación de DocuCentral", version="3.0-postgresql")


class FilaHibrida(dict):
    """Fila compatible con acceso por nombre (fila['correo']) y por índice (fila[0])."""
    def __getitem__(self, key):
        if isinstance(key, int):
            try:
                key = list(self.keys())[key]
            except IndexError:
                raise IndexError(key)
        return super().__getitem__(key)


class CursorCompatible:
    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        return FilaHibrida(row) if row is not None else None

    def fetchall(self):
        return [FilaHibrida(row) for row in self._cursor.fetchall()]

    @property
    def rowcount(self):
        return self._cursor.rowcount


class ConexionCompatible:
    """Adapta el uso de conn.execute y los placeholders SQLite al driver PostgreSQL."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        sql = sql.replace("BEGIN IMMEDIATE", "BEGIN")
        sql = sql.replace("?", "%s")
        try:
            cur = self._conn.execute(sql, params)
            return CursorCompatible(cur)
        except psycopg.Error as exc:
            raise sqlite3.OperationalError(str(exc)) from exc

    def commit(self):
        try:
            self._conn.commit()
        except psycopg.Error as exc:
            raise sqlite3.OperationalError(str(exc)) from exc

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def _crear_esquema(conn):
    """Crea las tablas de forma idempotente en PostgreSQL."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cuentas (
            correo TEXT PRIMARY KEY,
            hash_contrasena TEXT NOT NULL,
            verificado INTEGER NOT NULL DEFAULT 0,
            creado_en TEXT NOT NULL,
            actualizado_en TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS instalaciones (
            id_instalacion TEXT PRIMARY KEY,
            correo TEXT NOT NULL,
            verificado INTEGER NOT NULL DEFAULT 0,
            actualizado_en TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            id BIGSERIAL PRIMARY KEY,
            id_instalacion TEXT NOT NULL,
            proposito TEXT NOT NULL,
            hash_token TEXT NOT NULL,
            expira_en TEXT NOT NULL,
            usado INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS eventos_seguridad (
            id BIGSERIAL PRIMARY KEY,
            correo TEXT NOT NULL,
            id_instalacion TEXT NOT NULL,
            accion TEXT NOT NULL,
            resultado TEXT NOT NULL,
            detalle TEXT NOT NULL DEFAULT '',
            creado_en TEXT NOT NULL
        )
    """)
    conn.commit()


def db():
    """Abre PostgreSQL y prepara el esquema con manejo seguro de errores."""
    if not DATABASE_URL:
        raise RuntimeError(
            "Falta la variable DATABASE_URL de PostgreSQL en el servidor."
        )

    # Manejar por separado los errores al establecer la conexión.
    try:
        raw = psycopg.connect(
            DATABASE_URL,
            connect_timeout=10,
            row_factory=dict_row,
        )
    except psycopg.Error as exc:
        raise RuntimeError(
            "No se pudo conectar a PostgreSQL. "
            "Revisá DATABASE_URL y el acceso de red."
        ) from exc

    conn = ConexionCompatible(raw)

    # Los errores del adaptador pueden convertirse en sqlite3.OperationalError
    # para mantener la compatibilidad con los bloques existentes del servidor.
    try:
        _crear_esquema(conn)
        return conn
    except (psycopg.Error, sqlite3.Error) as exc:
        try:
            conn.rollback()
        except Exception:
            pass

        try:
            conn.close()
        except Exception:
            pass

        raise RuntimeError(
            "No se pudo preparar el esquema de PostgreSQL."
        ) from exc


def normalizar_correo(correo: str) -> str:
    return correo.strip().lower()


def validar_correo(correo: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", correo))


def hashear_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generar_token() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def hashear_contrasena(contrasena: str) -> str:
    sal = os.urandom(16)
    derivado = hashlib.scrypt(contrasena.encode("utf-8"), salt=sal, n=2**14, r=8, p=1, dklen=32)
    return "scrypt$16384$" + sal.hex() + "$" + derivado.hex()


def verificar_contrasena(contrasena: str, almacenada: str) -> bool:
    try:
        algoritmo, n_texto, sal_hex, hash_hex = almacenada.split("$", 3)
        if algoritmo != "scrypt" or int(n_texto) != 16384:
            return False
        calculado = hashlib.scrypt(
            contrasena.encode("utf-8"), salt=bytes.fromhex(sal_hex),
            n=16384, r=8, p=1, dklen=len(bytes.fromhex(hash_hex))
        )
        return hmac.compare_digest(calculado.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def enviar_token(token: str, proposito: str, correo_destino: str):
    if not USUARIO_SMTP or not CLAVE_SMTP or not CORREO_REMITENTE:
        raise RuntimeError("Faltan las variables de Brevo SMTP en el servidor.")
    msg = EmailMessage()
    if proposito == "verificación":
        msg["Subject"] = "Verificá tu correo de DocuCentral"
    elif proposito == "eliminación de cuenta":
        msg["Subject"] = "Código de seguridad para eliminar tu cuenta de DocuCentral"
    elif proposito == "recuperación":
        msg["Subject"] = "Código para recuperar tu cuenta de DocuCentral"
    else:
        msg["Subject"] = f"Código de seguridad de DocuCentral: {proposito}"
    msg["From"] = f"{NOMBRE_REMITENTE} <{CORREO_REMITENTE}>"
    msg["To"] = correo_destino
    msg.set_content(
        f"Código de {proposito} de DocuCentral: {token}\n\n"
        f"Este código vence en {MINUTOS_TOKEN} minutos.\n"
        "Si no solicitaste esta operación, ignorá este mensaje."
    )
    with smtplib.SMTP(HOST_SMTP, PUERTO_SMTP, timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(USUARIO_SMTP, CLAVE_SMTP)
        smtp.send_message(msg)


class SolicitudInstalacion(BaseModel):
    id_instalacion: str = Field(min_length=16, max_length=128)
    correo: str = Field(min_length=3, max_length=254)
    contrasena_cuenta: str = Field(min_length=8, max_length=256)
    # "auto" se conserva para compatibilidad con instalaciones anteriores.
    modo: str = "auto"


class SolicitudToken(BaseModel):
    id_instalacion: str
    proposito: str = "recuperación"


class SolicitudValidarCuenta(BaseModel):
    correo: str = Field(min_length=3, max_length=254)
    contrasena_cuenta: str = Field(min_length=8, max_length=256)


class SolicitudVerificacion(BaseModel):
    id_instalacion: str
    token: str
    proposito: str = "recuperación"


class SolicitudRestablecerContrasena(BaseModel):
    id_instalacion: str = Field(min_length=16, max_length=128)
    token: str = Field(min_length=6, max_length=12)
    nueva_contrasena: str = Field(min_length=8, max_length=256)


class SolicitudEliminarCuenta(BaseModel):
    id_instalacion: str = Field(min_length=16, max_length=128)
    correo: str = Field(min_length=3, max_length=254)
    contrasena_cuenta: str = Field(min_length=8, max_length=256)


class SolicitudConfirmarEliminarCuenta(BaseModel):
    id_instalacion: str = Field(min_length=16, max_length=128)
    correo: str = Field(min_length=3, max_length=254)
    contrasena_cuenta: str = Field(min_length=8, max_length=256)
    token: str = Field(min_length=6, max_length=12)


def registrar_evento(correo: str, id_instalacion: str, accion: str, resultado: str, detalle: str = ""):
    conn = db()
    try:
        conn.execute(
            "INSERT INTO eventos_seguridad(correo, id_instalacion, accion, resultado, detalle, creado_en) VALUES(?,?,?,?,?,?)",
            (normalizar_correo(correo), id_instalacion.strip(), accion, resultado, detalle[:500], datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


@app.get("/")
def estado():
    return {"servicio": "DocuCentral Cuentas y Recuperación", "estado": "ok"}


def crear_y_enviar_token(id_instalacion: str, proposito: str, correo_destino: str):
    token = generar_token()
    hash_token = hashear_token(token)
    expires = (datetime.now(timezone.utc) + timedelta(minutes=MINUTOS_TOKEN)).isoformat()
    conn = db()
    try:
        conn.execute(
            "UPDATE tokens SET usado=1 WHERE id_instalacion=? AND proposito=? AND usado=0",
            (id_instalacion, proposito),
        )
        conn.execute(
            "INSERT INTO tokens(id_instalacion, proposito, hash_token, expira_en, usado) VALUES(?,?,?,?,0)",
            (id_instalacion, proposito, hash_token, expires),
        )
        conn.commit()
    finally:
        conn.close()
    try:
        enviar_token(token, proposito, correo_destino)
    except Exception as exc:
        conn = db()
        try:
            conn.execute(
                "UPDATE tokens SET usado=1 WHERE id_instalacion=? AND proposito=? AND hash_token=?",
                (id_instalacion, proposito, hash_token),
            )
            conn.commit()
        finally:
            conn.close()
        raise HTTPException(status_code=500, detail=f"No se pudo enviar el correo. Revisá la configuración SMTP del servidor. ({exc})") from exc
    return {"ok": True, "message": "Código enviado al correo de la cuenta registrada."}


@app.post("/validar-cuenta")
def validar_cuenta_activa(payload: SolicitudValidarCuenta):
    """Valida que una cuenta autorizante siga activa y verificada en el servidor."""
    correo = normalizar_correo(payload.correo)
    conn = db()
    try:
        row = conn.execute("SELECT hash_contrasena, verificado FROM cuentas WHERE correo=?", (correo,)).fetchone()
    finally:
        conn.close()
    if not row or not row["verificado"] or not verificar_contrasena(payload.contrasena_cuenta, row["hash_contrasena"]):
        registrar_evento(correo, "sin_instalacion", "validacion_cuenta_autorizante", "rechazada", "Cuenta no activa/verificada o contraseña incorrecta")
        raise HTTPException(status_code=401, detail="La cuenta autorizante no está activa, no está verificada o la contraseña es incorrecta.")
    return {"ok": True, "validada": True}


@app.post("/registrar")
def registrar(payload: SolicitudInstalacion):
    correo = normalizar_correo(payload.correo)
    modo = (payload.modo or "auto").strip().lower()
    if modo not in {"auto", "ingresar", "crear"}:
        raise HTTPException(status_code=422, detail="El modo de acceso no es válido.")
    if not validar_correo(correo):
        raise HTTPException(status_code=422, detail="Ingresá un correo electrónico válido.")
    if len(payload.contrasena_cuenta) < 8:
        raise HTTPException(status_code=422, detail="La contraseña de la cuenta debe tener al menos 8 caracteres.")
    id_instalacion = payload.id_instalacion.strip()
    ahora = datetime.now(timezone.utc).isoformat()
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        instalacion_existente = conn.execute(
            "SELECT correo FROM instalaciones WHERE id_instalacion=?", (id_instalacion,)
        ).fetchone()
        if instalacion_existente and normalizar_correo(instalacion_existente["correo"]) != correo:
            conn.rollback()
            raise HTTPException(status_code=409, detail="Este identificador de instalación ya está asociado a otro correo.")

        cuenta = conn.execute("SELECT hash_contrasena, verificado FROM cuentas WHERE correo=?", (correo,)).fetchone()
        if modo == "ingresar" and cuenta is None:
            conn.rollback()
            eliminado_previo = conn.execute(
                "SELECT 1 FROM eventos_seguridad WHERE correo=? AND accion='eliminacion_cuenta' AND resultado='completada' LIMIT 1",
                (correo,),
            ).fetchone()
            if eliminado_previo:
                raise HTTPException(status_code=404, detail="Esta cuenta fue eliminada. Para volver a utilizar este correo, elegí explícitamente ‘Crear una cuenta nueva’.")
            raise HTTPException(status_code=404, detail="No existe una cuenta con ese correo. Elegí ‘Crear una cuenta nueva’.")

        if modo == "crear" and cuenta is not None:
            conn.rollback()
            raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese correo. Elegí ‘Ingresar a una cuenta existente’.")

        if cuenta is None:
            if modo == "auto":
                eliminada = conn.execute(
                    "SELECT 1 FROM eventos_seguridad WHERE correo=? AND accion='eliminacion_cuenta' AND resultado='completada' LIMIT 1",
                    (correo,),
                ).fetchone()
                if eliminada:
                    conn.rollback()
                    raise HTTPException(status_code=409, detail="Esta cuenta fue eliminada. Para registrar nuevamente el correo, elegí explícitamente crear una cuenta nueva.")
            hash_password = hashear_contrasena(payload.contrasena_cuenta)
            conn.execute(
                "INSERT INTO cuentas(correo, hash_contrasena, verificado, creado_en, actualizado_en) VALUES(?,?,0,?,?)",
                (correo, hash_password, ahora, ahora),
            )
            requiere_verificacion = True
            conn.execute(
                "INSERT INTO eventos_seguridad(correo,id_instalacion,accion,resultado,detalle,creado_en) VALUES(?,?,?,?,?,?)",
                (correo,id_instalacion,"creacion_cuenta","iniciada","Cuenta creada y pendiente de verificación",ahora),
            )
        else:
            if not verificar_contrasena(payload.contrasena_cuenta, cuenta["hash_contrasena"]):
                conn.rollback()
                raise HTTPException(status_code=401, detail="La contraseña de la cuenta es incorrecta.")
            requiere_verificacion = not bool(cuenta["verificado"])
            conn.execute("UPDATE cuentas SET actualizado_en=? WHERE correo=?", (ahora, correo))

        verificado_instalacion = 0 if requiere_verificacion else 1
        conn.execute(
            "INSERT INTO instalaciones(id_instalacion, correo, verificado, actualizado_en) VALUES(?,?,?,?) "
            "ON CONFLICT(id_instalacion) DO UPDATE SET correo=excluded.correo, verificado=excluded.verificado, actualizado_en=excluded.actualizado_en",
            (id_instalacion, correo, verificado_instalacion, ahora),
        )
        conn.commit()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="No se pudo guardar el registro de la cuenta.") from exc
    finally:
        conn.close()

    if requiere_verificacion:
        crear_y_enviar_token(id_instalacion, "verificación", correo)
        return {"ok": True, "requiere_verificacion": True, "message": "Código de verificación enviado al correo registrado."}
    return {"ok": True, "requiere_verificacion": False, "verificado": True, "message": "Cuenta verificada e instalación asociada."}


@app.post("/solicitar-recuperacion")
def solicitar_recuperacion(payload: SolicitudToken):
    conn = db()
    try:
        row = conn.execute(
            "SELECT i.verificado, i.correo, c.verificado AS cuenta_verificada "
            "FROM instalaciones i LEFT JOIN cuentas c ON c.correo=i.correo WHERE i.id_instalacion=?",
            (payload.id_instalacion,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Instalación no reconocida.")
    if not row["verificado"] or not row["cuenta_verificada"]:
        raise HTTPException(status_code=403, detail="El correo de la cuenta todavía no fue verificado.")
    return crear_y_enviar_token(payload.id_instalacion, "recuperación", row["correo"])


@app.post("/restablecer-contrasena")
def restablecer_contrasena(payload: SolicitudRestablecerContrasena):
    """Restablece la contraseña de cuenta usando un token de recuperación por correo."""
    token_limpio = payload.token.strip()
    if not token_limpio:
        raise HTTPException(status_code=400, detail="Ingresá el código recibido por correo.")
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT t.id, t.expira_en, i.correo, i.verificado, c.verificado AS cuenta_verificada "
            "FROM tokens t JOIN instalaciones i ON i.id_instalacion=t.id_instalacion "
            "JOIN cuentas c ON c.correo=i.correo "
            "WHERE t.id_instalacion=? AND t.proposito='recuperación' AND t.hash_token=? AND t.usado=0 "
            "ORDER BY t.id DESC LIMIT 1",
            (payload.id_instalacion, hashear_token(token_limpio)),
        ).fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(status_code=400, detail="Código incorrecto, vencido o ya utilizado.")
        try:
            expira = datetime.fromisoformat(row["expira_en"])
        except ValueError as exc:
            conn.rollback()
            raise HTTPException(status_code=500, detail="La fecha de expiración del código no es válida.") from exc
        if datetime.now(timezone.utc) > expira:
            conn.execute("UPDATE tokens SET usado=1 WHERE id=?", (row["id"],))
            conn.commit()
            raise HTTPException(status_code=400, detail="El código expiró. Solicitá uno nuevo.")
        if not row["verificado"] or not row["cuenta_verificada"]:
            conn.rollback()
            raise HTTPException(status_code=403, detail="La cuenta no está verificada.")
        correo = normalizar_correo(row["correo"])
        ahora = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE cuentas SET hash_contrasena=?, actualizado_en=? WHERE correo=?",
            (hashear_contrasena(payload.nueva_contrasena), ahora, correo),
        )
        conn.execute("UPDATE tokens SET usado=1 WHERE id=?", (row["id"],))
        conn.execute(
            "UPDATE tokens SET usado=1 WHERE id_instalacion=? AND proposito='recuperación' AND usado=0",
            (payload.id_instalacion,),
        )
        conn.commit()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="No se pudo restablecer la contraseña de la cuenta.") from exc
    finally:
        conn.close()
    return {"ok": True, "message": "La contraseña de la cuenta fue restablecida."}


@app.post("/solicitar-eliminacion-cuenta")
def solicitar_eliminacion_cuenta(payload: SolicitudEliminarCuenta):
    """Envía un token específico para borrar una cuenta; nunca la elimina en esta etapa."""
    correo = normalizar_correo(payload.correo)
    id_instalacion = payload.id_instalacion.strip()
    if not validar_correo(correo):
        raise HTTPException(status_code=422, detail="Ingresá un correo electrónico válido.")
    conn = db()
    try:
        row = conn.execute(
            "SELECT i.correo AS correo_instalacion, i.verificado AS instalacion_verificada, c.hash_contrasena, c.verificado AS cuenta_verificada "
            "FROM instalaciones i JOIN cuentas c ON c.correo=i.correo WHERE i.id_instalacion=?",
            (id_instalacion,),
        ).fetchone()
    finally:
        conn.close()
    if not row or normalizar_correo(row["correo_instalacion"]) != correo:
        registrar_evento(correo, id_instalacion, "solicitud_eliminacion_cuenta", "rechazada", "Instalación/correo no coinciden")
        raise HTTPException(status_code=404, detail="No se encontró una cuenta verificada asociada a esta instalación.")
    if not row["cuenta_verificada"] or not row["instalacion_verificada"]:
        registrar_evento(correo, id_instalacion, "solicitud_eliminacion_cuenta", "rechazada", "Cuenta o instalación sin verificar")
        raise HTTPException(status_code=403, detail="Primero debés verificar el correo de la cuenta.")
    if not verificar_contrasena(payload.contrasena_cuenta, row["hash_contrasena"]):
        registrar_evento(correo, id_instalacion, "solicitud_eliminacion_cuenta", "rechazada", "Contraseña incorrecta")
        raise HTTPException(status_code=401, detail="La contraseña de la cuenta es incorrecta.")
    try:
        resultado = crear_y_enviar_token(id_instalacion, "eliminación de cuenta", correo)
    except HTTPException:
        registrar_evento(correo, id_instalacion, "solicitud_eliminacion_cuenta", "fallo_envio", "No se pudo enviar el token")
        raise
    registrar_evento(correo, id_instalacion, "solicitud_eliminacion_cuenta", "token_enviado", "Se solicitó confirmación por correo")
    return {"ok": True, "token_enviado": True, "message": "Enviamos un código de eliminación al correo registrado. La cuenta todavía no fue eliminada."}


@app.post("/eliminar-cuenta")
def eliminar_cuenta(payload: SolicitudConfirmarEliminarCuenta):
    """Elimina una cuenta únicamente tras validar contraseña y token de eliminación."""
    correo = normalizar_correo(payload.correo)
    id_instalacion = payload.id_instalacion.strip()
    token_limpio = payload.token.strip()
    if not validar_correo(correo) or not token_limpio:
        raise HTTPException(status_code=422, detail="Faltan datos válidos para confirmar la eliminación.")

    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cuenta = conn.execute(
            "SELECT hash_contrasena, verificado FROM cuentas WHERE correo=?", (correo,)
        ).fetchone()
        instalacion = conn.execute(
            "SELECT correo, verificado FROM instalaciones WHERE id_instalacion=?", (id_instalacion,)
        ).fetchone()
        if not cuenta or not instalacion or normalizar_correo(instalacion["correo"]) != correo:
            conn.execute(
                "INSERT INTO eventos_seguridad(correo,id_instalacion,accion,resultado,detalle,creado_en) VALUES(?,?,?,?,?,?)",
                (correo,id_instalacion,"eliminacion_cuenta","rechazada","Cuenta o instalación no coinciden",datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            raise HTTPException(status_code=404, detail="No se encontró la cuenta vinculada a esta instalación.")
        if not cuenta["verificado"] or not verificar_contrasena(payload.contrasena_cuenta, cuenta["hash_contrasena"]):
            conn.execute(
                "INSERT INTO eventos_seguridad(correo,id_instalacion,accion,resultado,detalle,creado_en) VALUES(?,?,?,?,?,?)",
                (correo,id_instalacion,"eliminacion_cuenta","rechazada","Cuenta no verificada o contraseña incorrecta",datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            raise HTTPException(status_code=401, detail="No se pudo validar la cuenta. Revisá la contraseña y el estado de verificación.")
        fila_token = conn.execute(
            "SELECT id, expira_en FROM tokens WHERE id_instalacion=? AND proposito='eliminación de cuenta' AND hash_token=? AND usado=0 ORDER BY id DESC LIMIT 1",
            (id_instalacion, hashear_token(token_limpio)),
        ).fetchone()
        if not fila_token:
            conn.execute(
                "INSERT INTO eventos_seguridad(correo,id_instalacion,accion,resultado,detalle,creado_en) VALUES(?,?,?,?,?,?)",
                (correo,id_instalacion,"eliminacion_cuenta","rechazada","Token incorrecto, vencido o usado",datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            raise HTTPException(status_code=400, detail="El código de eliminación es incorrecto, venció o ya fue utilizado.")
        try:
            expira = datetime.fromisoformat(fila_token["expira_en"])
        except ValueError:
            conn.rollback()
            raise HTTPException(status_code=500, detail="La fecha de expiración del código no es válida.")
        if datetime.now(timezone.utc) > expira:
            conn.execute("UPDATE tokens SET usado=1 WHERE id=?", (fila_token["id"],))
            conn.execute(
                "INSERT INTO eventos_seguridad(correo,id_instalacion,accion,resultado,detalle,creado_en) VALUES(?,?,?,?,?,?)",
                (correo,id_instalacion,"eliminacion_cuenta","rechazada","Token vencido",datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            raise HTTPException(status_code=400, detail="El código venció. Solicitá uno nuevo.")

        ids = [r[0] for r in conn.execute("SELECT id_instalacion FROM instalaciones WHERE correo=?", (correo,)).fetchall()]
        for iid in ids:
            conn.execute("UPDATE tokens SET usado=1 WHERE id_instalacion=? AND usado=0", (iid,))
        conn.execute("UPDATE tokens SET usado=1 WHERE id=?", (fila_token["id"],))
        conn.execute("DELETE FROM instalaciones WHERE correo=?", (correo,))
        conn.execute("DELETE FROM cuentas WHERE correo=?", (correo,))
        conn.execute(
            "INSERT INTO eventos_seguridad(correo,id_instalacion,accion,resultado,detalle,creado_en) VALUES(?,?,?,?,?,?)",
            (correo,id_instalacion,"eliminacion_cuenta","completada","Cuenta eliminada tras validar contraseña y token por correo",datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="No se pudo completar la eliminación segura de la cuenta.") from exc
    finally:
        conn.close()
    return {"ok": True, "eliminada": True, "message": "La cuenta fue eliminada. El registro de seguridad se conservó."}


@app.post("/verificar")
def verificar_codigo(payload: SolicitudVerificacion):
    token_limpio = payload.token.strip()
    if not token_limpio:
        raise HTTPException(status_code=400, detail="Ingresá el código recibido por correo.")
    conn = db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT id, expira_en FROM tokens WHERE id_instalacion=? AND proposito=? AND hash_token=? AND usado=0 ORDER BY id DESC LIMIT 1",
            (payload.id_instalacion, payload.proposito, hashear_token(token_limpio)),
        ).fetchone()
        if not row:
            conn.rollback()
            raise HTTPException(status_code=400, detail="Código incorrecto o ya utilizado.")
        try:
            expira = datetime.fromisoformat(row["expira_en"])
        except ValueError as exc:
            conn.rollback()
            raise HTTPException(status_code=500, detail="La fecha de expiración del código no es válida.") from exc
        if datetime.now(timezone.utc) > expira:
            conn.execute("UPDATE tokens SET usado=1 WHERE id=?", (row["id"],))
            conn.commit()
            raise HTTPException(status_code=400, detail="El código expiró. Solicitá uno nuevo.")

        conn.execute("UPDATE tokens SET usado=1 WHERE id=?", (row["id"],))
        if payload.proposito == "verificación":
            inst = conn.execute("SELECT correo FROM instalaciones WHERE id_instalacion=?", (payload.id_instalacion,)).fetchone()
            if not inst:
                conn.rollback()
                raise HTTPException(status_code=404, detail="La instalación no está registrada.")
            correo = normalizar_correo(inst["correo"])
            conn.execute("UPDATE cuentas SET verificado=1, actualizado_en=? WHERE correo=?", (datetime.now(timezone.utc).isoformat(), correo))
            conn.execute("UPDATE instalaciones SET verificado=1, actualizado_en=? WHERE correo=?", (datetime.now(timezone.utc).isoformat(), correo))
        conn.commit()
    except HTTPException:
        raise
    except sqlite3.Error as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="No se pudo verificar el código.") from exc
    finally:
        conn.close()
    return {"ok": True, "verificado": payload.proposito == "verificación"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

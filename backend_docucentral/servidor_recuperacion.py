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
            id BIGSERIAL PRIMARY KEY, correo TEXT NOT NULL, id_instalacion TEXT NOT NULL,
            accion TEXT NOT NULL, resultado TEXT NOT NULL, detalle TEXT NOT NULL DEFAULT '', creado_en TEXT NOT NULL
        )
    """)
    # Esquema aditivo para organizaciones: no altera las cuentas existentes.
    conn.execute("""CREATE TABLE IF NOT EXISTS organizaciones (
        organizacion_id TEXT PRIMARY KEY, nombre TEXT NOT NULL, propietario_correo TEXT NOT NULL,
        max_instalaciones INTEGER NOT NULL DEFAULT 1, activa INTEGER NOT NULL DEFAULT 1, creada_en TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS oficinas (
        oficina_id TEXT PRIMARY KEY, organizacion_id TEXT NOT NULL REFERENCES organizaciones(organizacion_id),
        nombre TEXT NOT NULL, activa INTEGER NOT NULL DEFAULT 1, creada_en TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS miembros_organizacion (
        organizacion_id TEXT NOT NULL REFERENCES organizaciones(organizacion_id), correo TEXT NOT NULL,
        rol TEXT NOT NULL DEFAULT 'miembro', activa INTEGER NOT NULL DEFAULT 1, creada_en TEXT NOT NULL,
        PRIMARY KEY(organizacion_id, correo))""")
    conn.execute("""CREATE TABLE IF NOT EXISTS instalaciones_organizacion (
        id_instalacion TEXT PRIMARY KEY REFERENCES instalaciones(id_instalacion),
        organizacion_id TEXT NOT NULL REFERENCES organizaciones(organizacion_id), oficina_id TEXT REFERENCES oficinas(oficina_id),
        estado TEXT NOT NULL DEFAULT 'activa', vinculada_en TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS codigos_vinculacion (
        codigo_hash TEXT PRIMARY KEY, organizacion_id TEXT NOT NULL REFERENCES organizaciones(organizacion_id),
        oficina_id TEXT REFERENCES oficinas(oficina_id), creado_por TEXT NOT NULL, expira_en TEXT NOT NULL,
        usado INTEGER NOT NULL DEFAULT 0, creado_en TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS auditoria_organizacion (
        id BIGSERIAL PRIMARY KEY, organizacion_id TEXT NOT NULL, correo TEXT NOT NULL, id_instalacion TEXT NOT NULL,
        accion TEXT NOT NULL, detalle TEXT NOT NULL DEFAULT '', creado_en TEXT NOT NULL)""")
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
    correo: str = ""
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


class SolicitudOrganizacion(BaseModel):
    correo: str = Field(min_length=3, max_length=254)
    contrasena_cuenta: str = Field(min_length=8, max_length=256)
    id_instalacion: str = Field(min_length=16, max_length=128)
    nombre: str = Field(min_length=2, max_length=120)
    max_instalaciones: int = Field(default=5, ge=1, le=500)


class SolicitudVinculacion(BaseModel):
    correo: str = Field(min_length=3, max_length=254)
    contrasena_cuenta: str = Field(min_length=8, max_length=256)
    id_instalacion: str = Field(min_length=16, max_length=128)
    organizacion_id: str = Field(min_length=16, max_length=64)
    minutos_validez: int = Field(default=15, ge=5, le=60)


class SolicitudUsarCodigo(BaseModel):
    correo: str = Field(min_length=3, max_length=254)
    contrasena_cuenta: str = Field(min_length=8, max_length=256)
    id_instalacion: str = Field(min_length=16, max_length=128)
    codigo: str = Field(min_length=8, max_length=64)


class SolicitudOrgAdmin(BaseModel):
    correo: str = Field(min_length=3, max_length=254)
    contrasena_cuenta: str = Field(min_length=8, max_length=256)
    id_instalacion: str = Field(min_length=16, max_length=128)
    organizacion_id: str = Field(default="", max_length=64)


class SolicitudCrearOficina(SolicitudOrgAdmin):
    nombre: str = Field(min_length=2, max_length=120)


class SolicitudAsignarOficina(SolicitudOrgAdmin):
    instalacion_objetivo: str = Field(min_length=16, max_length=128)
    oficina_id: str = Field(min_length=16, max_length=64)


class SolicitudRevocarInstalacion(SolicitudOrgAdmin):
    instalacion_objetivo: str = Field(min_length=16, max_length=128)


class SolicitudCambiarCupo(SolicitudOrgAdmin):
    max_instalaciones: int = Field(ge=1, le=500)


class SolicitudMiembroOrg(SolicitudOrgAdmin):
    correo_miembro: str = Field(min_length=3, max_length=254)
    rol: str = Field(default="miembro", pattern="^(admin|miembro)$")


class SolicitudQuitarMiembro(SolicitudOrgAdmin):
    correo_miembro: str = Field(min_length=3, max_length=254)


def _autenticar_instalacion_org(correo, contrasena, id_instalacion, permitir_revocada=False):
    correo = normalizar_correo(correo)
    conn = db()
    try:
        cuenta = conn.execute(
            "SELECT hash_contrasena,verificado FROM cuentas WHERE correo=?", (correo,)
        ).fetchone()
        inst = conn.execute(
            "SELECT correo,verificado FROM instalaciones WHERE id_instalacion=?", (id_instalacion,)
        ).fetchone()
    finally:
        conn.close()

    if (
        not cuenta or not cuenta["verificado"]
        or not verificar_contrasena(contrasena, cuenta["hash_contrasena"])
        or not inst or not inst["verificado"]
        or normalizar_correo(inst["correo"]) != correo
    ):
        raise HTTPException(
            status_code=401,
            detail="Cuenta o instalación no verificada, o credenciales incorrectas."
        )

    # Una instalación revocada no puede seguir administrando ni vinculándose.
    conn = db()
    try:
        vinculacion = conn.execute(
            "SELECT estado FROM instalaciones_organizacion WHERE id_instalacion=?",
            (id_instalacion,),
        ).fetchone()
        if vinculacion and vinculacion["estado"] != "activa" and not permitir_revocada:
            raise HTTPException(status_code=403, detail="Esta instalación fue revocada por el administrador.")
    finally:
        conn.close()
    return correo


def _org_admin(conn, organizacion_id, correo):
    row = conn.execute(
        "SELECT organizacion_id,nombre,max_instalaciones,activa FROM organizaciones WHERE organizacion_id=?",
        (organizacion_id,),
    ).fetchone()
    member = conn.execute(
        "SELECT rol,activa FROM miembros_organizacion WHERE organizacion_id=? AND correo=?",
        (organizacion_id, correo),
    ).fetchone()
    if not row or not row["activa"] or not member or not member["activa"] or member["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Se requiere un administrador activo de esta organización.")
    return row


def _org_event(conn, org, correo, iid, accion, detalle=""):
    conn.execute(
        "INSERT INTO auditoria_organizacion(organizacion_id,correo,id_instalacion,accion,detalle,creado_en) VALUES(?,?,?,?,?,?)",
        (org, correo, iid, accion, detalle[:500], datetime.now(timezone.utc).isoformat()),
    )


def _org_lock(conn, organizacion_id):
    # Serializa las operaciones de cupo de una organización en PostgreSQL.
    return conn.execute(
        "SELECT organizacion_id,nombre,max_instalaciones,activa FROM organizaciones WHERE organizacion_id=? FOR UPDATE",
        (organizacion_id,),
    ).fetchone()


@app.post("/organizaciones/crear")
def crear_organizacion(payload: SolicitudOrganizacion):
    correo = _autenticar_instalacion_org(payload.correo, payload.contrasena_cuenta, payload.id_instalacion)
    ahora = datetime.now(timezone.utc).isoformat()
    oid = secrets.token_hex(16)
    nombre = payload.nombre.strip()
    conn = db()
    try:
        conn.execute("BEGIN")
        old = conn.execute(
            "SELECT organizacion_id,estado FROM instalaciones_organizacion WHERE id_instalacion=? FOR UPDATE",
            (payload.id_instalacion,),
        ).fetchone()
        if old:
            raise HTTPException(status_code=409, detail="Esta instalación ya tiene una vinculación de organización; no puede crear otra organización desde el mismo equipo.")
        conn.execute(
            "INSERT INTO organizaciones(organizacion_id,nombre,propietario_correo,max_instalaciones,activa,creada_en) VALUES(?,?,?,?,1,?)",
            (oid, nombre, correo, payload.max_instalaciones, ahora),
        )
        conn.execute(
            "INSERT INTO miembros_organizacion(organizacion_id,correo,rol,activa,creada_en) VALUES(?,?,'admin',1,?)",
            (oid, correo, ahora),
        )
        conn.execute(
            "INSERT INTO instalaciones_organizacion(id_instalacion,organizacion_id,estado,vinculada_en) VALUES(?,?,'activa',?)",
            (payload.id_instalacion, oid, ahora),
        )
        _org_event(conn, oid, correo, payload.id_instalacion, "organizacion_creada", nombre)
        conn.commit()
        return {"ok": True, "organizacion_id": oid, "nombre": nombre, "max_instalaciones": payload.max_instalaciones}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="No se pudo crear la organización.") from exc
    finally:
        conn.close()


@app.post("/organizaciones/codigo-vinculacion")
def crear_codigo_vinculacion(payload: SolicitudVinculacion):
    correo = _autenticar_instalacion_org(payload.correo, payload.contrasena_cuenta, payload.id_instalacion)
    codigo = secrets.token_urlsafe(24)
    codigo_hash = hashlib.sha256(codigo.encode()).hexdigest()
    ahora = datetime.now(timezone.utc)
    conn = db()
    try:
        conn.execute("BEGIN")
        org = _org_admin(conn, payload.organizacion_id, correo)
        org = _org_lock(conn, payload.organizacion_id)
        if not org or not org["activa"]:
            raise HTTPException(status_code=403, detail="La organización está inactiva.")
        admin = conn.execute(
            "SELECT 1 FROM instalaciones_organizacion WHERE id_instalacion=? AND organizacion_id=? AND estado='activa' FOR UPDATE",
            (payload.id_instalacion, payload.organizacion_id),
        ).fetchone()
        if not admin:
            raise HTTPException(status_code=403, detail="La instalación administradora no pertenece a esta organización.")
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM instalaciones_organizacion WHERE organizacion_id=? AND estado='activa'",
            (payload.organizacion_id,),
        ).fetchone()
        if int(count["n"]) >= int(org["max_instalaciones"]):
            raise HTTPException(status_code=409, detail="La licencia alcanzó el máximo de instalaciones autorizadas.")
        exp = (ahora + timedelta(minutes=payload.minutos_validez)).isoformat()
        conn.execute(
            "INSERT INTO codigos_vinculacion(codigo_hash,organizacion_id,creado_por,expira_en,usado,creado_en) VALUES(?,?,?,?,0,?)",
            (codigo_hash, payload.organizacion_id, correo, exp, ahora.isoformat()),
        )
        _org_event(conn, payload.organizacion_id, correo, payload.id_instalacion, "codigo_vinculacion_creado", f"{payload.minutos_validez} minutos")
        conn.commit()
        return {"ok": True, "codigo": codigo, "expira_en": exp, "uso_unico": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="No se pudo crear el código de vinculación.") from exc
    finally:
        conn.close()


@app.post("/organizaciones/vincular-instalacion")
def vincular_instalacion(payload: SolicitudUsarCodigo):
    correo = _autenticar_instalacion_org(payload.correo, payload.contrasena_cuenta, payload.id_instalacion)
    codigo_hash = hashlib.sha256(payload.codigo.strip().encode()).hexdigest()
    ahora_dt = datetime.now(timezone.utc)
    ahora = ahora_dt.isoformat()
    conn = db()
    try:
        conn.execute("BEGIN")
        old = conn.execute(
            "SELECT organizacion_id,estado FROM instalaciones_organizacion WHERE id_instalacion=? FOR UPDATE",
            (payload.id_instalacion,),
        ).fetchone()
        if old and old["estado"] == "activa":
            raise HTTPException(status_code=409, detail="Esta instalación ya está vinculada a una organización.")
        row = conn.execute(
            "SELECT organizacion_id,expira_en,usado,oficina_id FROM codigos_vinculacion WHERE codigo_hash=? FOR UPDATE",
            (codigo_hash,),
        ).fetchone()
        if not row or row["usado"] or datetime.fromisoformat(row["expira_en"]) <= ahora_dt:
            raise HTTPException(status_code=400, detail="El código es inválido, venció o ya fue utilizado.")
        org = _org_lock(conn, row["organizacion_id"])
        if not org or not org["activa"]:
            raise HTTPException(status_code=403, detail="La organización está inactiva.")
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM instalaciones_organizacion WHERE organizacion_id=? AND estado='activa'",
            (row["organizacion_id"],),
        ).fetchone()
        if int(count["n"]) >= int(org["max_instalaciones"]):
            raise HTTPException(status_code=409, detail="La licencia alcanzó el máximo de instalaciones autorizadas.")
        updated = conn.execute(
            "UPDATE codigos_vinculacion SET usado=1 WHERE codigo_hash=? AND usado=0",
            (codigo_hash,),
        )
        if updated.rowcount != 1:
            raise HTTPException(status_code=409, detail="El código ya fue utilizado por otra instalación.")
        if old and old["estado"] != "activa":
            conn.execute("DELETE FROM instalaciones_organizacion WHERE id_instalacion=?", (payload.id_instalacion,))
        conn.execute(
            "INSERT INTO instalaciones_organizacion(id_instalacion,organizacion_id,oficina_id,estado,vinculada_en) VALUES(?,?,?,'activa',?)",
            (payload.id_instalacion, row["organizacion_id"], row["oficina_id"], ahora),
        )
        conn.execute(
            "INSERT INTO miembros_organizacion(organizacion_id,correo,rol,activa,creada_en) VALUES(?,?,'miembro',1,?) "
            "ON CONFLICT(organizacion_id,correo) DO UPDATE SET activa=1",
            (row["organizacion_id"], correo, ahora),
        )
        _org_event(conn, row["organizacion_id"], correo, payload.id_instalacion, "instalacion_vinculada", "Código de un solo uso")
        conn.commit()
        return {"ok": True, "organizacion_id": row["organizacion_id"], "estado": "activa"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="No se pudo vincular la instalación.") from exc
    finally:
        conn.close()


@app.post("/organizaciones/oficinas/crear")
def crear_oficina(payload: SolicitudCrearOficina):
    correo = _autenticar_instalacion_org(payload.correo, payload.contrasena_cuenta, payload.id_instalacion)
    ahora = datetime.now(timezone.utc).isoformat()
    oficina_id = secrets.token_hex(16)
    conn = db()
    try:
        conn.execute("BEGIN")
        _org_admin(conn, payload.organizacion_id, correo)
        conn.execute(
            "INSERT INTO oficinas(oficina_id,organizacion_id,nombre,activa,creada_en) VALUES(?,?,?,1,?)",
            (oficina_id, payload.organizacion_id, payload.nombre.strip(), ahora),
        )
        _org_event(conn, payload.organizacion_id, correo, payload.id_instalacion, "oficina_creada", payload.nombre.strip())
        conn.commit()
        return {"ok": True, "oficina_id": oficina_id, "nombre": payload.nombre.strip()}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="No se pudo crear la oficina.") from exc
    finally:
        conn.close()


@app.post("/organizaciones/oficinas/asignar-instalacion")
def asignar_instalacion_oficina(payload: SolicitudAsignarOficina):
    correo = _autenticar_instalacion_org(payload.correo, payload.contrasena_cuenta, payload.id_instalacion)
    conn = db()
    try:
        conn.execute("BEGIN")
        _org_admin(conn, payload.organizacion_id, correo)
        oficina = conn.execute(
            "SELECT oficina_id FROM oficinas WHERE oficina_id=? AND organizacion_id=? AND activa=1",
            (payload.oficina_id, payload.organizacion_id),
        ).fetchone()
        instalacion = conn.execute(
            "SELECT organizacion_id,estado FROM instalaciones_organizacion WHERE id_instalacion=? FOR UPDATE",
            (payload.instalacion_objetivo,),
        ).fetchone()
        if not oficina or not instalacion or instalacion["organizacion_id"] != payload.organizacion_id or instalacion["estado"] != "activa":
            raise HTTPException(status_code=404, detail="No se encontró una oficina o instalación activa de esta organización.")
        conn.execute(
            "UPDATE instalaciones_organizacion SET oficina_id=? WHERE id_instalacion=?",
            (payload.oficina_id, payload.instalacion_objetivo),
        )
        _org_event(conn, payload.organizacion_id, correo, payload.id_instalacion, "instalacion_asignada_oficina", payload.instalacion_objetivo)
        conn.commit()
        return {"ok": True}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="No se pudo asignar la instalación a la oficina.") from exc
    finally:
        conn.close()


@app.post("/organizaciones/instalaciones/revocar")
def revocar_instalacion(payload: SolicitudRevocarInstalacion):
    correo = _autenticar_instalacion_org(payload.correo, payload.contrasena_cuenta, payload.id_instalacion)
    if payload.instalacion_objetivo == payload.id_instalacion:
        raise HTTPException(status_code=400, detail="No podés revocar la instalación administradora desde esta sesión.")
    conn = db()
    try:
        conn.execute("BEGIN")
        _org_admin(conn, payload.organizacion_id, correo)
        objetivo = conn.execute(
            "SELECT organizacion_id,estado FROM instalaciones_organizacion WHERE id_instalacion=? FOR UPDATE",
            (payload.instalacion_objetivo,),
        ).fetchone()
        if not objetivo or objetivo["organizacion_id"] != payload.organizacion_id:
            raise HTTPException(status_code=404, detail="La instalación no pertenece a esta organización.")
        if objetivo["estado"] == "activa":
            conn.execute(
                "UPDATE instalaciones_organizacion SET estado='revocada' WHERE id_instalacion=?",
                (payload.instalacion_objetivo,),
            )
        _org_event(conn, payload.organizacion_id, correo, payload.id_instalacion, "instalacion_revocada", payload.instalacion_objetivo)
        conn.commit()
        return {"ok": True, "estado": "revocada"}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="No se pudo revocar la instalación.") from exc
    finally:
        conn.close()


@app.post("/organizaciones/cupo/actualizar")
def actualizar_cupo(payload: SolicitudCambiarCupo):
    correo = _autenticar_instalacion_org(payload.correo, payload.contrasena_cuenta, payload.id_instalacion)
    conn = db()
    try:
        conn.execute("BEGIN")
        _org_admin(conn, payload.organizacion_id, correo)
        org = _org_lock(conn, payload.organizacion_id)
        count = conn.execute(
            "SELECT COUNT(*) AS n FROM instalaciones_organizacion WHERE organizacion_id=? AND estado='activa'",
            (payload.organizacion_id,),
        ).fetchone()
        if payload.max_instalaciones < int(count["n"]):
            raise HTTPException(status_code=409, detail=f"El nuevo cupo no puede ser menor que las instalaciones activas ({count['n']}).")
        conn.execute(
            "UPDATE organizaciones SET max_instalaciones=? WHERE organizacion_id=?",
            (payload.max_instalaciones, payload.organizacion_id),
        )
        _org_event(conn, payload.organizacion_id, correo, payload.id_instalacion, "cupo_actualizado", str(payload.max_instalaciones))
        conn.commit()
        return {"ok": True, "max_instalaciones": payload.max_instalaciones}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="No se pudo actualizar el cupo.") from exc
    finally:
        conn.close()


@app.post("/organizaciones/miembros/agregar")
def agregar_miembro(payload: SolicitudMiembroOrg):
    correo = _autenticar_instalacion_org(payload.correo, payload.contrasena_cuenta, payload.id_instalacion)
    miembro_correo = normalizar_correo(payload.correo_miembro)
    if not validar_correo(miembro_correo):
        raise HTTPException(status_code=422, detail="El correo del miembro no es válido.")
    if payload.rol == "admin" and miembro_correo != correo:
        # Los administradores adicionales deben agregarse explícitamente desde la tabla de miembros;
        # se permite aquí, pero requiere que la cuenta ya esté verificada.
        pass
    conn = db()
    try:
        conn.execute("BEGIN")
        _org_admin(conn, payload.organizacion_id, correo)
        cuenta = conn.execute(
            "SELECT verificado FROM cuentas WHERE correo=?", (miembro_correo,)
        ).fetchone()
        if not cuenta or not cuenta["verificado"]:
            raise HTTPException(status_code=404, detail="El usuario debe crear y verificar su cuenta DocuCentral antes de ser agregado.")
        ahora = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO miembros_organizacion(organizacion_id,correo,rol,activa,creada_en) VALUES(?,?,?,?,?) "
            "ON CONFLICT(organizacion_id,correo) DO UPDATE SET rol=excluded.rol,activa=1",
            (payload.organizacion_id, miembro_correo, payload.rol, 1, ahora),
        )
        _org_event(conn, payload.organizacion_id, correo, payload.id_instalacion, "miembro_agregado", f"{miembro_correo}:{payload.rol}")
        conn.commit()
        return {"ok": True, "correo_miembro": miembro_correo, "rol": payload.rol}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="No se pudo agregar el miembro.") from exc
    finally:
        conn.close()


@app.post("/organizaciones/miembros/quitar")
def quitar_miembro(payload: SolicitudQuitarMiembro):
    correo = _autenticar_instalacion_org(payload.correo, payload.contrasena_cuenta, payload.id_instalacion)
    objetivo = normalizar_correo(payload.correo_miembro)
    if objetivo == correo:
        raise HTTPException(status_code=400, detail="No podés quitarte a vos mismo como administrador desde esta operación.")
    conn = db()
    try:
        conn.execute("BEGIN")
        _org_admin(conn, payload.organizacion_id, correo)
        result = conn.execute(
            "UPDATE miembros_organizacion SET activa=0 WHERE organizacion_id=? AND correo=? AND activa=1",
            (payload.organizacion_id, objetivo),
        )
        if result.rowcount != 1:
            raise HTTPException(status_code=404, detail="No se encontró un miembro activo con ese correo.")
        _org_event(conn, payload.organizacion_id, correo, payload.id_instalacion, "miembro_desactivado", objetivo)
        conn.commit()
        return {"ok": True, "correo_miembro": objetivo, "activa": False}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail="No se pudo quitar el miembro.") from exc
    finally:
        conn.close()


@app.post("/organizaciones/consultar")
def consultar_organizacion_post(payload: SolicitudOrgAdmin):
    correo = _autenticar_instalacion_org(payload.correo, payload.contrasena_cuenta, payload.id_instalacion)
    conn = db()
    try:
        miembro = conn.execute(
            "SELECT rol,activa FROM miembros_organizacion WHERE organizacion_id=? AND correo=?",
            (payload.organizacion_id, correo),
        ).fetchone()
        if not miembro or not miembro["activa"]:
            raise HTTPException(status_code=403, detail="No pertenecés a esta organización.")
        org = conn.execute(
            "SELECT organizacion_id,nombre,propietario_correo,max_instalaciones,activa,creada_en FROM organizaciones WHERE organizacion_id=?",
            (payload.organizacion_id,),
        ).fetchone()
        if not org:
            raise HTTPException(status_code=404, detail="No existe la organización.")
        if miembro["rol"] == "admin":
            oficinas = conn.execute(
                "SELECT oficina_id,nombre,activa,creada_en FROM oficinas WHERE organizacion_id=? ORDER BY creada_en",
                (payload.organizacion_id,),
            ).fetchall()
            instalaciones = conn.execute(
                "SELECT id_instalacion,oficina_id,estado,vinculada_en FROM instalaciones_organizacion WHERE organizacion_id=? ORDER BY vinculada_en",
                (payload.organizacion_id,),
            ).fetchall()
        else:
            oficinas = []
            instalaciones = conn.execute(
                "SELECT id_instalacion,oficina_id,estado,vinculada_en FROM instalaciones_organizacion WHERE organizacion_id=? AND id_instalacion=?",
                (payload.organizacion_id, payload.id_instalacion),
            ).fetchall()
        return {"ok": True, "organizacion": org, "rol": miembro["rol"], "oficinas": oficinas, "instalaciones": instalaciones}
    finally:
        conn.close()


@app.post("/organizaciones/estado-instalacion")
def estado_instalacion_organizacion(payload: SolicitudOrgAdmin):
    correo = _autenticar_instalacion_org(payload.correo, payload.contrasena_cuenta, payload.id_instalacion, permitir_revocada=True)
    conn = db()
    try:
        row = conn.execute(
            "SELECT io.organizacion_id,io.estado,o.activa AS organizacion_activa,o.nombre,o.max_instalaciones "
            "FROM instalaciones_organizacion io JOIN organizaciones o ON o.organizacion_id=io.organizacion_id "
            "WHERE io.id_instalacion=?",
            (payload.id_instalacion,),
        ).fetchone()
        if not row:
            return {"ok": True, "vinculada": False, "estado": "sin_organizacion"}
        return {
            "ok": True,
            "vinculada": True,
            "estado": row["estado"],
            "organizacion_activa": bool(row["organizacion_activa"]),
            "organizacion_id": row["organizacion_id"],
            "nombre": row["nombre"],
            "max_instalaciones": row["max_instalaciones"],
        }
    finally:
        conn.close()


@app.post("/organizaciones/auditoria")
def consultar_auditoria(payload: SolicitudOrgAdmin):
    correo = _autenticar_instalacion_org(payload.correo, payload.contrasena_cuenta, payload.id_instalacion)
    conn = db()
    try:
        _org_admin(conn, payload.organizacion_id, correo)
        rows = conn.execute(
            "SELECT correo,id_instalacion,accion,detalle,creado_en FROM auditoria_organizacion "
            "WHERE organizacion_id=? ORDER BY id DESC LIMIT 200",
            (payload.organizacion_id,),
        ).fetchall()
        return {"ok": True, "eventos": rows}
    finally:
        conn.close()


@app.get("/organizaciones/{organizacion_id}")
def consultar_organizacion(organizacion_id: str, correo: str, contrasena_cuenta: str, id_instalacion: str):
    # Compatibilidad con la primera versión; las nuevas instalaciones deben usar POST /organizaciones/consultar.
    correo = _autenticar_instalacion_org(correo, contrasena_cuenta, id_instalacion)
    conn = db()
    try:
        miembro = conn.execute(
            "SELECT rol,activa FROM miembros_organizacion WHERE organizacion_id=? AND correo=?",
            (organizacion_id, correo),
        ).fetchone()
        if not miembro or not miembro["activa"]:
            raise HTTPException(status_code=403, detail="No pertenecés a esta organización.")
        org = conn.execute(
            "SELECT organizacion_id,nombre,propietario_correo,max_instalaciones,activa,creada_en FROM organizaciones WHERE organizacion_id=?",
            (organizacion_id,),
        ).fetchone()
        oficinas = conn.execute(
            "SELECT oficina_id,nombre,activa,creada_en FROM oficinas WHERE organizacion_id=? ORDER BY creada_en",
            (organizacion_id,),
        ).fetchall()
        instalaciones = conn.execute(
            "SELECT id_instalacion,oficina_id,estado,vinculada_en FROM instalaciones_organizacion WHERE organizacion_id=? ORDER BY vinculada_en",
            (organizacion_id,),
        ).fetchall() if miembro["rol"] == "admin" else []
        return {"ok": True, "organizacion": org, "rol": miembro["rol"], "oficinas": oficinas, "instalaciones": instalaciones}
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
    """Solicita el código por correo y recupera el ID canónico si el registro local quedó desactualizado.

    El correo no permite cambiar la contraseña por sí solo: el restablecimiento sigue
    exigiendo el token de un solo uso enviado al correo verificado.
    """
    id_solicitado = payload.id_instalacion.strip()
    correo_solicitado = normalizar_correo(payload.correo) if payload.correo.strip() else ""
    conn = db()
    try:
        row = conn.execute(
            "SELECT i.id_instalacion, i.verificado, i.correo, c.verificado AS cuenta_verificada "
            "FROM instalaciones i LEFT JOIN cuentas c ON c.correo=i.correo WHERE i.id_instalacion=?",
            (id_solicitado,),
        ).fetchone()

        # Si el ID guardado en esta PC quedó viejo, buscamos una instalación verificada
        # de la misma cuenta. Nunca se usa un correo sin verificar ni se omite el OTP.
        if row is None and correo_solicitado:
            row = conn.execute(
                "SELECT i.id_instalacion, i.verificado, i.correo, c.verificado AS cuenta_verificada "
                "FROM instalaciones i JOIN cuentas c ON c.correo=i.correo "
                "WHERE lower(i.correo)=? AND i.verificado=1 AND c.verificado=1 "
                "ORDER BY i.actualizado_en DESC LIMIT 1",
                (correo_solicitado,),
            ).fetchone()
    finally:
        conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="No encontramos una instalación verificada para esa cuenta.")
    if correo_solicitado and normalizar_correo(row["correo"]) != correo_solicitado:
        raise HTTPException(status_code=404, detail="La instalación no corresponde a la cuenta indicada.")
    if not row["verificado"] or not row["cuenta_verificada"]:
        raise HTTPException(status_code=403, detail="El correo de la cuenta todavía no fue verificado.")

    resultado = crear_y_enviar_token(row["id_instalacion"], "recuperación", row["correo"])
    resultado["id_instalacion"] = row["id_instalacion"]
    return resultado


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

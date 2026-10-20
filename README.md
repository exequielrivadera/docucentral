# DocuCentral — backend de cuentas para Vercel

Este paquete separa el backend de la aplicación de escritorio. Mantiene las rutas actuales de cuentas, verificación, recuperación y eliminación, pero utiliza PostgreSQL persistente en lugar de SQLite local.

## Incluye

- `servidor_recuperacion.py`: API FastAPI adaptada a PostgreSQL.
- `api/index.py` y `vercel.json`: entrada y enrutamiento para Vercel.
- `migrar_sqlite_a_postgres.py`: importación conservadora desde `recovery.db`.
- `.env.example`: nombres de variables sin secretos reales.
- `servidor_recuperacion_original.txt`: copia de referencia del código entregado para facilitar la comparación.

## Importante antes de desplegar

1. No subas `recovery.db`, su respaldo ni `.env`.
2. Crea una base PostgreSQL administrada y guarda su URL como variable `DATABASE_URL` en Vercel.
3. Configura en Vercel las variables `BREVO_SMTP_HOST`, `BREVO_SMTP_PORT`, `BREVO_SMTP_USER`, `BREVO_SMTP_KEY`, `BREVO_SENDER_EMAIL` y `BREVO_SENDER_NAME`. El remitente previsto es `docucentrallr@gmail.com`.
4. No ejecutes la migración hasta verificar que `DATABASE_URL` apunta a la base correcta y vacía o que entendés qué filas se omitirán por conflicto.
5. Conserva la copia local `respaldo_seguridad/recovery_antes_de_migrar.db` hasta terminar pruebas funcionales de la API y de la app de escritorio.

## Migrar datos desde Windows PowerShell

Instala dependencias en un entorno separado o en el del backend:

```powershell
python -m pip install -r requirements.txt
$env:DATABASE_URL = "PEGAR_URL_DE_POSTGRESQL_SOLO_EN_LA_TERMINAL_PRIVADA"
python .\migrar_sqlite_a_postgres.py --source "C:\Users\EXEQUIELNK\Desktop\LectorPDF\recovery.db"
```

La URL no debe pegarse en chats ni subirse a GitHub. El importador abre SQLite en modo solo lectura, valida su integridad, inserta por clave primaria y omite filas en conflicto. No borra ni modifica la base de origen. Si ya existe información en PostgreSQL, revisa los totales insertados/omitidos antes de continuar.

## Prueba local de la API

Con `DATABASE_URL` y variables SMTP configuradas:

```powershell
python -m uvicorn api.index:app --host 127.0.0.1 --port 8000
```

Abrir `http://127.0.0.1:8000/docs` y comprobar que estén las rutas `/solicitar-eliminacion-cuenta` y `/eliminar-cuenta`. No uses las rutas destructivas contra datos reales durante la prueba.

## Variables necesarias

`DATABASE_URL` es obligatoria. Las credenciales SMTP son necesarias para enviar códigos por correo. No hay secretos reales incluidos en este paquete.

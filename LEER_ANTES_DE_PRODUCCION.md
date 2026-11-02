# DocuCentral — paquete de trabajo para organizaciones

Este ZIP excluye .env, bases de datos, data/, respaldos y entornos virtuales.

## Incluye
- Código de escritorio y recursos actuales.
- Backend PostgreSQL con esquema aditivo y rutas iniciales para crear organización, crear código de vinculación, vincular una instalación y consultar organización.
- Archivo spec inicial de PyInstaller.

## Estado honesto
Este paquete NO es todavía un instalador listo para distribución ni una implementación completa desde la interfaz. Las nuevas rutas del backend todavía requieren pruebas automatizadas contra una base PostgreSQL de prueba, endurecimiento de concurrencia del código de vinculación, integración de pantallas/llamadas en `main.py`, administración de oficinas y miembros, sesiones de autenticación revocables, y definición final de licencias. No reemplazar producción con este backend sin probarlo primero.

Las nuevas tablas se crean con `CREATE TABLE IF NOT EXISTS`; no se eliminan las tablas actuales. Las instalaciones existentes no se asignan automáticamente a una organización.

## Variables de backend
Configurar `DATABASE_URL`, `BREVO_SMTP_HOST`, `BREVO_SMTP_PORT`, `BREVO_SMTP_USER`, `BREVO_SMTP_KEY`, `BREVO_SENDER_EMAIL` y `BREVO_SENDER_NAME` en Vercel. Nunca subir credenciales.

## Compilación preliminar en Windows (solo pruebas)
```powershell
python -m pip install -r requirements-desktop-build.txt
python -m PyInstaller --clean --noconfirm docucentral.spec
```
Antes de distribuir: probar en PC limpia, validar recuperación, alta de cuenta, licencias, vinculación, revocación y apertura de PDF. La licencia no sincroniza automáticamente archivos ni bloqueos de PDF.

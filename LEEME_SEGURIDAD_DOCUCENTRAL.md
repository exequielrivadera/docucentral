# Seguridad de DocuCentral

Archivos de esta versión:

- `main.py`: aplicación principal de DocuCentral.
- `nucleo_seguridad.py`: cifrado, contraseña maestra, clave de recuperación y protección de archivos.
- `servidor_recuperacion.py`: servidor FastAPI que registra instalaciones y envía códigos de verificación/recuperación mediante Brevo SMTP.
- `requisitos-seguridad.txt`: dependencias necesarias.

## Instalación

En PowerShell, dentro del proyecto:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requisitos-seguridad.txt
```

## Ejecutar el servidor local

Configurá las variables de entorno del servidor:

```powershell
$env:BREVO_SMTP_HOST="smtp-relay.brevo.com"
$env:BREVO_SMTP_PORT="587"
$env:BREVO_SMTP_USER="TU_USUARIO_SMTP"
$env:BREVO_SMTP_KEY="TU_CLAVE_SMTP"
$env:BREVO_SENDER_EMAIL="tu-correo@dominio.com"
$env:BREVO_SENDER_NAME="DocuCentral"
$env:DOCUCENTRAL_RECOVERY_DB="recuperacion.db"
```

Luego:

```powershell
python -m uvicorn servidor_recuperacion:app --host 127.0.0.1 --port 8000
```

## Ejecutar DocuCentral

En otra PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python main.py
```

Los nombres de librerías y APIs externas (`cryptography`, `FastAPI`, `Uvicorn`, `AESGCM`, `Scrypt`, etc.) se mantienen con sus nombres oficiales.

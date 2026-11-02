# DocuCentral – corrección de recuperación por correo

## Qué corrige
- El cliente envía el correo de la cuenta junto con el ID local.
- Si el ID local ya no existe en el backend, el servidor busca una instalación verificada asociada a ese correo.
- El servidor envía el código únicamente al correo verificado y devuelve el ID canónico.
- El cliente guarda ese ID canónico y lo utiliza para restablecer la contraseña.
- El restablecimiento sigue exigiendo el código de un solo uso enviado por correo.

## Archivos modificados
- `backend_docucentral/servidor_recuperacion.py`
- `main.py`

## Publicación
1. Hacer copia de seguridad del proyecto actual.
2. Reemplazar los archivos por los de este paquete y subir los cambios al repositorio.
3. Mantener en Vercel `DATABASE_URL` apuntando a la rama Neon correcta y las variables SMTP actuales.
4. Hacer Deploy de Production.
5. Reconstruir el ejecutable de escritorio con este `main.py` y distribuir esa versión.

No ejecutar migraciones ni borrar tablas. No se modifica la contraseña local maestra ni los PDF protegidos.

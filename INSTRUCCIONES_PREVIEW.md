# DocuCentral — paquete actual preparado para Preview

## Qué se modificó
- Se conserva el `main.py`, `gestion_organizacion.py`, el backend PostgreSQL y los recursos del ZIP actual.
- Se agregó `api/index.py` en la raíz del repositorio para que Vercel importe explícitamente la aplicación FastAPI desde `servidor_recuperacion.py`.
- Se actualizó el `vercel.json` de la raíz para dirigir las solicitudes al endpoint serverless `/api/index`.
- Se conservó `index.py` de la raíz por compatibilidad con la estructura que ya existía.

## Despliegue seguro
1. Subir estos archivos a una rama de prueba de GitHub, no a `main`.
2. En Vercel, comprobar que el deployment Preview use la rama de prueba y la variable `DATABASE_URL` de la rama Neon `docucentral-staging`.
3. Mantener las variables SMTP de Brevo configuradas para Preview.
4. Esperar `Ready` y comprobar `/openapi.json`. Deben aparecer las rutas `/organizaciones/crear`, `/organizaciones/vincular-instalacion`, `/organizaciones/instalaciones/revocar` y `/organizaciones/estado-instalacion`.
5. Solo hacer pruebas con cuentas sintéticas en staging. No probar operaciones destructivas contra Production.

## Seguridad y contenido omitido
Por seguridad y para reducir el tamaño, este ZIP no contiene `.git`, entornos virtuales, `.env`, archivos de base de datos (`*.db`, `*.sqlite*`), carpeta `data/` ni respaldos `respaldo_seguridad/`. Esos archivos contienen estado local o información sensible y no son necesarios para desplegar el backend. La aplicación puede recrear su carpeta de datos al ejecutarse.

## Estado de validación
Se revisó estáticamente el backend y se verificó que los archivos Python compilen. No se pudo probar una conexión real a Neon desde este entorno. No considerar validado para producción hasta completar pruebas en Preview.

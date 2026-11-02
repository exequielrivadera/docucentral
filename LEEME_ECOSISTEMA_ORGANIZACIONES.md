# DocuCentral — paquete integrado de organizaciones y equipos

## Qué incluye
- La aplicación de escritorio existente (`main.py`) con el menú **Organización → Organización y equipos…**.
- Panel de gestión de organización: crear organización, vincular esta PC por código, generar código de un solo uso, consultar instalaciones, crear oficinas, asignar instalaciones, revocar instalaciones, cambiar cupo y consultar auditoría.
- Backend FastAPI/PostgreSQL con endpoints aditivos para esas operaciones.
- Punto de entrada y dependencias en la raíz para el despliegue de Vercel.

## Antes de producción
Este paquete fue revisado estáticamente y los archivos Python compilan. No se pudo probar una transacción real contra tu Neon ni una instalación EXE en Windows desde este entorno. No lo consideres validado para producción hasta hacer la prueba de staging descrita abajo.

### Despliegue de backend
El repositorio conectado a `docucentral.vercel.app` usa la raíz del repositorio. Los archivos de entrada para esa estructura son:
- `index.py`
- `servidor_recuperacion.py`
- `requirements.txt`
- `vercel.json`

El `servidor_recuperacion.py` de la raíz de este paquete es la versión PostgreSQL con recuperación y organizaciones. Mantener en Vercel las variables `DATABASE_URL` y las cinco variables de Brevo que ya existen. No pegues secretos en GitHub ni en el ZIP. Antes de desplegar, confirmá que `DATABASE_URL` tenga un valor válido en Production; no la reemplaces por una URL inventada.

### Base de datos
El backend crea las tablas que faltan con `CREATE TABLE IF NOT EXISTS` al abrir una conexión. Es aditivo y no borra las tablas de cuentas existentes. Hacer backup de Neon antes del primer despliegue. No ejecutar el script `migrar_sqlite_a_postgres.py` para este cambio: no es necesario para crear las tablas nuevas.

### Prueba recomendada en staging
1. Probar `/` y `/openapi.json`.
2. Registrar/verificar una cuenta de prueba y comprobar recuperación.
3. Crear una organización de prueba con cupo 2.
4. Generar un código, vincular otra instalación de prueba y comprobar que el código no puede reutilizarse.
5. Intentar una tercera instalación: debe rechazarse por cupo.
6. Revocar la segunda instalación y comprobar que al iniciar sesión en esa PC el cliente detecta la revocación.
7. Comprobar que las cuentas existentes siguen pudiendo recuperar contraseña.

### Límites que aún requieren validación
- La interfaz permite ajustar el número de instalaciones, pero la autorización comercial del cupo (planes/licencias pagadas) todavía no está conectada a un proveedor de licencias.
- El estado de revocación se consulta cuando se inicia sesión; no es un bloqueo instantáneo offline. Una PC sin conexión no puede recibir una revocación hasta consultar el servidor.
- Los PDF continúan locales. Este paquete no sube ni sincroniza el contenido de los PDF. La sincronización de marcadores de bloqueo entre equipos requiere un identificador estable por documento y una capa de sincronización separada.
- La interfaz de administración de miembros por correo/roles todavía no tiene altas/bajas dedicadas; el propietario es administrador y la consulta de la organización usa los miembros que existan en la tabla.


from pathlib import Path
import zipfile
import os

ORIGEN = Path(r"C:\Users\EXEQUIELNK\Desktop\LectorPDF")
DESTINO = Path(r"C:\Users\EXEQUIELNK\Desktop\DocuCentral_revision.zip")

EXCLUIR_CARPETAS = {
    ".venv", "venv", "env", "__pycache__", ".git",
    "node_modules", "build", "dist", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "site-packages"
}

EXCLUIR_ARCHIVOS = {
    ".env", ".env.local", ".env.production",
    "id_rsa", "id_ed25519"
}

EXCLUIR_EXTENSIONES = {".pyc", ".pyo", ".log", ".tmp"}

EXCLUIR_NOMBRES = {
    "cuentas.json", "usuarios.json",
    "database.db", "docucentral.db"
}


def excluir(ruta):
    partes = {p.lower() for p in ruta.parts}
    nombre = ruta.name.lower()

    if partes & {x.lower() for x in EXCLUIR_CARPETAS}:
        return True

    if nombre in {x.lower() for x in EXCLUIR_ARCHIVOS}:
        return True

    if nombre in {x.lower() for x in EXCLUIR_NOMBRES}:
        return True

    if ruta.suffix.lower() in EXCLUIR_EXTENSIONES:
        return True

    if nombre.endswith((".sqlite", ".sqlite3", ".db")):
        return True

    if nombre.startswith(".env."):
        return True

    return False


def main():
    if not ORIGEN.is_dir():
        print(f"No existe la carpeta: {ORIGEN}")
        input("Presioná Enter para salir...")
        return

    total = 0
    omitidos = 0

    with zipfile.ZipFile(
        DESTINO, "w", compression=zipfile.ZIP_DEFLATED
    ) as zipf:
        for raiz, carpetas, archivos in os.walk(ORIGEN):
            raiz = Path(raiz)

            carpetas[:] = [
                c for c in carpetas
                if not excluir(raiz / c)
            ]

            for archivo in archivos:
                ruta = raiz / archivo
                relativa = ruta.relative_to(ORIGEN)

                if excluir(relativa):
                    omitidos += 1
                    continue

                try:
                    zipf.write(ruta, relativa)
                    total += 1
                except OSError as error:
                    print(f"No se pudo incluir {relativa}: {error}")

    print("\nZIP creado:")
    print(DESTINO)
    print(f"Archivos incluidos: {total}")
    print(f"Archivos omitidos: {omitidos}")
    print(f"Tamaño: {DESTINO.stat().st_size / (1024 * 1024):.1f} MB")
    input("\nPresioná Enter para cerrar...")


if __name__ == "__main__":
    main()

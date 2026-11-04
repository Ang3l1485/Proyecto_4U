import argparse
from pathlib import Path
import shutil

# Lista con todos los archivos y carpetas del proyecto
ESTRUCTURA = [
    "domain/model/FotoRecolectada.kt",
    "domain/model/SesionRecoleccion.kt",
    "domain/usecase/DisparadorCaptura.kt",
    "data/repository/RecoleccionRepository.kt",
]

def gestionar_elemento(ruta_str: str, eliminar: bool = False):
    """Crea o elimina un archivo o carpeta según la acción seleccionada."""
    ruta = Path(ruta_str)

    try:
        if eliminar:
            # Lógica de eliminación
            if ruta.exists():
                if ruta.is_file():
                    ruta.unlink()
                    print(f"[Archivo Eliminado]: {ruta}")
                elif ruta.is_dir():
                    shutil.rmtree(ruta, ignore_errors=True)
                    print(f"[Carpeta Eliminada]: {ruta}")
            
            # Opcional: limpiar directorios padres vacíos hacia arriba
            for parent in ruta.parents:
                if parent in (Path(""), Path(".")):
                    break
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
                    print(f"[Carpeta Vacía Limpiada]: {parent}")
        else:
            # Lógica de creación (original)
            if ruta.suffix:
                # Crear directorios padres y el archivo
                ruta.parent.mkdir(parents=True, exist_ok=True)
                ruta.touch(exist_ok=True)
                print(f"[Archivo Creado]: {ruta}")
            else:
                # Es una carpeta explicita
                ruta.mkdir(parents=True, exist_ok=True)
                print(f"[Carpeta Creada]: {ruta}")

    except Exception as e:
        print(f"Error al procesar '{ruta_str}': {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gestiona la estructura de archivos y carpetas del proyecto.")
    parser.add_argument(
        "--eliminar", 
        action="store_true", 
        help="Si se activa, elimina los archivos y carpetas especificados en lugar de crearlos."
    )
    
    args = parser.parse_args()

    accion_texto = "Eliminando" if args.eliminar else "Creando"
    print(f"{accion_texto} estructura de archivos y carpetas...\n")

    # Si eliminamos, recorremos la lista en orden inverso para borrar primero archivos y luego carpetas hijas/padres
    elementos = reversed(ESTRUCTURA) if args.eliminar else ESTRUCTURA

    for elemento in elementos:
        gestionar_elemento(elemento, eliminar=args.eliminar)

    print(f"\n¡Operación completada con éxito!")
# Proyecto 4U

Proyecto para recopilar un dataset visual del campus, entrenar y validar modelos de visión por computador y estimar la ubicación de una persona a partir de imágenes.

## Componentes

### `APK/`: aplicación de recolección de datos

Contiene la aplicación Flutter utilizada para construir el dataset. Desde ella se capturan fotografías del campus y se registran los metadatos que las describen: ubicación GPS, rumbo, bloque, piso, zona, fecha y demás información de la captura. También permite organizar, revisar, editar y eliminar registros para mantener un conjunto de datos limpio y ampliable.

### `localización/`: backend de localización

Contiene el sistema backend que procesa el dataset y estima la ubicación del usuario. Indexa las imágenes y sus metadatos, busca referencias visuales similares y combina esa evidencia con GPS, rumbo y filtrado temporal para corregir la posición estimada. La ubicación corregida se entrega como coordenadas y como una referencia comprensible del campus, con el objetivo de orientar a personas con discapacidad visual.

## Flujo general

```text
APK: captura de imagen + metadatos
        ↓
Dataset de imágenes georreferenciadas
        ↓
localización: indexación, reconocimiento visual y corrección de GPS
        ↓
Ubicación estimada y referencia del campus para guiar al usuario
```

El procesamiento pesado se ejecuta en el backend. La aplicación móvil aporta las capturas y sus sensores; el sistema de localización transforma esa información en una estimación de posición que podrá integrarse posteriormente con navegación y rutas accesibles.

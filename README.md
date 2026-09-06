# RustIDEAM

Servicio en Rust para extender y publicar la animación del canal infrarrojo GOES-16 C13 distribuida por IDEAM.

## Objetivo

IDEAM publica `DUITAMA_C13.gif` con aproximadamente las últimas 2 horas. El servicio debe descargar esa fuente periódicamente, identificar y conservar los frames nuevos, mantener un buffer histórico local de 6 horas y producir una salida eficiente para visualización dentro del portal WeeWX.

Fuente actual:

`https://bart.ideam.gov.co/ospa/gifs/satelite/INFRARROJO/DUITAMA_C13.gif`

## Decisiones de diseño ya acordadas

- Lenguaje: Rust.
- Ejecución objetivo: Raspberry Pi 5 / ARM64.
- Intervalo de adquisición por defecto: 10 minutos.
- Ventana histórica local: 6 horas.
- La fecha/hora válida de un frame se obtiene del texto visible del encabezado del propio frame, no de metadatos ni de la hora de descarga.
- No usar Tesseract ni OCR externo.
- Reconocimiento específico por plantillas de caracteres sobre una región fija y configurable del encabezado.
- Deduplicación de frames antes de persistirlos.
- Persistencia suficiente para reconstruir las 6 horas después de reinicios.
- Salida primaria prevista: MP4/H.264, sujeta a validación A/B de calidad/tamaño frente a Animated WebP.
- Escritura atómica del archivo publicado para que WeeWX nunca sirva un archivo incompleto.
- Configuración operativa externa en YAML.
- El servicio será administrado por systemd.

## Documentación

- [`SPEC.md`](SPEC.md): especificación funcional y criterios de aceptación.
- [`ARCHITECTURE.md`](ARCHITECTURE.md): componentes y flujo de datos.
- [`config.example.yaml`](config.example.yaml): parámetros externos previstos.
- [`docs/timestamp-recognition.md`](docs/timestamp-recognition.md): reconocimiento de fecha/hora.
- [`docs/video-encoding.md`](docs/video-encoding.md): estrategia de salida y benchmark.
- [`docs/weewx-integration.md`](docs/weewx-integration.md): publicación en WeeWX.

## Estado

Repositorio inicial de especificación. Las coordenadas reales del timestamp, resolución del GIF, número exacto de frames por archivo y parámetros finales de compresión se medirán sobre muestras reales y no se asumirán en código.

# Estrategia de codificación de salida

## Problema

El GIF fuente de IDEAM contiene aproximadamente 2 horas y tiene un tamaño de varios MB. Extenderlo linealmente a 6 horas como GIF produciría un archivo innecesariamente grande para publicación web.

## Salida primaria prevista

MP4/H.264, sin audio.

Razones:

- Aprovecha redundancia temporal entre frames meteorológicos consecutivos.
- Amplia compatibilidad de navegador.
- Adecuado para reproducción automática, silenciosa y en bucle.
- Carga web previsiblemente menor que un GIF equivalente.

## Alternativa a medir

Animated WebP.

Se conserva como candidato porque mantiene semántica de imagen y puede integrarse mediante `<img>`, pero no se asumirá que supera a H.264 hasta medir material real.

## Benchmark obligatorio

Sobre una ventana real de 6 horas se deben generar al menos:

1. GIF equivalente.
2. Animated WebP.
3. MP4/H.264.

Registrar para cada salida:

- Resolución.
- Número de frames.
- Duración de reproducción.
- Tamaño de archivo.
- Tiempo de codificación en Raspberry Pi 5.
- Uso máximo aproximado de CPU y memoria.
- Inspección visual de detalles meteorológicos y legibilidad del encabezado.

## Parámetros

No se fijarán CRF, preset o FPS definitivos antes del benchmark.

La resolución original debe conservarse inicialmente. Solo se evaluará reducción de resolución si la compresión de video no alcanza un tamaño razonable sin pérdida visual relevante.

## Publicación segura

La codificación debe escribir a un archivo temporal. Solo después de finalizar y validar el contenedor se reemplazará el archivo público mediante rename atómico.

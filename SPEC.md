# Especificación funcional — RustIDEAM

## 1. Propósito

Construir un servicio nativo en Rust para Raspberry Pi 5 que tome la animación `DUITAMA_C13.gif` publicada por IDEAM, amplíe localmente la ventana temporal disponible desde aproximadamente 2 horas hasta 6 horas y publique una representación animada de menor tamaño adecuada para el portal WeeWX.

## 2. Fuente

URL inicial:

`https://bart.ideam.gov.co/ospa/gifs/satelite/INFRARROJO/DUITAMA_C13.gif`

La fuente se consulta por defecto cada 600 segundos.

El servicio no debe asumir que la hora de descarga representa la hora meteorológica de los frames.

## 3. Timestamp de los frames

La fecha/hora válida se leerá del texto visible en el encabezado de cada frame.

Restricciones:

- No usar metadatos como fuente de tiempo.
- No usar Tesseract ni procesos OCR externos.
- Usar reconocimiento por plantillas de caracteres sobre una región configurable.
- El reconocedor debe limitarse al conjunto mínimo de símbolos requerido por el formato de fecha/hora observado.
- Las coordenadas y dimensiones del recorte deben ser configurables mediante YAML.
- Si un timestamp no puede reconocerse con confianza suficiente, el frame no debe incorporarse silenciosamente al histórico.

## 4. Deduplicación

Cada frame debe disponer de una identidad estable calculada a partir de su contenido decodificado o de otra representación determinista validada durante implementación.

El servicio debe evitar guardar más de una vez el mismo frame aunque aparezca en varias descargas consecutivas del GIF fuente.

La deduplicación debe sobrevivir reinicios.

## 5. Histórico local

El origen solo aporta aproximadamente 2 horas, por lo que el servicio mantendrá localmente una ventana móvil de 6 horas.

Requisitos:

- Persistir frames nuevos con su timestamp validado.
- Mantenerlos ordenados cronológicamente.
- Eliminar frames cuya antigüedad exceda la ventana configurada.
- Tras un reinicio, reconstruir el estado usando la persistencia local.
- No depender del GIF fuente para recuperar las horas que IDEAM ya haya retirado.

## 6. Salida publicada

Salida primaria prevista:

- MP4.
- Codec H.264.
- Sin pista de audio.
- Reproducción apta para `autoplay`, `loop`, `muted` y `playsinline` en navegadores modernos.

Antes de fijar parámetros definitivos deberá realizarse una comparación real entre:

- GIF original extendido a 6 h.
- Animated WebP.
- MP4/H.264.

El criterio será preservar utilidad visual meteorológica reduciendo significativamente el tamaño frente al GIF equivalente.

No reducir resolución de forma predeterminada hasta disponer de mediciones A/B.

## 7. Generación atómica

La salida debe generarse primero con un nombre temporal y publicarse mediante una operación atómica de reemplazo/rename.

WeeWX nunca debe poder leer un archivo parcialmente escrito.

Si una actualización falla, debe permanecer disponible el último archivo válido.

## 8. Configuración

Todos los valores operativos susceptibles de ajuste deben residir en YAML, incluyendo al menos:

- URL fuente.
- Intervalo de adquisición.
- Timeouts de red.
- Duración del histórico.
- Ruta de persistencia.
- Ruta de publicación.
- Región de recorte del timestamp.
- Umbral o parámetros de binarización.
- Parámetros del reconocedor por plantillas.
- Formato esperado del timestamp.
- Duración/fps de reproducción.
- Parámetros de compresión de video una vez medidos.
- Nivel de logging.

Los valores específicos todavía no medidos deben aparecer como pendientes explícitos, no como supuestos silenciosos.

## 9. Ejecución

Destino operativo:

- Raspberry Pi 5.
- ARM64.
- Linux.
- Servicio gestionado mediante systemd.

El proceso debe permanecer en ejecución y despertar según el intervalo configurado.

No se requiere cron ni `flock` si la implementación funciona como daemon único.

## 10. Observabilidad

El servicio debe registrar como mínimo:

- Inicio y versión.
- Descarga satisfactoria/fallida.
- Tamaño de descarga.
- Número de frames detectados en fuente.
- Número de frames nuevos.
- Número de duplicados.
- Frames rechazados por timestamp inválido.
- Timestamp más antiguo y más reciente retenidos.
- Número total de frames en ventana de 6 h.
- Tiempo de procesamiento.
- Tamaño del archivo de salida.
- Errores de codificación/publicación.

## 11. Integración WeeWX

WeeWX no será responsable de procesar la fuente IDEAM.

WeeWX únicamente publicará la salida generada por RustIDEAM.

La integración prevista usará un elemento HTML5 `video` con reproducción automática, silenciosa, en bucle y `playsinline`.

La ubicación final dentro de la skin debe ser después de los gráficos de la estación.

Las rutas reales del contenedor/skin WeeWX deberán verificarse en el host antes de fijarlas.

## 12. Criterios de aceptación

La primera versión se considerará funcional cuando:

1. Descargue correctamente el GIF fuente.
2. Separe sus frames.
3. Reconozca de manera determinista la fecha/hora visible en frames de prueba reales.
4. Rechace de forma explícita frames cuyo timestamp no pueda validarse.
5. No duplique frames entre descargas solapadas.
6. Acumule una ventana real de 6 horas aunque la fuente solo contenga aproximadamente 2 horas.
7. Recupere el histórico retenido después de reiniciar el servicio.
8. Genere una salida reproducible en navegador.
9. Mantenga disponible el último archivo válido ante una falla de actualización.
10. Demuestre mediante medición que la salida seleccionada reduce sustancialmente el tamaño frente a un GIF equivalente de 6 horas.
11. Publique correctamente la animación dentro de WeeWX.

## 13. Datos pendientes de medición

No están confirmados todavía:

- Resolución exacta de los frames actuales.
- Número exacto de frames contenidos en cada descarga.
- Intervalo efectivo entre imágenes de IDEAM.
- Coordenadas exactas del timestamp.
- Fuente/tamaño de caracteres y tolerancias del reconocedor.
- Estrategia óptima de identidad/hash del frame.
- Formato persistente óptimo de los frames retenidos.
- CRF/preset/fps finales para H.264.
- Tamaño real de las salidas GIF/WebP/MP4 para 6 horas.

Estos puntos se resolverán mediante inspección y benchmark sobre muestras reales antes de endurecerlos en la implementación.

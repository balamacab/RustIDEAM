# Arquitectura

```text
IDEAM DUITAMA_C13.gif (~2 h)
            |
            v
      downloader HTTP
            |
            v
       GIF decoder
            |
            +--> identidad/hash
            |
            +--> crop timestamp
                     |
                     v
             template recognizer
                     |
                     v
                timestamp
            |
            v
      deduplicación persistente
            |
            v
      buffer local móvil 6 h
            |
            v
     encoder de salida eficiente
            |
            v
      archivo temporal completo
            |
         rename atómico
            |
            v
      archivo publicado WeeWX
            |
            v
  <video autoplay loop muted playsinline>
```

## Componentes

### 1. Scheduler interno

Daemon único. Ejecuta el ciclo de adquisición cada `source.interval_seconds` y evita solapamiento por diseño.

### 2. Downloader

Descarga la fuente con timeout y límites configurables. Una descarga inválida no modifica la última salida válida.

### 3. Decoder GIF

Recorre los frames de la fuente. La implementación debe minimizar copias y evitar materializar representaciones intermedias innecesarias.

### 4. Identificación y deduplicación

Calcula una identidad determinista por frame. La elección exacta se validará con muestras reales; el objetivo es reconocer el mismo frame aunque reaparezca en distintas descargas solapadas.

### 5. Reconocimiento temporal

Procesa solamente el rectángulo configurado que contiene fecha/hora. No procesa toda la imagen con OCR general.

Pipeline previsto:

```text
crop -> grayscale/binarización -> segmentación -> comparación de plantillas -> parseo -> validación
```

### 6. Store histórico

Persiste frames y timestamps para mantener 6 horas aunque IDEAM retire imágenes antiguas de su GIF de 2 horas.

El store es circular por tiempo, no por cantidad fija de archivos.

### 7. Encoder

Produce la representación publicada. La primera alternativa es MP4/H.264. Animated WebP se conserva como candidato de benchmark, no como salida simultánea obligatoria.

### 8. Publisher

Escribe primero a archivo temporal en el mismo filesystem de la ruta final y hace `rename` al completar con éxito.

### 9. WeeWX

No participa en adquisición, OCR/reconocimiento, retención ni codificación. Solo sirve el archivo terminado dentro de su página.

## Principios

- Sin metadatos de GIF como fuente temporal.
- Sin Tesseract.
- Sin procesos OCR externos.
- Sin PNG intermedios salvo que mediciones demuestren que son necesarios.
- Sin pérdida del último producto válido por una falla de actualización.
- Configuración variable fuera del binario.
- No introducir valores geométricos o de compresión no medidos como defaults pretendidamente reales.

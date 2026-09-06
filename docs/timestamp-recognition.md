# Reconocimiento del timestamp

## Objetivo

Extraer únicamente la fecha/hora visible en el encabezado de cada frame sin usar OCR general ni dependencias externas.

## Estrategia

1. Recortar una región fija configurable.
2. Convertir únicamente ese recorte a una representación adecuada para segmentación.
3. Aplicar binarización/normalización.
4. Segmentar caracteres.
5. Comparar cada carácter contra plantillas conocidas.
6. Reconstruir la cadena temporal.
7. Validarla contra el formato esperado y contra valores calendáricos válidos.

## Conjunto de caracteres

El conjunto definitivo debe derivarse del formato real observado. Para un timestamp tipo `YYYY-MM-DD HH:MM`, normalmente bastan:

`0 1 2 3 4 5 6 7 8 9 - :`

No se debe ampliar el alfabeto sin necesidad.

## Región de interés

Las coordenadas exactas no están confirmadas y deben medirse sobre muestras reales. Deben permanecer en YAML para tolerar futuros desplazamientos del encabezado sin recompilar.

## Confianza

El reconocedor debe producir una medida de similitud/confianza. Un frame por debajo del umbral configurado no debe entrar al histórico silenciosamente.

## Plantillas

Las plantillas deben generarse a partir de frames reales de IDEAM, no de una fuente tipográfica aproximada. De esta forma se conserva la rasterización, borde y antialiasing reales del proveedor.

## Pruebas mínimas

- Reconocimiento correcto de todos los dígitos.
- Reconocimiento de separadores.
- Tolerancia a pequeñas variaciones de compresión GIF.
- Rechazo de crops desplazados o ilegibles.
- Validación de fechas imposibles.
- Ausencia de procesamiento de la región meteorológica completa.

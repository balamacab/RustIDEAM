# Integración con WeeWX

## Responsabilidad

RustIDEAM produce y publica el archivo animado. WeeWX únicamente lo presenta en su portal.

WeeWX no debe descargar la fuente IDEAM ni mantener el histórico satelital.

## HTML previsto

Para salida MP4/H.264:

```html
<video autoplay loop muted playsinline preload="metadata">
  <source src="satellite/duitama_c13_6h.mp4" type="video/mp4">
</video>
```

La ruta exacta debe corresponder al `HTML_ROOT` y al montaje real del contenedor WeeWX en el host.

## Ubicación visual

La animación debe aparecer después de los gráficos de la estación.

La plantilla concreta y el punto de inserción se verificarán contra la skin instalada antes del despliegue.

## Publicación

Se recomienda que RustIDEAM escriba directamente en una ruta del host que WeeWX/servidor web exponga mediante bind mount o volumen de solo lectura desde el lado del consumidor.

No usar `docker cp` periódicamente.

## Fallos

Si una descarga o codificación falla, WeeWX debe seguir sirviendo el último MP4 válido.

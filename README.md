# Correo Studio

Aplicación local que transforma una URL pública en un HTML de email marketing con vista previa y descarga. Extrae nombre, logo (si hay una imagen compatible), imagen promocional, color publicado en la página, titulares, descripción y un enlace de acción. No inventa descuentos ni datos de producto.

## Arranque

```bash
cd /opt/data/projects/email-campaign-builder
python server.py --port 8765
```

Abre `http://127.0.0.1:8765`, introduce la URL del anunciante y pulsa **Crear mi email**. Tras revisar el resultado, usa **Descargar HTML**. Solo necesita Python 3.11+; no requiere paquetes externos.

## Antes de enviar

- Sustituye `{{unsubscribe_url}}` y `{{sender_address}}` por los campos propios de tu ESP. El HTML no incluye asunto ni gestiona envíos.
- Verifica que las imágenes enlazadas sean públicas, estén autorizadas para uso promocional y carguen en el cliente de correo. Las webs con contenido generado por JavaScript, bloqueo antibots o imágenes SVG pueden ofrecer una extracción incompleta.
- Revisa claims, CTA, color y destino, y prueba el HTML en los clientes de correo de tu audiencia. La app usa tablas y CSS inline como base de compatibilidad, pero no garantiza idéntico resultado en todos los clientes.
- La aplicación escucha por defecto solo en `127.0.0.1`. Si publicas el servicio en Internet, añade autenticación, límites de solicitudes y controles de abuso.

## Pruebas

```bash
python -m unittest discover -s tests -v
```

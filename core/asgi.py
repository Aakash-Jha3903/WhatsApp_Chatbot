"""
ASGI config for core project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/asgi/
"""

import os
# # wsgi.py / asgi.py (top of file, before other imports)
# import os
# if os.name == "nt":
#     try:
#         os.add_dll_directory(r"C:\msys64\ucrt64\bin")
#     except FileNotFoundError:
#         # MSYS2 not found; will fail later if WeasyPrint is used
#         pass


from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

application = get_asgi_application()

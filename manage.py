#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys

# # manage.py (very top, before other imports)
# import os
# if os.name == "nt":
#     try:
#         os.add_dll_directory(r"C:\msys64\ucrt64\bin")
#     except FileNotFoundError:
#         pass



def main():
    """Run administrative tasks."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()

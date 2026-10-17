"""Entry point of the Windows desktop app (the installer's NQ-ES Options.exe). Run from source with:  python NQES.py"""
import sys

from desktop.app import main

if __name__ == "__main__":
    sys.exit(main())

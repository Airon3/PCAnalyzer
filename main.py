"""Avvio di PC Analyzer."""
import sys

if sys.version_info < (3, 10):
    sys.exit("PC Analyzer richiede Python 3.10 o superiore (consigliato 3.12).")

from app.gui import main

if __name__ == "__main__":
    main()

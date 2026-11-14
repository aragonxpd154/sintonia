import os, sys
sys.argv = [sys.argv[0], sys.argv[1]]
os.environ.setdefault("PAGINAS", "modulacao")
exec(open("tests/interface/capturas.py").read().replace('"-screen 0 1400x900x24"', ''))

"""Servidor de la imagen de prueba «bootstrap» (ARCHITECTURE §5.11).

- Si el comando de la tarea contiene «app.cli» (tareas migrate), imprime «imagen de prueba: nada que migrar» y sale
  con 0.
- Con cualquier otro comando (api, worker, embedding) sirve en los puertos 8000 y 8080: 200 en GET /v1/health,
  /health y /health/ready; 404 en cualquier otro GET o HEAD; 501 en los demás métodos (POST incluido: http.server
  responde así a lo que no implementa). Termina limpio con SIGTERM (ECS lo envía al detener la tarea).
"""

import json
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PUERTOS = (8000, 8080)
RUTAS_SANAS = {"/v1/health", "/health", "/health/ready"}


class Manejador(BaseHTTPRequestHandler):
    server_version = "imagen-prueba"
    sys_version = ""

    def _responder(self, codigo: int, cuerpo: dict) -> None:
        datos = json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(datos)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(datos)

    def do_GET(self) -> None:  # noqa: N802 — nombre que exige http.server
        ruta = self.path.split("?", 1)[0]
        if ruta in RUTAS_SANAS:
            self._responder(200, {"estado": "ok", "imagen": "bootstrap"})
        else:
            self._responder(404, {"codigo": "NO_ENCONTRADO"})

    do_HEAD = do_GET

    def log_message(self, formato: str, *argumentos) -> None:
        # Sin registrar cada sondeo de salud (cada 30 s); el log solo dice que arrancó.
        pass


def main() -> int:
    argumentos = sys.argv[1:]
    if any("app.cli" in a for a in argumentos):
        print("imagen de prueba: nada que migrar")
        return 0

    servidores = [ThreadingHTTPServer(("0.0.0.0", p), Manejador) for p in PUERTOS]
    for servidor in servidores:
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
    print(f"imagen de prueba: sirviendo en {', '.join(map(str, PUERTOS))} (comando: {argumentos or 'ninguno'})")

    detener = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: detener.set())
    signal.signal(signal.SIGINT, lambda *_: detener.set())
    detener.wait()
    for servidor in servidores:
        servidor.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())

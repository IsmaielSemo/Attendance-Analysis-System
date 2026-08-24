# run_server.py -> Runs the server

from waitress import serve
from main import app
import logging

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
    logging.info("Starting production server on port 80...")

    # 0.0.0.0 tells it to accept connections from ANY computer on the company network
    # Port 80 is the default web port, so users won't have to type a port number in the URL
    serve(app, host='0.0.0.0', port=80, threads=4)


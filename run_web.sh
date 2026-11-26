#!/usr/bin/env bash
# Starts the REQ//PUNK web UI at http://localhost:8000
python -m uvicorn server:app --port 8000

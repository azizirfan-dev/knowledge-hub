#!/bin/bash
# Start FastAPI backend and Next.js frontend concurrently

echo "Starting KnowledgeHub API..."
cd "$(dirname "$0")"

# FastAPI (port 8000)
pip install -q fastapi uvicorn[standard] -r requirements.txt 2>/dev/null
uvicorn api.main:app --reload --port 8000 &
API_PID=$!

echo "Starting KnowledgeHub Frontend..."
cd frontend && npm run dev &
NEXT_PID=$!

echo ""
echo "  API  → http://localhost:8000"
echo "  UI   → http://localhost:3000"
echo ""
echo "Press Ctrl+C to stop both servers."

trap "kill $API_PID $NEXT_PID 2>/dev/null; exit" INT TERM
wait

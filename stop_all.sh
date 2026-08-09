#!/bin/bash
# Stop all fileShare.app processes

echo "🛑 Stopping all fileShare.app processes..."

# Kill Python file server processes (new names)
pkill -f "python.*main.py" 2>/dev/null && echo "✅ Stopped main server processes"
pkill -f "python.*control_panel" 2>/dev/null && echo "✅ Stopped control panel processes"

# Kill legacy processes (for compatibility)
pkill -f "python.*auth_server" 2>/dev/null && echo "✅ Stopped legacy auth_server processes"
pkill -f "python.*simple_gui" 2>/dev/null && echo "✅ Stopped legacy simple_gui processes"
pkill -f "fileshare" 2>/dev/null && echo "✅ Stopped fileshare processes"

# Kill any Python processes on ports 8000 and 9000
lsof -ti:8000 | xargs kill -9 2>/dev/null && echo "✅ Freed port 8000"
lsof -ti:9000 | xargs kill -9 2>/dev/null && echo "✅ Freed port 9000"

# Deactivate virtual environment if active
if [[ "$VIRTUAL_ENV" != "" ]]; then
    deactivate 2>/dev/null && echo "✅ Deactivated virtual environment"
fi

# Clear environment variables
unset VIRTUAL_ENV 2>/dev/null
unset PYTHONPATH 2>/dev/null

echo "🎯 All processes stopped and environments cleared"
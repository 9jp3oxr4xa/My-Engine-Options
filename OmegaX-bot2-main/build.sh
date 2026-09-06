#!/bin/bash
# Nuclear build optimizations for Render

echo "☢️ NUCLEAR BUILD v2.0"

# Clean previous builds
rm -rf __pycache__ *.pyc

# Optimize pip
export PIP_NO_CACHE_DIR=1
export PIP_DISABLE_PIP_VERSION_CHECK=1

# Install with maximum optimization
pip install --no-cache-dir --compile -r requirements.txt

# Pre-compile all Python files
python -m py_compile *.py

# Create state directory structure
mkdir -p data logs cache tmp

# Set permissions
chmod +x nuclear_launcher.py

echo "✅ Build optimized for Python 3.13.4"
#!/bin/bash
# Installation script for Gemini-OpenClaw Gateway

set -e

echo "========================================="
echo "Gemini-OpenClaw Gateway Installation"
echo "========================================="
echo ""

# Check Python version
echo "Checking Python version..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
REQUIRED_VERSION="3.10"

if ! python3 -c "import sys; exit(0 if sys.version_info >= (3, 10) else 1)"; then
    echo "❌ Error: Python 3.10 or higher is required"
    echo "   Current version: $PYTHON_VERSION"
    exit 1
fi

echo "✅ Python version: $PYTHON_VERSION"
echo ""

# Install dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt
echo "✅ Dependencies installed"
echo ""

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo "✅ Created .env file"
    echo ""
    echo "⚠️  IMPORTANT: Edit .env and add your Gemini cookies:"
    echo "   - GEMINI_SECURE_1PSID"
    echo "   - GEMINI_SECURE_1PSIDTS"
    echo ""
    echo "   Get these from gemini.google.com (F12 > Network > Cookie)"
    echo ""
else
    echo "✅ .env file already exists"
    echo ""
fi

# Create temp directory
echo "Creating temp directory..."
mkdir -p /tmp/gemini-gateway
echo "✅ Temp directory created"
echo ""

echo "========================================="
echo "Installation Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Edit .env and add your Gemini cookies"
echo "2. Run: python api_server.py"
echo "3. Test: curl http://localhost:18789/health"
echo ""
echo "For more information, see:"
echo "- QUICKSTART.md - Quick start guide"
echo "- README.md - Full documentation"
echo "- EXAMPLES.md - Usage examples"
echo ""

#!/bin/bash
# Quick Start Script for GitHub Migration
# Run this after uploading files to GitHub

echo "🚀 IHC Fleet Dashboard - GitHub Setup Helper"
echo "============================================="
echo ""

# Check if we're in the right directory
if [ ! -f "README.md" ]; then
    echo "❌ Error: Please run this script from the ihc-fleet-dashboard directory"
    exit 1
fi

echo "✓ Found project files"
echo ""

# Check Python version
echo "Checking Python version..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version)
    echo "✓ $PYTHON_VERSION found"
else
    echo "❌ Python 3 not found. Please install Python 3.11+"
    exit 1
fi
echo ""

# Install dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt
echo ""

# Generate dashboard
echo "Generating dashboard..."
python3 scripts/fleet_dashboard_generator.py
echo ""


# Summary
echo "============================================="
echo "✅ Setup Complete!"
echo "============================================="
echo ""
echo "Next steps:"
echo "1. Open data/index.html in your browser to test locally"
echo "2. Commit and push to GitHub:"
echo "   git add ."
echo "   git commit -m 'Add test dashboard'"
echo "   git push"
echo ""
echo "3. Enable GitHub Pages in repository Settings"
echo "4. Your dashboard will be live at:"
echo "   https://YOUR_USERNAME.github.io/ihc-fleet-dashboard/"
echo ""
echo "📖 See SETUP_GUIDE.md for detailed instructions"
echo ""

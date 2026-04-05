#!/bin/bash
# Setup script for Authica Fabric development environment
# This script configures git hooks and development dependencies

set -e

echo "Setting up Authica Fabric development environment..."

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}Error: pyproject.toml not found. Please run this script from the project root.${NC}"
    exit 1
fi

# Configure git hooks path
echo "Configuring git hooks..."
git config core.hooksPath .githooks
echo -e "${GREEN}✓ Git hooks path set to .githooks${NC}"

# Verify hooks are executable
if [ -f ".githooks/pre-push" ]; then
    chmod +x .githooks/pre-push
    echo -e "${GREEN}✓ Pre-push hook is executable${NC}"
else
    echo -e "${RED}Warning: Pre-push hook not found${NC}"
fi

# Check if uv is installed
if command -v uv &> /dev/null; then
    echo -e "${GREEN}✓ uv is installed${NC}"
    echo "Installing development dependencies with uv..."
    uv pip install -e ".[dev]"
else
    echo -e "${YELLOW}⚠ uv not found. Using pip...${NC}"
    pip install -e ".[dev]"
fi

echo ""
echo -e "${GREEN}Setup complete!${NC}"
echo ""
echo "Development workflow:"
echo "  1. Make your changes"
echo "  2. Run tests: make test"
echo "  3. Run linter: make lint"
echo "  4. Commit your changes"
echo "  5. Tag release: git tag -a v0.1.0 -m 'Release v0.1.0'"
echo "  6. Push: git push origin main --follow-tags"
echo ""
echo "The pre-push hook will:"
echo "  - Validate tag format (must be vX.Y.Z)"
echo "  - Run tests before pushing tags"
echo "  - Run linting before pushing to main"
echo ""
echo "CI will automatically:"
echo "  - Build packages with version from git tag"
echo "  - Publish to PyPI when a tag is pushed"

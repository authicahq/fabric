#!/bin/bash
# Initial push script for Authica Fabric
# This script sets up the remote and pushes the initial commit and v0.1.0 tag

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "Authica Fabric - Initial Push Script"
echo "===================================="
echo ""

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}Error: pyproject.toml not found. Please run this script from the project root.${NC}"
    exit 1
fi

# Check if git remote exists
if git remote get-url origin &>/dev/null; then
    REMOTE_URL=$(git remote get-url origin)
    echo -e "${GREEN}Remote 'origin' already configured: $REMOTE_URL${NC}"
else
    echo -e "${YELLOW}Remote 'origin' not configured.${NC}"
    echo ""
    echo "Please create the repository on GitHub first:"
    echo "  https://github.com/new"
    echo ""
    echo "Repository name: fabric"
    echo "Owner: authicahq (or your organization)"
    echo ""
    read -p "Enter the GitHub repository URL (e.g., git@github.com:authicahq/fabric.git): " REPO_URL
    
    if [ -z "$REPO_URL" ]; then
        echo -e "${RED}Error: No URL provided. Exiting.${NC}"
        exit 1
    fi
    
    git remote add origin "$REPO_URL"
    echo -e "${GREEN}✓ Remote 'origin' added: $REPO_URL${NC}"
fi

echo ""
echo "Repository status:"
echo "  Branch: $(git branch --show-current)"
echo "  Commits: $(git rev-list --count HEAD)"
echo "  Tags: $(git tag -l | wc -l)"
git tag -l | sed 's/^/    - /'

echo ""
echo -e "${YELLOW}Ready to push.${NC}"
echo ""
echo "This will:"
echo "  1. Push the main branch to origin"
echo "  2. Push the v0.1.0 tag (triggers release workflow)"
echo ""
read -p "Do you want to proceed? (y/N): " CONFIRM

if [[ "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo ""
    echo "Pushing to origin..."
    
    # Push main branch
    git push -u origin main
    echo -e "${GREEN}✓ Branch pushed${NC}"
    
    # Push tags
    git push origin --tags
    echo -e "${GREEN}✓ Tags pushed${NC}"
    
    echo ""
    echo -e "${GREEN}====================================${NC}"
    echo -e "${GREEN}Initial push complete!${NC}"
    echo -e "${GREEN}====================================${NC}"
    echo ""
    echo "What happens next:"
    echo "  1. GitHub Actions will run CI (test, lint, build)"
    echo "  2. Since v0.1.0 tag was pushed, the release workflow will:"
    echo "     - Build standalone executables for Linux, macOS, Windows"
    echo "     - Create GitHub release with executables"
    echo ""
    echo "Note: PyPI publishing is currently disabled."
    echo "      To enable, uncomment the publish-pypi job in .github/workflows/ci.yml"
    echo ""
    echo "Monitor progress at:"
    echo "  https://github.com/$(git remote get-url origin | sed 's/.*github.com[:/]//;s/.git$//')/actions"
else
    echo ""
    echo "Push cancelled. To push manually:"
    echo "  git remote add origin <your-repo-url>"
    echo "  git push -u origin main"
    echo "  git push origin --tags"
fi

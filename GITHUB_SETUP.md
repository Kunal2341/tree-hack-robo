# GitHub Setup

## Create the repository

1. Go to [github.com/new](https://github.com/new)
2. Name it `TreeHackNow` (or your preferred name)
3. **Do not** initialize with README, .gitignore, or license (we already have these)
4. Click **Create repository**

## Push your code

```bash
cd /Users/kunalaneja/TreeHackNow

# Add the remote (replace YOUR_USERNAME with your GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/TreeHackNow.git

# Push
git push -u origin main
```

## Optional: Use GitHub CLI

If you install [GitHub CLI](https://cli.github.com/) (`brew install gh`):

```bash
gh auth login
gh repo create TreeHackNow --source=. --push
```

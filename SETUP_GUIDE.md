# 🚀 GitHub Migration Guide
## IHC Fleet Dashboard - Complete Setup Instructions

**Time Required:** 15 minutes  
**Difficulty:** Easy  
**Prerequisites:** GitHub account

---

## 📦 Package Contents

You have everything you need in this folder:

```
github-migration-package/
├── .github/workflows/          ← GitHub Actions (automation)
├── scripts/                    ← All your Python scripts
├── data/                       ← Put your CSV files here
├── docs/                       ← Documentation
├── public/                     ← Dashboard output (auto-generated)
├── .gitignore                  ← Git configuration
├── requirements.txt            ← Python dependencies
└── README.md                   ← Project documentation
```

---

## ⚡ Quick Setup (3 Steps)

### Step 1: Create GitHub Repository (5 min)

1. **Go to GitHub.com** and log in
2. **Click the `+` icon** (top right) → "New repository"
3. **Fill in:**
   - Repository name: `ihc-fleet-dashboard`
   - Description: "IHC Aviation Fleet Maintenance Dashboard"
   - Visibility: **Private** (recommended)
   - ✅ Add a README file
4. **Click "Create repository"**

### Step 2: Upload Files (5 min)

**Option A: Via GitHub Web Interface (Easiest)**

1. **In your new repository**, click "Add file" → "Upload files"
2. **Drag all files** from `github-migration-package` folder
3. **Important:** Make sure you include the `.github` folder (it has the workflows!)
4. **Commit message:** "Initial commit - Fleet Dashboard"
5. **Click "Commit changes"**

**Option B: Via Git Command Line**

```bash
# Navigate to the migration package folder
cd github-migration-package

# Initialize git
git init
git add .
git commit -m "Initial commit"

# Connect to GitHub (replace YOUR_USERNAME)
git remote add origin https://github.com/YOUR_USERNAME/ihc-fleet-dashboard.git
git branch -M main
git push -u origin main
```

### Step 3: Configure GitHub (5 min)

#### A. Enable GitHub Pages

1. Go to repository **Settings** → **Pages** (left sidebar)
2. Under "Build and deployment":
   - Source: **GitHub Actions**
3. **Save**

Your dashboard will be at: `https://YOUR_USERNAME.github.io/ihc-fleet-dashboard/`

#### B. Add SkyRouter Credentials (if you have API access)

1. Go to **Settings** → **Secrets and variables** → **Actions**
2. Click "New repository secret"
3. Add two secrets:
   - Name: `SKYROUTER_USER`, Value: your username
   - Name: `SKYROUTER_PASS`, Value: your password

#### C. Update Configuration

Edit `scripts/fleet_dashboard_generator.py`:
- Change `ONEDRIVE_FOLDER` to `data` (line 22)
  ```python
  OUTPUT_FOLDER = "data"  # Changed from OneDrive path
  ```

Do the same for:
- `scripts/base_assignment_generator.py` (line 13)
- `scripts/skyrouter_api_fetcher.py` (line 15)

---

## 📥 Daily Usage Workflow

### Uploading New CSV Files

**Option 1: GitHub Web Interface**
1. Go to your repository
2. Navigate to `data/` folder
3. Click "Add file" → "Upload files"
4. Upload your `Due-List_Latest.csv` and `Due-List_BIG_WEEKLY.csv`
5. Commit → This automatically triggers dashboard generation!

**Option 2: Git Command Line**
```bash
cd ihc-fleet-dashboard
cp "path/to/Due-List_Latest.csv" data/
git add data/*.csv
git commit -m "Update CSV data"
git push
```

The dashboard updates automatically within 2 minutes!

---

## 🤖 Automation Details

### What Runs Automatically:

**Daily at 8 AM UTC (1 AM MST):**
1. Fetch SkyRouter positions
2. Calculate base assignments
3. Generate dashboard
4. Deploy to GitHub Pages

**When you upload CSV files:**
1. Dashboard regenerates
2. Deploys to GitHub Pages

### Manual Triggers:

Go to **Actions** tab → **Update Fleet Dashboard** → **Run workflow**

---

## 🧪 Testing the Setup

### Generate Test Dashboard

1. **Upload test data:**
   ```bash
   cd ihc-fleet-dashboard
   python scripts/create_test_data.py
   ```

2. **Generate dashboard:**
   ```bash
   python scripts/fleet_dashboard_generator.py
   ```

3. **Check output:**
   - File created: `data/fleet_dashboard.html`
   - Open in browser to verify

4. **Commit and push:**
   ```bash
   git add data/fleet_dashboard.html public/index.html
   git commit -m "Test dashboard"
   git push
   ```

5. **Check GitHub Pages:**
   - Wait 2 minutes
   - Visit: `https://YOUR_USERNAME.github.io/ihc-fleet-dashboard/`

---

## 📝 Updating Your Workflow

### Adding CSV Files

Put CSV files in the `data/` folder:
```
data/
├── Due-List_Latest.csv       ← Daily export from CAMP
├── Due-List_BIG_WEEKLY.csv   ← Weekly export from CAMP
```

### Running Locally (Optional)

```bash
# Install dependencies
pip install -r requirements.txt

# Generate dashboard locally
python scripts/fleet_dashboard_generator.py

# View dashboard
open data/fleet_dashboard.html  # Mac
start data/fleet_dashboard.html  # Windows
```

---

## 🔒 Security Best Practices

### ✅ DO:
- Keep repository **private**
- Use GitHub Secrets for credentials
- Review who has access regularly
- Use `.gitignore` (already configured)

### ❌ DON'T:
- Commit CSV files with sensitive data (optional)
- Hard-code passwords in scripts
- Make repository public if data is sensitive
- Share credentials in commit messages

---

## 🐛 Troubleshooting

### Dashboard not updating?

**Check Actions tab:**
1. Go to repository → **Actions**
2. Look for failed workflows (red X)
3. Click on the workflow → View logs
4. Fix the error and try again

**Common issues:**
- Missing secrets → Add them in Settings
- CSV files not uploaded → Upload to `data/` folder
- Python errors → Check the logs for details

### SkyRouter not working?

1. Verify credentials in Secrets
2. Check if API access is enabled with Blue Sky Network
3. Try test data: `python scripts/create_test_data.py`

### GitHub Pages not deploying?

1. Check Settings → Pages is enabled
2. Verify `public/index.html` exists
3. Check deploy workflow succeeded in Actions
4. Wait 2-3 minutes after push

---

## 📊 Monitoring

### View Workflow Runs

**Actions tab shows:**
- ✅ Successful runs (green check)
- ❌ Failed runs (red X)
- ⏱️ In progress (yellow dot)

**Click any run to see:**
- Detailed logs
- Error messages
- Execution time
- Artifacts

### Email Notifications

GitHub can email you when workflows fail:
1. Click your profile → **Settings**
2. **Notifications** → **Actions**
3. Configure failure notifications

---

## 🎯 Next Steps

### After Initial Setup:

1. **Test everything:**
   - Upload test CSV
   - Verify dashboard generates
   - Check GitHub Pages deployment

2. **Schedule regular uploads:**
   - Manual: Upload CSVs when you get them
   - Automated: Set up CAMP scraper to upload via GitHub API

3. **Share with team:**
   - Add collaborators in Settings → Collaborators
   - Share dashboard URL
   - Train team on usage

4. **Monitor and maintain:**
   - Check Actions tab weekly
   - Update dependencies periodically
   - Review access controls

---

## 📞 Getting Help

### Resources:
- GitHub Actions docs: https://docs.github.com/actions
- Repository Issues tab: Create an issue for problems
- Review workflow logs for debugging

### Quick Fixes:

| Problem | Solution |
|---------|----------|
| Dashboard blank | Check CSV files uploaded |
| 404 error | Enable GitHub Pages in Settings |
| Automation not running | Check Secrets are configured |
| Python errors | Review requirements.txt installed |

---

## ✅ Setup Checklist

- [ ] GitHub repository created
- [ ] All files uploaded
- [ ] GitHub Pages enabled
- [ ] Secrets configured (if using SkyRouter)
- [ ] Test dashboard generated
- [ ] Dashboard accessible at GitHub Pages URL
- [ ] Automated workflow tested
- [ ] Team members added
- [ ] Documentation reviewed

---

**🎉 Congratulations!** Your dashboard is now running on GitHub with full automation!

**Dashboard URL:** `https://YOUR_USERNAME.github.io/ihc-fleet-dashboard/`

---

**Questions?** Create an issue in the repository or check the troubleshooting section above.

# GitHub Publication Checklist

Use this before publishing the repository to a private GitHub repo for team review.

## Safety Checklist

- [ ] No tenancy OCIDs
- [ ] No compartment OCIDs
- [ ] No user OCIDs
- [ ] No instance OCIDs
- [ ] No dynamic group OCIDs
- [ ] No subnet or VCN OCIDs
- [ ] No secrets
- [ ] No private key material
- [ ] No session tokens
- [ ] No customer IPs
- [ ] No internal hostnames
- [ ] No personal email addresses
- [ ] No personal file paths containing sensitive information
- [ ] No environment-specific values in source
- [ ] `.gitignore` present
- [ ] `examples/config.example.env` present
- [ ] Secret scan passes
- [ ] Tests pass
- [ ] README works from a clean checkout
- [ ] Screenshots are sanitized
- [ ] Team quickstart works

## Required Checks

PowerShell:

```powershell
.\scripts\check-secrets.ps1
python -m unittest discover -s tests -v
python -m compileall src cli tests
```

Bash:

```bash
bash scripts/check-secrets.sh
python -m unittest discover -s tests -v
python -m compileall src cli tests
```

## GitHub Commands

From the repository root:

```bash
git init
git add .
git status
git commit -m "Prepare OCI Capacity Preflight team review"
git branch -M main
git remote add origin <PRIVATE_REPO_URL>
git push -u origin main
```

## Verify The First Commit

Before pushing:

```bash
git grep -n "ocid1\\." HEAD
git grep -n "-----BEGIN" HEAD
git grep -n "fingerprint\\s*=" HEAD
git grep -n "key_file\\s*=" HEAD
git grep -n "session[_-]\\?token" HEAD
git grep -n "ssh-key" HEAD
```

Each command should return no findings. If any command returns a match, remove or replace the value before pushing.

Also review staged files:

```bash
git status
git diff --cached --stat
git diff --cached
```

Do not push if any real OCID, credential path, key material, IP address, hostname, username, email address, token, or screenshot with tenancy data is present.

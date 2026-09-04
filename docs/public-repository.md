# Public Repository Checklist

Run the repository safety gate before every release or visibility change:

```bash
python scripts/check_public_repo_safety.py
```

The gate rejects tracked local state, credential-shaped filenames, and high-confidence
credential patterns in every reachable Git commit. It does not replace rotating a
credential that was ever intentionally shared outside the repository.

Before changing repository visibility in GitHub, configure these repository settings:

1. In **Settings > Actions > General**, set the default workflow permission to
   **Read repository contents and packages permissions**.
2. Disable **Send write tokens to workflows from pull requests**.
3. Require approval for Actions runs originating from outside collaborators.
4. In **Settings > Branches**, protect `main` and require the `ci` workflow before
   changes are merged.
5. In **Settings > Security**, enable Dependabot alerts and secret scanning.

Repository and environment secrets remain private when the repository is public. Keep
all OAuth JSON, browser cookies, API keys, and Colab credentials in GitHub Secrets only.

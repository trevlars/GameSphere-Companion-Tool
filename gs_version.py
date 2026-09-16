"""Single version string for CLI, GUI, and GitHub auto-update."""

__version__ = "1.5.6"
GITHUB_OWNER = "trevlars"
GITHUB_REPO = "Gamesphere-Import-Tool"
GITHUB_RELEASES_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
)
GITHUB_LATEST_API = GITHUB_RELEASES_API + "/latest"
GITHUB_RELEASES_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

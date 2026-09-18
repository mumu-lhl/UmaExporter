import os
import sys
import platform
import tarfile
import zipfile
import urllib.request
import json
import shutil

# GitHub Repository for AssetStudioCat
REPO = "mumu-lhl/AssetStudioCat"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DEST_DIR = "as_cli"
CLI_NAME = "AssetStudioCatCLI"


def get_platform_asset_name():
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        return "AssetStudioCat-CLI-{version}-linux-x64.tar.gz"
    elif system == "darwin":
        if machine in ("arm64", "aarch64"):
            return "AssetStudioCat-CLI-{version}-osx-arm64.tar.gz"
        else:
            return "AssetStudioCat-CLI-{version}-osx-x64.tar.gz"
    elif system == "windows":
        return "AssetStudioCat-CLI-{version}-win-x64.zip"
    else:
        print(f"Unsupported system: {system}")
        sys.exit(1)


def main():
    if not os.path.exists(DEST_DIR):
        os.makedirs(DEST_DIR)

    print(f"Fetching latest release info from {API_URL}...")
    try:
        req = urllib.request.Request(API_URL)
        req.add_header("User-Agent", "UmaExporter-Setup-Script")

        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            print("Using GitHub Token for authentication...")
            req.add_header("Authorization", f"token {token}")

        with urllib.request.urlopen(req) as response:
            data = json.loads(response.read().decode())
            tag_name = data.get("tag_name", "")
            # Strip leading 'v' for version string used in filenames
            version = tag_name.lstrip("v")
            assets = data.get("assets", [])

            asset_name_template = get_platform_asset_name()
            asset_name = asset_name_template.format(version=version)
            print(f"Targeting asset: {asset_name}")

            download_url = next(
                (a["browser_download_url"] for a in assets if a["name"] == asset_name),
                None,
            )

            if not download_url:
                print(f"Could not find {asset_name} in the latest release.")
                print(f"Found assets: {[a['name'] for a in assets]}")
                sys.exit(1)

            print(f"Downloading {asset_name} from {download_url}...")
            archive_path = os.path.join(DEST_DIR, asset_name)

            download_req = urllib.request.Request(download_url)
            download_req.add_header("User-Agent", "UmaExporter-Setup-Script")
            if token:
                download_req.add_header("Authorization", f"token {token}")

            with (
                urllib.request.urlopen(download_req) as dl_response,
                open(archive_path, "wb") as out_file,
            ):
                shutil.copyfileobj(dl_response, out_file)

            print(f"Extracting to {DEST_DIR}...")
            if archive_path.endswith(".tar.gz") or archive_path.endswith(".tgz"):
                with tarfile.open(archive_path, "r:gz") as tar_ref:
                    tar_ref.extractall(DEST_DIR)
            else:
                with zipfile.ZipFile(archive_path, "r") as zip_ref:
                    zip_ref.extractall(DEST_DIR)

            os.remove(archive_path)

            # Set executable permissions on Linux/macOS
            cli_name = CLI_NAME
            if platform.system().lower() == "windows":
                cli_name += ".exe"

            cli_path = os.path.join(DEST_DIR, cli_name)
            if platform.system().lower() != "windows":
                if os.path.exists(cli_path):
                    os.chmod(cli_path, 0o755)
                    print(f"Permissions set for {cli_path}")

            if not os.path.exists(cli_path):
                print(f"Warning: {cli_name} not found in {DEST_DIR}")

            print("Asset Studio CLI setup complete.")
    except Exception as e:
        print(f"Error during setup: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

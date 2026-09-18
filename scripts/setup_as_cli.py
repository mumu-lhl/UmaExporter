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


def get_platform_suffix():
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        if machine in ("arm64", "aarch64"):
            return "linux-arm64.tar.gz"
        return "linux-x64.tar.gz"
    elif system == "darwin":
        if machine in ("arm64", "aarch64"):
            return "osx-arm64.tar.gz"
        else:
            return "osx-x64.tar.gz"
    elif system == "windows":
        if machine in ("arm64", "aarch64"):
            return "win-arm64.zip"
        return "win-x64.zip"
    else:
        print(f"Unsupported system: {system}")
        sys.exit(1)


def main():
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
            assets = data.get("assets", [])

            target_suffix = get_platform_suffix()
            prefix = "AssetStudioCat-CLI-"

            # Search for matching asset with prefix and platform suffix
            matched_asset = next(
                (
                    a
                    for a in assets
                    if a["name"].startswith(prefix) and a["name"].endswith(target_suffix)
                ),
                None,
            )

            # Fallback if specific arch not found (e.g. linux-arm64 fallback to linux-x64)
            if not matched_asset and "arm64" in target_suffix:
                fallback_suffix = target_suffix.replace("arm64", "x64")
                matched_asset = next(
                    (
                        a
                        for a in assets
                        if a["name"].startswith(prefix) and a["name"].endswith(fallback_suffix)
                    ),
                    None,
                )

            if not matched_asset:
                print(f"Could not find a matching asset for suffix '{target_suffix}' in the latest release.")
                print(f"Found assets: {[a['name'] for a in assets]}")
                sys.exit(1)

            asset_name = matched_asset["name"]
            download_url = matched_asset["browser_download_url"]
            print(f"Targeting asset: {asset_name}")

            import tempfile

            with tempfile.TemporaryDirectory() as tmp_dir:
                archive_path = os.path.join(tmp_dir, asset_name)
                print(f"Downloading {asset_name} from {download_url}...")

                download_req = urllib.request.Request(download_url)
                download_req.add_header("User-Agent", "UmaExporter-Setup-Script")
                if token:
                    download_req.add_header("Authorization", f"token {token}")

                with (
                    urllib.request.urlopen(download_req) as dl_response,
                    open(archive_path, "wb") as out_file,
                ):
                    shutil.copyfileobj(dl_response, out_file)

                print(f"Preparing destination directory: {DEST_DIR}...")
                if os.path.exists(DEST_DIR):
                    shutil.rmtree(DEST_DIR)
                os.makedirs(DEST_DIR, exist_ok=True)

                print(f"Extracting to {DEST_DIR}...")
                if archive_path.endswith(".tar.gz") or archive_path.endswith(".tgz"):
                    with tarfile.open(archive_path, "r:gz") as tar_ref:
                        if hasattr(tarfile, "data_filter"):
                            tar_ref.extractall(DEST_DIR, filter="tar")
                        else:
                            tar_ref.extractall(DEST_DIR)
                else:
                    with zipfile.ZipFile(archive_path, "r") as zip_ref:
                        zip_ref.extractall(DEST_DIR)

                cli_name = CLI_NAME + (".exe" if platform.system().lower() == "windows" else "")
                cli_path = os.path.join(DEST_DIR, cli_name)

                # Move contents if they were extracted into a single subfolder
                if not os.path.exists(cli_path):
                    subdirs = [
                        d for d in os.listdir(DEST_DIR) if os.path.isdir(os.path.join(DEST_DIR, d))
                    ]
                    if len(subdirs) == 1:
                        subfolder = os.path.join(DEST_DIR, subdirs[0])
                        if os.path.exists(os.path.join(subfolder, cli_name)):
                            print(f"Moving contents from {subfolder} to {DEST_DIR}...")
                            for item in os.listdir(subfolder):
                                shutil.move(
                                    os.path.join(subfolder, item), os.path.join(DEST_DIR, item)
                                )
                            os.rmdir(subfolder)

                # Set executable permissions on Linux/macOS
                if platform.system().lower() != "windows":
                    if os.path.exists(cli_path):
                        os.chmod(cli_path, 0o755)
                        print(f"Permissions set for {cli_path}")

                if not os.path.exists(cli_path):
                    print(f"Error: {cli_name} not found in {DEST_DIR}")
                    sys.exit(1)

                print("Asset Studio CLI setup complete.")
    except Exception as e:
        print(f"Error during setup: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

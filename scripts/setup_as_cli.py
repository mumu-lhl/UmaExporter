import os
import sys
import platform
import zipfile
import urllib.request
import json
import shutil

# GitHub Repository for AssetStudioMod (aelurum's version is common for these names)
REPO = "aelurum/AssetStudio"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DEST_DIR = "as_cli"


def get_platform_asset_name():
    system = platform.system().lower()
    if system == "linux":
        return "AssetStudioModCLI_net9_linux64.zip"
    elif system == "darwin":
        return "AssetStudioModCLI_net9_mac64.zip"
    elif system == "windows":
        return "AssetStudioModCLI_net9_win64.zip"
    else:
        print(f"Unsupported system: {system}")
        sys.exit(1)


def main():
    if not os.path.exists(DEST_DIR):
        os.makedirs(DEST_DIR)

    asset_name = get_platform_asset_name()
    print(f"Targeting asset: {asset_name}")

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
            download_url = next(
                (a["browser_download_url"] for a in assets if a["name"] == asset_name),
                None,
            )

            if not download_url:
                print(f"Could not find {asset_name} in the latest release.")
                # Fallback if names differ slightly (e.g. without _net9)
                print("Checking for alternatives...")
                alt_name = asset_name.replace("_net9", "")
                download_url = next(
                    (
                        a["browser_download_url"]
                        for a in assets
                        if a["name"] == alt_name
                    ),
                    None,
                )
                if download_url:
                    asset_name = alt_name
                else:
                    print(f"Found assets: {[a['name'] for a in assets]}")
                    sys.exit(1)

            print(f"Downloading {asset_name} from {download_url}...")
            zip_path = os.path.join(DEST_DIR, asset_name)

            download_req = urllib.request.Request(download_url)
            download_req.add_header("User-Agent", "UmaExporter-Setup-Script")
            if token:
                download_req.add_header("Authorization", f"token {token}")

            with (
                urllib.request.urlopen(download_req) as dl_response,
                open(zip_path, "wb") as out_file,
            ):
                shutil.copyfileobj(dl_response, out_file)

            print(f"Extracting to {DEST_DIR}...")
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                zip_ref.extractall(DEST_DIR)

            os.remove(zip_path)

            # Move contents if they are in a subfolder (common in GitHub release zips)
            subdirs = [
                d
                for d in os.listdir(DEST_DIR)
                if os.path.isdir(os.path.join(DEST_DIR, d))
            ]
            if len(subdirs) == 1 and ("AssetStudioModCLI" in subdirs[0]):
                subfolder = os.path.join(DEST_DIR, subdirs[0])
                print(f"Moving contents from {subfolder} to {DEST_DIR}...")
                for item in os.listdir(subfolder):
                    shutil.move(
                        os.path.join(subfolder, item), os.path.join(DEST_DIR, item)
                    )
                os.rmdir(subfolder)

            # Set executable permissions on Linux/macOS
            cli_name = "AssetStudioModCLI"
            if platform.system().lower() == "windows":
                cli_name += ".exe"

            cli_path = os.path.join(DEST_DIR, cli_name)
            if platform.system().lower() != "windows":
                if os.path.exists(cli_path):
                    os.chmod(cli_path, 0o755)
                    print(f"Permissions set for {cli_path}")

            if not os.path.exists(cli_path):
                # Support checking both with/without exe in logs to be safe
                print(f"Warning: {cli_name} not found in {DEST_DIR}")

            print("Asset Studio CLI setup complete.")
    except Exception as e:
        print(f"Error during setup: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

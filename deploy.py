import argparse
import os
import shutil
import subprocess
import sys


def run_tests():
    """Run the test suite and return True if all tests pass."""
    print("\n=== Running tests ===")
    result = subprocess.run(
        ["python", "-m", "pytest", "-v"], capture_output=True, text=True
    )

    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)

    if result.returncode != 0:
        print("\n[ERROR] Tests failed. Aborting deployment.", file=sys.stderr)
        return False

    print("\n[OK] All tests passed!")
    return True


def build_package():
    """Build the Python package."""
    print("\n=== Building package ===")
    # Remove build directories in a cross-platform way
    for dir_path in ["dist", "build"]:
        if os.path.exists(dir_path):
            shutil.rmtree(dir_path)
    # Remove egg-info files
    for egg_info in os.listdir("src"):
        if egg_info.endswith(".egg-info"):
            shutil.rmtree(os.path.join("src", egg_info))

    subprocess.run([sys.executable, "-m", "build"], check=True)


def check_package():
    """Check the built package."""
    print("\n=== Checking package ===")
    subprocess.run(["python", "-m", "twine", "check", "dist/*"], check=True)


def main() -> None:
    """Bump the version, test and build. Publishing is left to CI."""
    parser = argparse.ArgumentParser(description="Bump, test and build the package")
    parser.add_argument(
        "bump",
        nargs="?",
        choices=["patch", "minor", "major"],
        help="Run bumpversion before deployment",
    )
    args = parser.parse_args()

    if args.bump:
        subprocess.run([sys.executable, "-m", "bumpversion", args.bump], check=True)

    # Run tests first
    if not run_tests():
        sys.exit(1)

    # Proceed with deployment if tests pass
    build_package()
    check_package()

    # Publishing is the release workflow's job: it triggers on the version tag
    # and uploads to PyPI itself. Uploading here too made that job fail with a
    # 400 from PyPI, because the files were already there.
    print("\n[SUCCESS] Build completed successfully!")
    print("Push the branch and the version tag to publish:")
    print("    git push && git push --tags")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Error during deployment: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[CANCELLED] Deployment cancelled by user.")
        sys.exit(1)

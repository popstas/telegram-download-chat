import os
import subprocess
import sys
import shutil

def run_tests():
    """Run the test suite and return True if all tests pass."""
    print("\n=== Running tests ===")
    result = subprocess.run(
        ["python", "-m", "pytest", "-v"],
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    
    if result.returncode != 0:
        print("\n❌ Tests failed. Aborting deployment.", file=sys.stderr)
        return False
    
    print("\n✅ All tests passed!")
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
        if egg_info.endswith('.egg-info'):
            shutil.rmtree(os.path.join("src", egg_info))
    
    subprocess.run([sys.executable, "-m", "build"], check=True)

def check_package():
    """Check the built package."""
    print("\n=== Checking package ===")
    subprocess.run(["python", "-m", "twine", "check", "dist/*"], check=True)

def upload_package():
    """Upload the package to PyPI."""
    print("\n=== Uploading to PyPI ===")
    subprocess.run(["python", "-m", "twine", "upload", "dist/*"], check=True)

def main():
    # Run tests first
    if not run_tests():
        sys.exit(1)
    
    # Proceed with deployment if tests pass
    build_package()
    check_package()
    upload_package()
    
    print("\n🚀 Deployment completed successfully!")

if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Error during deployment: {e}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n🚫 Deployment cancelled by user.")
        sys.exit(1)

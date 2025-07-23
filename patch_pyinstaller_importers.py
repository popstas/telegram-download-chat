import os
import sys


def apply_patch():
    """Apply patch to PyInstaller's pyimod02_importers.py to suppress pkg_resources warning."""
    try:
        import PyInstaller

        pyinstaller_path = os.path.dirname(os.path.abspath(PyInstaller.__file__))
        target_file = os.path.join(pyinstaller_path, "loader", "pyimod02_importers.py")

        # Read the original file
        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()

        # Check if patch is already applied
        if "warnings.filterwarnings" in content:
            print("Patch already applied.")
            return

        # Find the right place to insert our warning filter
        insert_point = content.find("import ")
        if insert_point == -1:
            print("Could not find import statement in pyimod02_importers.py")
            return

        # Add our warning filter after the imports
        new_content = (
            content[:insert_point]
            + "import warnings\n"
            + "warnings.filterwarnings(\n"
            + "    'ignore', 'pkg_resources is deprecated as an API', 'UserWarning', 'pyimod02_importers'\n"
            + ")\n\n"
            + content[insert_point:]
        )

        # Write the modified content back
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(new_content)

        print("Successfully patched PyInstaller's pyimod02_importers.py")

    except Exception as e:
        print(f"Error applying patch: {e}")


if __name__ == "__main__":
    apply_patch()

import os

from PIL import Image


def convert_png_to_ico(png_path, ico_path):
    """
    Convert a PNG file to ICO format with multiple sizes.
    This is a simple implementation that creates a single 256x256 icon
    as it's the most commonly used size for modern Windows applications.
    """
    try:
        # Open the image
        img = Image.open(png_path)

        # Convert to RGBA if needed
        if img.mode != "RGBA":
            img = img.convert("RGBA")

        # Resize to 256x256 (standard size for modern Windows icons)
        img = img.resize((256, 256), Image.Resampling.LANCZOS)

        # Save as ICO
        img.save(ico_path, format="ICO", sizes=[(256, 256)])
        print(f"Successfully created ICO file at: {ico_path}")

    except Exception as e:
        print(f"Error creating ICO file: {e}")
        # Fallback: Create a basic ICO file using the original image
        try:
            img = Image.open(png_path)
            img.save(ico_path, format="ICO")
            print(f"Created basic ICO file at: {ico_path}")
        except Exception as e2:
            print(f"Failed to create ICO file: {e2}")


if __name__ == "__main__":
    png_path = os.path.join("assets", "icon.png")
    ico_path = os.path.join("assets", "icon.ico")

    # Create assets directory if it doesn't exist
    os.makedirs("assets", exist_ok=True)

    convert_png_to_ico(png_path, ico_path)

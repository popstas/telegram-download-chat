from PIL import Image, ImageDraw, ImageFont
import os

# Create a simple icon
img = Image.new('RGBA', (256, 256), (255, 255, 255, 0))
draw = ImageDraw.Draw(img)

# Draw a simple telegram logo (just a blue circle with a paper plane)
draw.ellipse((20, 20, 236, 236), fill=(0, 136, 204, 255))
# Draw a paper plane shape
draw.polygon([(180, 100), (100, 180), (120, 220), (160, 140), (80, 200)], 
             fill=(255, 255, 255, 255))

# Ensure assets directory exists
os.makedirs('assets', exist_ok=True)
img.save('assets/icon.png')

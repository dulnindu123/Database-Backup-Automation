"""
Enterprise Database Cloud Backup Automation - Application Icon Generator
=============================================================================
Author: Dulnindu Saranga
Utility: Programmatic multi-resolution icon builder using Pillow (PIL)

Generates:
1. app_icon.png: High-resolution (256x256) master graphic with transparency.
2. app_icon.ico: Multi-resolution Windows application icon container embedding:
   - 256x256 (High-DPI / Windows 11 Desktop large icons)
   - 128x128 (Windows File Explorer large view)
   - 64x64   (Taskbar preview)
   - 48x48   (Desktop standard)
   - 32x32   (Window titlebar & Alt+Tab)
   - 16x16   (System tray & small view)
"""

import os
from PIL import Image, ImageDraw


def create_backup_icon(output_dir):
    """
    Renders vector-style shapes for the cloud database backup motif and outputs
    both PNG and multi-resolution ICO formats into the target directory.
    """
    size = (256, 256)
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # 1. Outer rounded shield background with vibrant modern gradient feel
    draw.ellipse([16, 16, 240, 240], fill=(24, 119, 242))  # Modern Royal Blue
    draw.ellipse([26, 26, 230, 230], fill=(20, 95, 200))   # Deep Inner Ring
    
    # 2. Cloud shape (representing Cloud Storage / Google Drive)
    cloud_color = (255, 255, 255)
    draw.ellipse([65, 110, 125, 170], fill=cloud_color)
    draw.ellipse([100, 80, 160, 140], fill=cloud_color)
    draw.ellipse([140, 105, 195, 165], fill=cloud_color)
    draw.rectangle([90, 125, 175, 165], fill=cloud_color)
    
    # 3. Database cylinder shape (representing Microsoft SQL Server)
    db_color = (30, 144, 255)
    db_top_color = (135, 206, 250)
    
    # Cylinder bottom disk
    draw.chord([105, 160, 155, 185], start=0, end=180, fill=db_color)
    # Cylinder body
    draw.rectangle([105, 145, 155, 172], fill=db_color)
    # Cylinder top ellipse cap
    draw.ellipse([105, 135, 155, 155], fill=db_top_color)
    
    # 4. Upward sync arrow (representing Cloud Sync & Disaster Recovery)
    arrow_color = (255, 215, 0)  # Gold
    draw.polygon([(130, 95), (115, 120), (145, 120)], fill=arrow_color)
    draw.rectangle([125, 120, 135, 138], fill=arrow_color)
    
    ico_path = os.path.join(output_dir, "app_icon.ico")
    png_path = os.path.join(output_dir, "app_icon.png")
    
    # Save master PNG
    image.save(png_path, format="PNG")
    
    # Save multi-size ICO container for Windows OS
    image.save(
        ico_path, 
        format="ICO", 
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    )
    print(f"Generated icons:\n  {ico_path}\n  {png_path}")


if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    create_backup_icon(current_dir)

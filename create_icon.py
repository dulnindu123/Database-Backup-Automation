import os
from PIL import Image, ImageDraw

def create_backup_icon(output_dir):
    size = (256, 256)
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Outer circle / rounded shield background with vibrant modern gradient feel
    draw.ellipse([16, 16, 240, 240], fill=(24, 119, 242)) # Modern Royal Blue
    draw.ellipse([26, 26, 230, 230], fill=(20, 95, 200))
    
    # Cloud shape (representing Cloud Storage / Google Drive)
    cloud_color = (255, 255, 255)
    draw.ellipse([65, 110, 125, 170], fill=cloud_color)
    draw.ellipse([100, 80, 160, 140], fill=cloud_color)
    draw.ellipse([140, 105, 195, 165], fill=cloud_color)
    draw.rectangle([90, 125, 175, 165], fill=cloud_color)
    
    # Database cylinder shape inside cloud / overlaid in center
    db_color = (30, 144, 255)
    db_top_color = (135, 206, 250)
    
    # Cylinder bottom disk
    draw.chord([105, 160, 155, 185], start=0, end=180, fill=db_color)
    # Cylinder middle
    draw.rectangle([105, 145, 155, 172], fill=db_color)
    # Cylinder top ellipse
    draw.ellipse([105, 135, 155, 155], fill=db_top_color)
    
    # Upward sync arrow (representing Cloud Sync / Backup)
    arrow_color = (255, 215, 0) # Gold
    draw.polygon([(130, 95), (115, 120), (145, 120)], fill=arrow_color)
    draw.rectangle([125, 120, 135, 138], fill=arrow_color)
    
    ico_path = os.path.join(output_dir, "app_icon.ico")
    png_path = os.path.join(output_dir, "app_icon.png")
    
    image.save(png_path, format="PNG")
    image.save(
        ico_path, 
        format="ICO", 
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    )
    print(f"Generated icons:\n  {ico_path}\n  {png_path}")

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    create_backup_icon(current_dir)

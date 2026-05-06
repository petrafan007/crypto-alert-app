"""
Bitcoin Icon Generator for Desktop App
Creates a simple Bitcoin symbol icon
"""
from PIL import Image, ImageDraw, ImageFont
import os

def create_bitcoin_icon():
    """Create a Bitcoin symbol icon"""
    
    # Create a 128x128 image with transparent background
    size = 128
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Bitcoin orange color
    bitcoin_orange = (247, 147, 26, 255)  # #F7931A
    bitcoin_dark = (255, 165, 0, 255)     # Darker orange for contrast
    
    # Draw outer circle
    margin = 8
    circle_coords = [margin, margin, size - margin, size - margin]
    draw.ellipse(circle_coords, fill=bitcoin_orange, outline=bitcoin_dark, width=3)
    
    # Calculate center and dimensions for the B symbol
    center_x = size // 2
    center_y = size // 2
    
    # Draw the Bitcoin "B" symbol
    # This is a simplified version - two vertical lines and curves
    
    # Main vertical line (left side of B)
    line_width = 8
    line_height = size // 2
    left_x = center_x - 20
    top_y = center_y - line_height // 2
    bottom_y = center_y + line_height // 2
    
    # Left vertical line
    draw.rectangle([left_x, top_y, left_x + line_width, bottom_y], fill='white')
    
    # Top horizontal line
    draw.rectangle([left_x, top_y, left_x + 30, top_y + line_width], fill='white')
    
    # Middle horizontal line
    middle_y = center_y - line_width // 2
    draw.rectangle([left_x, middle_y, left_x + 28, middle_y + line_width], fill='white')
    
    # Bottom horizontal line
    draw.rectangle([left_x, bottom_y - line_width, left_x + 30, bottom_y], fill='white')
    
    # Right curves (simplified as rectangles)
    # Top curve
    right_top_x = left_x + 25
    draw.rectangle([right_top_x, top_y + 5, right_top_x + line_width, middle_y + 3], fill='white')
    
    # Bottom curve
    draw.rectangle([right_top_x + 2, middle_y - 3, right_top_x + line_width + 2, bottom_y - 5], fill='white')
    
    # Add small vertical lines above and below (traditional Bitcoin symbol)
    extend_line = 10
    draw.rectangle([left_x + 12, top_y - extend_line, left_x + 12 + 4, top_y], fill='white')
    draw.rectangle([left_x + 12, bottom_y, left_x + 12 + 4, bottom_y + extend_line], fill='white')
    
    return img

def save_icon_formats(img):
    """Save icon in multiple formats"""
    # Save as ICO (Windows icon format)
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128)]
    img.save('bitcoin_icon.ico', format='ICO', sizes=ico_sizes)
    
    # Save as PNG
    img.save('bitcoin_icon.png', format='PNG')
    
    # Save smaller versions
    img_32 = img.resize((32, 32), Image.Resampling.LANCZOS)
    img_32.save('bitcoin_icon_32.png', format='PNG')
    
    img_64 = img.resize((64, 64), Image.Resampling.LANCZOS)
    img_64.save('bitcoin_icon_64.png', format='PNG')

if __name__ == "__main__":
    try:
        print("🪙 Creating Bitcoin icon...")
        
        # Create the icon
        icon = create_bitcoin_icon()
        
        # Save in multiple formats
        save_icon_formats(icon)
        
        print("✅ Bitcoin icon created successfully!")
        print("📁 Files created:")
        print("   - bitcoin_icon.ico (Windows icon)")
        print("   - bitcoin_icon.png (128x128)")
        print("   - bitcoin_icon_32.png (32x32)")
        print("   - bitcoin_icon_64.png (64x64)")
        
    except ImportError:
        print("❌ PIL (Pillow) not installed")
        print("💡 Alternative: Creating simple text-based icon...")
        
        # Create a simple fallback icon using basic graphics
        print("📝 Creating fallback icon...")
        with open('bitcoin_icon.txt', 'w') as f:
            f.write("Bitcoin Icon - Use any image editor to create an icon with Bitcoin symbol ₿")
        
        print("✅ Created fallback text file")
        print("💡 Suggestion: Use an online icon generator with Bitcoin symbol ₿")
        
    except Exception as e:
        print(f"❌ Error creating icon: {e}")
        print("💡 Creating simple placeholder...")
        
        # Create placeholder
        with open('icon_placeholder.txt', 'w') as f:
            f.write("Create a Bitcoin icon manually and save as bitcoin_icon.ico")
        
        print("✅ Created placeholder")

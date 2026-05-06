#!/usr/bin/env python3
"""
Simple Bitcoin Icon Creator (No PIL required)
Creates a basic Windows ICO file with Bitcoin colors
"""

def create_simple_ico():
    """Create a simple 32x32 ICO file with Bitcoin colors"""
    
    # ICO file header (6 bytes)
    ico_header = bytearray([
        0x00, 0x00,  # Reserved (must be 0)
        0x01, 0x00,  # Image type (1 = ICO)
        0x01, 0x00   # Number of images in file (1)
    ])
    
    # ICO directory entry (16 bytes)
    ico_dir_entry = bytearray([
        0x20,        # Width (32 pixels)
        0x20,        # Height (32 pixels)
        0x00,        # Color count (0 = more than 256 colors)
        0x00,        # Reserved
        0x01, 0x00,  # Color planes (1)
        0x20, 0x00,  # Bits per pixel (32 = RGBA)
        0x80, 0x02, 0x00, 0x00,  # Size of image data (640 bytes)
        0x16, 0x00, 0x00, 0x00   # Offset to image data (22 bytes)
    ])
    
    # Create 32x32 RGBA bitmap data
    width, height = 32, 32
    
    # Bitcoin orange color (RGBA)
    bitcoin_orange = [26, 147, 247, 255]  # #F7931A in BGRA format for ICO
    white = [255, 255, 255, 255]
    transparent = [0, 0, 0, 0]
    
    # Create bitmap data (bottom-up, left-to-right)
    bitmap_data = bytearray()
    
    for y in range(height - 1, -1, -1):  # ICO format is bottom-up
        for x in range(width):
            # Calculate distance from center
            center_x, center_y = width // 2, height // 2
            dx, dy = x - center_x, y - center_y
            distance = (dx * dx + dy * dy) ** 0.5
            
            # Create a simple circular Bitcoin icon
            if distance < 14:  # Inside circle
                # Simple Bitcoin "B" pattern
                if (8 <= x <= 10 and 8 <= y <= 24) or \
                   (8 <= x <= 20 and 8 <= y <= 10) or \
                   (8 <= x <= 18 and 15 <= y <= 17) or \
                   (8 <= x <= 20 and 22 <= y <= 24) or \
                   (18 <= x <= 20 and 10 <= y <= 17) or \
                   (20 <= x <= 22 and 17 <= y <= 22):
                    # White for Bitcoin "B"
                    bitmap_data.extend(white)
                else:
                    # Bitcoin orange background
                    bitmap_data.extend(bitcoin_orange)
            else:
                # Transparent outside circle
                bitmap_data.extend(transparent)
    
    # Create AND mask (1 bit per pixel, padded to 4-byte boundary)
    and_mask = bytearray()
    for y in range(height):
        mask_byte = 0
        bit_count = 0
        for x in range(width):
            # Set bit to 0 for opaque, 1 for transparent
            center_x, center_y = width // 2, height // 2
            dx, dy = x - center_x, y - center_y
            distance = (dx * dx + dy * dy) ** 0.5
            
            if distance >= 14:  # Transparent outside circle
                mask_byte |= (1 << (7 - bit_count))
            
            bit_count += 1
            if bit_count == 8:
                and_mask.append(mask_byte)
                mask_byte = 0
                bit_count = 0
        
        # Pad to 4-byte boundary
        while len(and_mask) % 4 != 0:
            and_mask.append(0)
    
    # Combine all data
    ico_data = ico_header + ico_dir_entry + bitmap_data + and_mask
    
    return ico_data

def main():
    """Create the Bitcoin ICO file"""
    try:
        print("🪙 Creating simple Bitcoin icon...")
        
        ico_data = create_simple_ico()
        
        with open('bitcoin_icon.ico', 'wb') as f:
            f.write(ico_data)
        
        print("✅ Bitcoin icon created: bitcoin_icon.ico")
        print(f"📏 File size: {len(ico_data)} bytes")
        print("🎯 32x32 pixel icon with Bitcoin orange background")
        
    except Exception as e:
        print(f"❌ Error creating icon: {e}")
        
        # Create a placeholder text file
        with open('bitcoin_icon_instructions.txt', 'w') as f:
            f.write("""
Bitcoin Icon Instructions:

1. Download a Bitcoin icon from: https://bitcoin.org/img/icons/opengraph.png
2. Resize to 32x32 or 64x64 pixels
3. Convert to ICO format using online converter
4. Save as 'bitcoin_icon.ico'

Or use the SVG file (bitcoin_icon.svg) with an online SVG to ICO converter.
""")
        
        print("✅ Created instructions file: bitcoin_icon_instructions.txt")

if __name__ == "__main__":
    main()

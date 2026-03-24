"""
Erstellt ein einfaches Icon für WetzlarErkennung
"""
import os

from PIL import Image, ImageDraw, ImageFont


def create_icon():
    """Erstellt ein einfaches Icon mit 'W' Buchstaben"""
    # Erstelle verschiedene Größen für das Icon
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    images = []
    
    for size in sizes:
        # Erstelle neues Bild mit transparentem Hintergrund
        img = Image.new('RGBA', size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        
        # Zeichne Hintergrund (dunkles Blau)
        draw.ellipse([0, 0, size[0]-1, size[1]-1], fill=(25, 50, 100, 255))
        
        # Zeichne weißen Rand
        draw.ellipse([0, 0, size[0]-1, size[1]-1], outline=(255, 255, 255, 255), width=max(1, size[0]//32))
        
        # Zeichne 'W' in der Mitte
        font_size = size[0] // 2
        try:
            # Versuche eine System-Schriftart zu verwenden
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            # Fallback auf Standard-Schriftart
            font = ImageFont.load_default()
        
        # Berechne Text-Position (zentriert)
        text = "W"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        
        position = ((size[0] - text_width) // 2 - bbox[0], 
                   (size[1] - text_height) // 2 - bbox[1])
        
        # Zeichne Text (weiß)
        draw.text(position, text, fill=(255, 255, 255, 255), font=font)
        
        images.append(img)
    
    # Speichere als ICO-Datei (multi-size)
    output_path = os.path.join(os.path.dirname(__file__), 'icon.ico')
    images[0].save(output_path, format='ICO', sizes=[(img.width, img.height) for img in images])
    
    print(f"Icon erfolgreich erstellt: {output_path}")
    return output_path

if __name__ == '__main__':
    try:
        create_icon()
    except Exception as e:
        print(f"Fehler beim Erstellen des Icons: {e}")
        print("\nAlternativ können Sie ein eigenes Icon (icon.ico) im Projektverzeichnis platzieren.")

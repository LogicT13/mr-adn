import os
import sys
import urllib.request
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QMovie

# Use a generic transparent placeholder or a dummy URL for Mr DNA.
# In a real scenario, the user would provide a direct link to a clean transparent GIF.
GIF_URL = "https://media.giphy.com/media/VbYj3Ej0iE9D5CjZgP/giphy.gif" # Placeholder

def setup_sprite():
    root_dir = Path(__file__).parent.parent
    assets_dir = root_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    
    target_path = assets_dir / "mr_dna_idle.gif"
    
    print(f"Downloading Mr. DNA GIF to {target_path}...")
    try:
        req = urllib.request.Request(GIF_URL, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response, open(target_path, 'wb') as out_file:
            out_file.write(response.read())
        print("Download complete.")
    except Exception as e:
        print(f"Failed to download GIF: {e}")
        print("Please manually download a transparent Mr. DNA GIF and place it in the assets/ directory.")
        return

    # Validate with QMovie
    app = QApplication(sys.argv)
    movie = QMovie(str(target_path))
    if movie.isValid():
        print(f"Success! {target_path.name} loaded correctly with {movie.frameCount()} frames.")
    else:
        print(f"Error: {target_path.name} is not a valid GIF or could not be loaded by PyQt6.")

if __name__ == "__main__":
    setup_sprite()

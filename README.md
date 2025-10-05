# Atlasify Selected Object

## Description
**Atlasify Selected Object** is a Python script designed for Blender to automate the creation of texture atlases for 3D models. It simplifies the process of combining multiple textures into a single atlas, ensuring efficient UV mapping and material assignment. This tool is particularly useful for optimizing 3D assets for game engines or other real-time applications.

### Key Features
- **Automatic Duplication**: Duplicates the active object and creates a new version with a single-user mesh.
- **Texture Atlas Creation**: Generates BaseColor and Normal atlases with customizable padding, tile size, and layout.
- **UV Mapping**: Creates a new UV map (`BAKE_ATLAS`) by remapping UVs based on material slots.
- **Material Assignment**: Assigns a single material wired to the generated atlases.
- **Customizable Options**: Includes settings for output directory, atlas resolution, resampling methods, and more.

## Installation
1. Ensure you have Blender installed.
2. Install the Pillow library (required for image processing):
   ```
   import ensurepip, pip
   ensurepip.bootstrap()
   pip.main(['install', 'pillow'])
   ```
3. Place the `atlasify_selected_object.py` script in your Blender scripts directory or any accessible location.

## Usage
1. Open Blender and select a mesh object.
2. Ensure the object has material slots with textures assigned to Base Color and/or Normal inputs.
3. Run the script in Blender's scripting editor or via the Python console.
4. The script will generate a duplicate object with the atlas applied and save the output in the specified directory.

## Options
You can customize the following options in the script:
- **OUTPUT_DIR**: Directory for saving the generated atlases.
- **PADDING_PX**: Padding between tiles in pixels.
- **TILE_W / TILE_H**: Tile width and height (default: maximum source dimensions).
- **FORCE_POW2**: Force atlas dimensions to be powers of two.
- **RESAMPLE**: Resampling method for resizing textures (e.g., `LANCZOS`, `BILINEAR`).
- **LAYOUT**: Layout of the atlas (`auto`, `row`, `col`, or custom rows/columns).

## License
This project is licensed under a simple permissive license. You are free to use, modify, and distribute this script. However, you must include a link to this repository or credit the author (Alex Rynas) in your project.

---

**Author**: Alex Rynas
**Repository**: [Atlasify_Selected_Object](https://github.com/AlexRynas/Atlasify_Selected_Object)
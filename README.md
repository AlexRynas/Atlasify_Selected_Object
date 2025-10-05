# Atlasify Selected Object

## Description
**Atlasify Selected Object** is a Python script designed for Blender to automate the creation of texture atlases for 3D models. It simplifies the process of combining multiple textures into a single atlas, ensuring efficient UV mapping and material assignment. This tool is particularly useful for optimizing 3D assets for game engines or other real-time applications with full PBR (Physically Based Rendering) support.

### Key Features
- **Automatic Duplication**: Duplicates the active object and creates a new version with a single-user mesh.
- **Complete PBR Texture Atlas Creation**: Generates BaseColor, Normal, Roughness, and Metalness atlases with customizable padding, tile size, and layout.
- **UV Mapping**: Creates a new UV map (`BAKE_ATLAS`) by remapping UVs based on material slots.
- **Material Assignment**: Assigns a single material wired to all generated atlases.
- **Smart Texture Detection**: Automatically detects and extracts textures from Principled BSDF shader nodes.
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
2. Ensure the object has material slots with textures assigned to Base Color, Normal, Roughness, and/or Metallic inputs of Principled BSDF nodes.
3. Run the script in Blender's scripting editor or via the Python console.
4. The script will generate a duplicate object with the atlas applied and save the output in the specified directory.

### Output
The script generates the following files:
- **`<name>_BaseColor.png`**: Combined base color/albedo atlas
- **`<name>_Normal.png`**: Combined normal map atlas
- **`<name>_Roughness.png`**: Combined roughness atlas (grayscale)
- **`<name>_Metalness.png`**: Combined metalness atlas (grayscale)
- **`<name>_manifest.json`**: JSON file containing atlas layout information and UV coordinates

## Options
You can customize the following options in the script:
- **OUTPUT_DIR**: Directory for saving the generated atlases (default: `//atlas_out` next to .blend file).
- **ATLAS_BASENAME**: Base name for output files (default: object name).
- **PADDING_PX**: Padding between tiles in pixels (default: 32).
- **TILE_W / TILE_H**: Tile width and height (default: maximum source dimensions).
- **FORCE_POW2**: Force atlas dimensions to be powers of two (default: True).
- **RESAMPLE**: Resampling method for resizing textures - `NEAREST`, `BILINEAR`, `BICUBIC`, or `LANCZOS` (default: `LANCZOS`).
- **LAYOUT**: Layout of the atlas - `auto`, `row`, `col`, or custom tuple `(rows, cols)` (default: `auto`).
- **MATERIAL_NAME**: Name of the generated material (default: `AtlasMaterial`).
- **UV_NAME**: Name of the generated UV map (default: `BAKE_ATLAS`).

## Requirements
- **Blender**: 2.8 or higher (tested with 3.x and 4.x)
- **Pillow (PIL)**: Python imaging library for texture processing

## Features in Detail

### Smart Texture Detection
The script intelligently detects textures by:
1. Following node connections from Principled BSDF inputs
2. Tracing UV map nodes to preserve correct UV channels per material
3. Searching by texture name patterns as fallback (e.g., "roughness", "metallic", "normal")

### Default Values
If a material slot is missing certain textures, the script uses sensible defaults:
- **Base Color**: Black (0, 0, 0)
- **Normal**: Flat normal (128, 128, 255)
- **Roughness**: Mid-gray (128) - medium roughness
- **Metalness**: Black (0) - non-metallic

### UV Mapping
The script creates a new UV layer (`BAKE_ATLAS`) that:
- Preserves the original UV layout per material slot
- Remaps coordinates to the correct atlas region
- Maintains proper texture sampling for each face based on its material assignment

## License
This project is licensed under a simple permissive license. You are free to use, modify, and distribute this script. However, you must include a link to this repository or credit the author (Alex Rynas) in your project.

---

**Author**: Alex Rynas
**Repository**: [Atlasify_Selected_Object](https://github.com/AlexRynas/Atlasify_Selected_Object)
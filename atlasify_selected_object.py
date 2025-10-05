
# atlasify_selected_object_v4.py
# Universal no-bake atlas builder with robust per-slot UV detection.
# - Duplicates ACTIVE object to <name>_ATLAS (single-user mesh)
# - Builds BaseColor + Normal + Roughness + Metalness atlases
# - Creates BAKE_ATLAS UV by remapping from the UV actually used per material slot
# - Finally assigns a single material wired to the atlases

import bpy, os, math, json, tempfile

# ------------- OPTIONS -----------------
OUTPUT_DIR = None          # None -> //atlas_out next to .blend
ATLAS_BASENAME = None      # None -> object name
PADDING_PX = 32
TILE_W = None              # None -> max source width
TILE_H = None              # None -> max source height
FORCE_POW2 = True
RESAMPLE = 'LANCZOS'       # 'NEAREST' | 'BILINEAR' | 'BICUBIC' | 'LANCZOS'
LAYOUT = 'auto'            # 'auto' | 'row' | 'col' | (rows, cols)
MATERIAL_NAME = 'AtlasMaterial'
UV_NAME = 'BAKE_ATLAS'
# --------------------------------------

def _get_pil():
    try:
        from PIL import Image, ImageOps
        return Image, ImageOps
    except Exception as e:
        raise RuntimeError(
            "Pillow (PIL) is required. In Blender's Python Console run:\n"
            "import ensurepip, pip; ensurepip.bootstrap(); pip.main(['install','pillow'])\n"
            f"Original import error: {e}"
        )

def _get_scene_dir():
    if bpy.data.is_saved:
        return os.path.dirname(bpy.data.filepath)
    return tempfile.gettempdir()

def _abspath(path):
    return bpy.path.abspath(path) if path else ''

def _pow2(n):
    p = 1
    while p < n: p <<= 1
    return p

def _choose_layout(n):
    if isinstance(LAYOUT, tuple) and len(LAYOUT) == 2:
        r, c = LAYOUT
        return max(1, int(r)), max(1, int(c))
    if LAYOUT == 'row':  return 1, n
    if LAYOUT == 'col':  return n, 1
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    return rows, cols

def _resample_mode(Image):
    key = RESAMPLE.upper()
    try:
        R = Image.Resampling
        return {'NEAREST':R.NEAREST,'BILINEAR':R.BILINEAR,'BICUBIC':R.BICUBIC,'LANCZOS':R.LANCZOS}.get(key, R.LANCZOS)
    except AttributeError:
        default = getattr(Image,'LANCZOS',None) or getattr(Image,'BICUBIC',None) or getattr(Image,'BILINEAR',None) or getattr(Image,'NEAREST',None)
        return getattr(Image, key, default)

# ---------- Node graph helpers ----------
def _find_principled(nt):
    for n in nt.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            return n
    return None

def _upstream_uvmap_name(nt, tex_image_node):
    """Follow Vector input upstream to find a UV Map node; return uv_map string or None."""
    if not tex_image_node: return None
    stack = [tex_image_node]
    visited = set()
    while stack:
        node = stack.pop()
        if node in visited: continue
        visited.add(node)
        # Examine its inputs
        if 'Vector' in node.inputs and node.inputs['Vector'].is_linked:
            from_socket = node.inputs['Vector'].links[0].from_socket
            from_node = from_socket.node
            if from_node.type == 'UVMAP':
                return from_node.uv_map or None
            # Keep walking upstream (Mapping, TextureCoord, etc.)
            stack.append(from_node)
    return None

def _find_image_input_socket_link(nt, dest_node, dest_socket_name):
    sock = dest_node.inputs.get(dest_socket_name)
    if not sock or not sock.is_linked: return None
    n = sock.links[0].from_node
    return n if n and n.type == 'TEX_IMAGE' else None

def _find_basecolor_image_node(nt, principled):
    n = _find_image_input_socket_link(nt, principled, 'Base Color')
    if n: return n
    for node in nt.nodes:
        if node.type == 'TEX_IMAGE':
            nm = (node.name or '').lower()
            if any(k in nm for k in ('base','albedo','diff','color')):
                return node
    for node in nt.nodes:
        if node.type == 'TEX_IMAGE':
            return node
    return None

def _find_normal_image_node(nt, principled):
    normal_in = principled.inputs.get('Normal')
    if normal_in and normal_in.is_linked:
        nmap = normal_in.links[0].from_node
        if nmap and nmap.type == 'NORMAL_MAP':
            col = nmap.inputs.get('Color')
            if col and col.is_linked:
                inode = col.links[0].from_node
                if inode and inode.type == 'TEX_IMAGE':
                    return inode
    n = _find_image_input_socket_link(nt, principled, 'Normal')
    if n: return n
    for node in nt.nodes:
        if node.type == 'TEX_IMAGE':
            img = node.image
            try:
                if img and img.colorspace_settings.name.lower().startswith('non-'):
                    return node
            except: pass
    return None

def _find_roughness_image_node(nt, principled):
    """Find the roughness texture node connected to Principled BSDF."""
    n = _find_image_input_socket_link(nt, principled, 'Roughness')
    if n: return n
    # Search by name as fallback
    for node in nt.nodes:
        if node.type == 'TEX_IMAGE':
            nm = (node.name or '').lower()
            if any(k in nm for k in ('rough', 'glossy', 'gloss')):
                return node
    return None

def _find_metalness_image_node(nt, principled):
    """Find the metalness/metallic texture node connected to Principled BSDF."""
    n = _find_image_input_socket_link(nt, principled, 'Metallic')
    if n: return n
    # Search by name as fallback
    for node in nt.nodes:
        if node.type == 'TEX_IMAGE':
            nm = (node.name or '').lower()
            if any(k in nm for k in ('metal', 'metallic', 'metalness')):
                return node
    return None

def _image_to_path(img, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    if not img: return None
    # Prefer existing file path
    src = _abspath(img.filepath)
    if src and os.path.exists(src):
        return src
    # Save packed image
    safe = (img.name or 'Image').replace('.', '_').replace(' ', '_')
    path = os.path.join(out_dir, f'{safe}.png')
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    return path

# -------- Build atlases --------
def _build_atlases(slot_images, out_dir, base_name):
    Image, ImageOps = _get_pil()
    sizes = []
    for s in slot_images:
        with Image.open(s['base_path']) as im:
            sizes.append(im.size)
    max_w = max(w for w,h in sizes); max_h = max(h for w,h in sizes)
    tw = TILE_W or max_w; th = TILE_H or max_h
    rows, cols = _choose_layout(len(slot_images))
    W = cols*tw + (cols+1)*PADDING_PX
    H = rows*th + (rows+1)*PADDING_PX
    if FORCE_POW2: W = _pow2(W); H = _pow2(H)
    atlas_base = Image.new('RGB', (W, H), (20,20,20))
    atlas_norm = Image.new('RGBA', (W, H), (20,20,20,255))
    atlas_rough = Image.new('L', (W, H), 128)  # Grayscale for roughness
    atlas_metal = Image.new('L', (W, H), 0)    # Grayscale for metalness
    resample = _resample_mode(Image)

    def place(img_path, x, y, canvas, is_normal=False, is_grayscale=False):
        if img_path and os.path.exists(img_path):
            if is_grayscale:
                im = Image.open(img_path).convert('L')
            else:
                im = Image.open(img_path).convert('RGBA' if is_normal else 'RGB')
        else:
            if is_grayscale:
                im = Image.new('L', (tw, th), 128)
            else:
                im = Image.new('RGBA' if is_normal else 'RGB', (tw, th), (128,128,255,255) if is_normal else (0,0,0))
        im = im.resize((tw, th), resample=resample)
        if is_grayscale:
            canvas.paste(im, (x, y))
        else:
            canvas.paste(im, (x, y), im if im.mode == 'RGBA' else None)
        im.close()

    rects_px = []
    idx = 0
    for r in range(rows):
        for c in range(cols):
            if idx >= len(slot_images): break
            x0 = PADDING_PX + c*(tw + PADDING_PX)
            y0 = PADDING_PX + r*(th + PADDING_PX)
            x1 = x0 + tw; y1 = y0 + th
            s = slot_images[idx]
            place(s['base_path'], x0, y0, atlas_base, is_normal=False)
            place(s.get('normal_path'), x0, y0, atlas_norm, is_normal=True)
            place(s.get('roughness_path'), x0, y0, atlas_rough, is_grayscale=True)
            place(s.get('metalness_path'), x0, y0, atlas_metal, is_grayscale=True)
            rects_px.append((s['slot_index'], [x0,y0,x1,y1]))
            idx += 1

    os.makedirs(out_dir, exist_ok=True)
    base_path = os.path.join(out_dir, f'{base_name}_BaseColor.png')
    norm_path = os.path.join(out_dir, f'{base_name}_Normal.png')
    rough_path = os.path.join(out_dir, f'{base_name}_Roughness.png')
    metal_path = os.path.join(out_dir, f'{base_name}_Metalness.png')
    atlas_base.save(base_path, 'PNG'); atlas_norm.save(norm_path, 'PNG')
    atlas_rough.save(rough_path, 'PNG'); atlas_metal.save(metal_path, 'PNG')

    rects_uv = {}
    for slot_idx, (x0,y0,x1,y1) in rects_px:
        u0 = x0 / W; u1 = x1 / W
        v0 = 1.0 - (y1 / H); v1 = 1.0 - (y0 / H)
        rects_uv[slot_idx] = (u0, v0, u1, v1)

    manifest = {
        'image_size_px': [W, H],
        'tile_size_px': [tw, th],
        'padding_px': PADDING_PX,
        'rows_cols': [rows, cols],
        'rects_uv_by_slot_index': rects_uv,
    }
    with open(os.path.join(out_dir, f'{base_name}_manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    return base_path, norm_path, rough_path, metal_path, manifest

# -------- UV remap (per-slot source UV) --------
def _remap_uvs_to_atlas_with_slot_uv(obj, slot_to_src_uv, dst_uv_name, rects_uv_by_slot, poly_slot_index_cache):
    me = obj.data
    dst = me.uv_layers.get(dst_uv_name) or me.uv_layers.new(name=dst_uv_name)
    me.uv_layers.active = dst; dst.active = True; dst.active_render = True

    # Build a cache of UV layer data by name
    uvdata_by_name = {uv.name: uv.data for uv in me.uv_layers}

    loop_index = 0
    for poly_idx, poly in enumerate(me.polygons):
        slot_idx = poly_slot_index_cache[poly_idx]
        rect = rects_uv_by_slot.get(slot_idx)
        # which source UV to sample?
        src_name = slot_to_src_uv.get(slot_idx)
        src_data = uvdata_by_name.get(src_name) if src_name in uvdata_by_name else None
        if not src_data:
            # fallback to active render, then active
            src_layer = next((uv for uv in me.uv_layers if uv.active_render), me.uv_layers.active)
            src_data = src_layer.data
        if not rect:
            # copy through
            for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
                dst.data[li].uv = src_data[li].uv
            continue
        u0,v0,u1,v1 = rect; du=(u1-u0); dv=(v1-v0)
        for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
            su,sv = src_data[li].uv
            dst.data[li].uv = (u0 + su*du, v0 + sv*dv)

# -------- One-material shader --------
def _create_atlas_material(obj, base_path, norm_path, rough_path, metal_path, mat_name, uv_name):
    mat = bpy.data.materials.new(mat_name); mat.use_nodes = True
    nt = mat.node_tree; nodes, links = nt.nodes, nt.links
    for n in list(nodes): nodes.remove(n)
    out = nodes.new('ShaderNodeOutputMaterial'); out.location = (420, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location = (140, 0)
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    
    # Base Color texture
    tex_d = nodes.new('ShaderNodeTexImage'); tex_d.location = (-200, 80)
    tex_d.image = bpy.data.images.load(base_path)
    
    # Normal texture
    tex_n = nodes.new('ShaderNodeTexImage'); tex_n.location = (-200, -240)
    tex_n.image = bpy.data.images.load(norm_path)
    try: tex_n.image.colorspace_settings.name = 'Non-Color'
    except: pass
    nmap = nodes.new('ShaderNodeNormalMap'); nmap.location = (20, -240)
    
    # Roughness texture
    tex_r = nodes.new('ShaderNodeTexImage'); tex_r.location = (-200, -400)
    tex_r.image = bpy.data.images.load(rough_path)
    try: tex_r.image.colorspace_settings.name = 'Non-Color'
    except: pass
    
    # Metalness texture
    tex_m = nodes.new('ShaderNodeTexImage'); tex_m.location = (-200, -560)
    tex_m.image = bpy.data.images.load(metal_path)
    try: tex_m.image.colorspace_settings.name = 'Non-Color'
    except: pass
    
    # UV Map node
    uv = nodes.new('ShaderNodeUVMap'); uv.location = (-420, -80); uv.uv_map = uv_name
    
    # Connect UV to all texture nodes
    links.new(uv.outputs['UV'], tex_d.inputs['Vector'])
    links.new(uv.outputs['UV'], tex_n.inputs['Vector'])
    links.new(uv.outputs['UV'], tex_r.inputs['Vector'])
    links.new(uv.outputs['UV'], tex_m.inputs['Vector'])
    
    # Connect textures to Principled BSDF
    links.new(tex_d.outputs['Color'], bsdf.inputs['Base Color'])
    links.new(tex_n.outputs['Color'], nmap.inputs['Color'])
    links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])
    links.new(tex_r.outputs['Color'], bsdf.inputs['Roughness'])
    links.new(tex_m.outputs['Color'], bsdf.inputs['Metallic'])
    
    obj.data.materials.clear(); obj.data.materials.append(mat); obj.active_material = mat

# -------- Main --------
def main():
    obj = bpy.context.active_object
    if not obj or obj.type != 'MESH':
        raise RuntimeError('Select a mesh object first (active object must be MESH).')
    if len(obj.data.materials) == 0:
        raise RuntimeError('The active object has no material slots.')

    scene_dir = _get_scene_dir()
    out_dir = bpy.path.abspath(OUTPUT_DIR) if OUTPUT_DIR else os.path.join(scene_dir, 'atlas_out')
    base_name = (ATLAS_BASENAME or obj.name).replace(' ', '_')
    tmp_dir = os.path.join(out_dir, '_tmp_src'); os.makedirs(tmp_dir, exist_ok=True)

    # PER-SLOT: find base + normal + roughness + metalness images and the UV map name actually used
    slot_images = []
    slot_to_src_uv = {}
    for idx, mat in enumerate(obj.data.materials):
        if not mat or not mat.use_nodes or not mat.node_tree: continue
        nt = mat.node_tree
        bsdf = _find_principled(nt)
        if not bsdf: continue
        base_node = _find_basecolor_image_node(nt, bsdf)
        normal_node = _find_normal_image_node(nt, bsdf)
        roughness_node = _find_roughness_image_node(nt, bsdf)
        metalness_node = _find_metalness_image_node(nt, bsdf)
        
        base_img = base_node.image if base_node else None
        normal_img = normal_node.image if normal_node else None
        roughness_img = roughness_node.image if roughness_node else None
        metalness_img = metalness_node.image if metalness_node else None
        
        base_path = _image_to_path(base_img, tmp_dir) if base_img else None
        normal_path = _image_to_path(normal_img, tmp_dir) if normal_img else None
        roughness_path = _image_to_path(roughness_img, tmp_dir) if roughness_img else None
        metalness_path = _image_to_path(metalness_img, tmp_dir) if metalness_img else None
        
        if not base_path and not normal_path and not roughness_path and not metalness_path:
            # skip empty slots
            continue
        slot_images.append({
            'slot_index': idx, 
            'slot_name': mat.name, 
            'base_path': base_path, 
            'normal_path': normal_path,
            'roughness_path': roughness_path,
            'metalness_path': metalness_path
        })
        # UV map used by this slot (prefer base's chain, else check others)
        uvname = (_upstream_uvmap_name(nt, base_node) or 
                  _upstream_uvmap_name(nt, normal_node) or
                  _upstream_uvmap_name(nt, roughness_node) or
                  _upstream_uvmap_name(nt, metalness_node))
        slot_to_src_uv[idx] = uvname  # may be None (handled later)

    if not slot_images:
        raise RuntimeError('No usable textures found in material slots (Base Color / Normal / Roughness / Metalness).')

    # Build atlases
    base_atlas_path, normal_atlas_path, rough_atlas_path, metal_atlas_path, manifest = _build_atlases(slot_images, out_dir, base_name)

    # Duplicate object (single-user mesh) BEFORE modifying anything
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True); bpy.context.view_layer.objects.active = obj
    bpy.ops.object.duplicate()
    dup = bpy.context.active_object
    dup.name = f'{obj.name}_ATLAS'
    dup.data = dup.data.copy()  # single-user mesh so UV edits don't touch the source

    # Cache the original per-polygon material indices from the SOURCE object
    poly_slot_index_cache = [p.material_index for p in obj.data.polygons]

    # Create BAKE_ATLAS UV on the duplicate by remapping from per-slot src UV
    _remap_uvs_to_atlas_with_slot_uv(dup, slot_to_src_uv, UV_NAME, manifest['rects_uv_by_slot_index'], poly_slot_index_cache)

    # Now assign the single atlas material on the duplicate
    _create_atlas_material(dup, base_atlas_path, normal_atlas_path, rough_atlas_path, metal_atlas_path, MATERIAL_NAME, UV_NAME)

    # Pack for convenience
    try: bpy.ops.file.pack_all()
    except Exception as e: print('Pack warning:', e)

    print(f"[DONE] Created '{dup.name}' with one material and atlases at: {out_dir}")
    print(f"  BaseColor: {base_atlas_path}")
    print(f"  Normal:    {normal_atlas_path}")
    print(f"  Roughness: {rough_atlas_path}")
    print(f"  Metalness: {metal_atlas_path}")
    print(f"  UV Map:    {UV_NAME} (mapped by material slot)")

if __name__ == '__main__':
    main()
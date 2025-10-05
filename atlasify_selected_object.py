# atlasify_selected_object_v2.py
# Universal no-bake atlas builder (patched resampling for Pillow 10+).

import bpy, bmesh, os, math, json, tempfile

# ---- OPTIONS ------------------------------------------------
OUTPUT_DIR = None
ATLAS_BASENAME = None
PADDING_PX = 32
TILE_W = None
TILE_H = None
FORCE_POW2 = True
RESAMPLE = 'LANCZOS'   # 'NEAREST' | 'BILINEAR' | 'BICUBIC' | 'LANCZOS'
LAYOUT = 'auto'        # 'auto' | 'row' | 'col' | (rows, cols)
SRC_UV_NAME = None
MATERIAL_NAME = 'AtlasMaterial'
UV_NAME = 'BAKE_ATLAS'
# -------------------------------------------------------------

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

def _image_to_path(img, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    name = (img.name or 'Image').replace('.', '_').replace(' ', '_')
    out_path = os.path.join(out_dir, f"{name}.png")
    try:
        src = _abspath(img.filepath)
        if src and os.path.exists(src):
            return src
        img.filepath_raw = out_path
        img.file_format = 'PNG'
        img.save()
        return out_path
    except Exception:
        try:
            img.save_render(out_path)
            return out_path
        except Exception as e:
            raise RuntimeError(f"Cannot save image '{img.name}': {e}")

def _pow2(n):
    p = 1
    while p < n:
        p <<= 1
    return p

def _choose_layout(n):
    if isinstance(LAYOUT, tuple) and len(LAYOUT) == 2:
        r, c = LAYOUT
        return max(1, int(r)), max(1, int(c))
    if LAYOUT == 'row':
        return 1, n
    if LAYOUT == 'col':
        return n, 1
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    return rows, cols

def _resample_mode(Image):
    key = RESAMPLE.upper()
    # Pillow 10+: enums under Image.Resampling
    try:
        Resampling = Image.Resampling
        mapping = {
            'NEAREST': Resampling.NEAREST,
            'BILINEAR': Resampling.BILINEAR,
            'BICUBIC': Resampling.BICUBIC,
            'LANCZOS': Resampling.LANCZOS,
        }
        return mapping.get(key, mapping['LANCZOS'])
    except AttributeError:
        # Older Pillow: enums directly on Image
        mapping = {
            'NEAREST': getattr(Image, 'NEAREST', None),
            'BILINEAR': getattr(Image, 'BILINEAR', None),
            'BICUBIC': getattr(Image, 'BICUBIC', None),
            'LANCZOS': getattr(Image, 'LANCZOS', None),
        }
        default = mapping.get('LANCZOS') or mapping.get('BICUBIC') or mapping.get('BILINEAR') or mapping.get('NEAREST')
        return mapping.get(key, default)

def _find_principled(nt):
    for n in nt.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            return n
    return None

def _find_image_input_socket_link(nt, dest_node, dest_socket_name):
    dest_input = dest_node.inputs.get(dest_socket_name)
    if not dest_input or not dest_input.is_linked:
        return None
    from_node = dest_input.links[0].from_node
    if from_node and from_node.type == 'TEX_IMAGE':
        return from_node
    return None

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
    norm_input = principled.inputs.get('Normal')
    if norm_input and norm_input.is_linked:
        nmap = norm_input.links[0].from_node
        if nmap and nmap.type == 'NORMAL_MAP':
            col_input = nmap.inputs.get('Color')
            if col_input and col_input.is_linked:
                inode = col_input.links[0].from_node
                if inode and inode.type == 'TEX_IMAGE':
                    return inode
    inode = _find_image_input_socket_link(nt, principled, 'Normal')
    if inode: return inode
    for node in nt.nodes:
        if node.type == 'TEX_IMAGE':
            img = node.image
            try:
                if img and img.colorspace_settings.name.lower().startswith('non-'):
                    return node
            except:
                pass
    return None

def _collect_slot_textures(mat):
    if not mat or not mat.use_nodes or not mat.node_tree:
        return (None, None)
    nt = mat.node_tree
    bsdf = _find_principled(nt)
    if not bsdf:
        return (None, None)
    base_node = _find_basecolor_image_node(nt, bsdf)
    normal_node = _find_normal_image_node(nt, bsdf)
    base_img = base_node.image if base_node else None
    normal_img = normal_node.image if normal_node else None
    return (base_img, normal_img)

def _build_atlases(slot_images, out_dir, base_name):
    Image, ImageOps = _get_pil()
    sizes = []
    for s in slot_images:
        im = Image.open(s['base_path'])
        sizes.append(im.size); im.close()
    max_w = max(w for w,h in sizes); max_h = max(h for w,h in sizes)
    tw = TILE_W or max_w; th = TILE_H or max_h
    rows, cols = _choose_layout(len(slot_images))
    W = cols*tw + (cols+1)*PADDING_PX
    H = rows*th + (rows+1)*PADDING_PX
    if FORCE_POW2:
        W = _pow2(W); H = _pow2(H)
    atlas_base = Image.new('RGB', (W, H), (20,20,20))
    atlas_norm = Image.new('RGBA', (W, H), (20,20,20,255))
    resample = _resample_mode(Image)
    def place(img_path, x, y, canvas, is_normal=False):
        if img_path and os.path.exists(img_path):
            im = Image.open(img_path).convert('RGBA' if is_normal else 'RGB')
        else:
            im = Image.new('RGBA' if is_normal else 'RGB', (tw, th), (128,128,255,255) if is_normal else (0,0,0))
        im = im.resize((tw, th), resample=resample)
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
            rects_px.append((s['slot_index'], [x0,y0,x1,y1]))
            idx += 1
    os.makedirs(out_dir, exist_ok=True)
    base_path = os.path.join(out_dir, f"{base_name}_BaseColor.png")
    norm_path = os.path.join(out_dir, f"{base_name}_Normal.png")
    atlas_base.save(base_path, 'PNG'); atlas_norm.save(norm_path, 'PNG')
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
    with open(os.path.join(out_dir, f"{base_name}_manifest.json"), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2)
    return base_path, norm_path, manifest

def _remap_uvs_to_atlas(obj, src_uv_name, dst_uv_name, rects_uv_by_slot):
    me = obj.data
    dst = me.uv_layers.get(dst_uv_name) or me.uv_layers.new(name=dst_uv_name)
    me.uv_layers.active = dst; dst.active = True; dst.active_render = True
    src = me.uv_layers.get(src_uv_name)
    if not src: raise RuntimeError(f"Source UV layer '{src_uv_name}' not found")
    src_data = src.data; dst_data = dst.data
    for poly in me.polygons:
        rect = rects_uv_by_slot.get(poly.material_index)
        if not rect:
            for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
                dst_data[li].uv = src_data[li].uv
            continue
        u0,v0,u1,v1 = rect; du=(u1-u0); dv=(v1-v0)
        for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
            su,sv = src_data[li].uv
            dst_data[li].uv = (u0 + su*du, v0 + sv*dv)

def _create_atlas_material(obj, base_path, norm_path, mat_name):
    mat = bpy.data.materials.new(mat_name); mat.use_nodes = True
    nt = mat.node_tree; nodes, links = nt.nodes, nt.links
    for n in list(nodes): nodes.remove(n)
    out = nodes.new('ShaderNodeOutputMaterial'); out.location = (420, 0)
    bsdf = nodes.new('ShaderNodeBsdfPrincipled'); bsdf.location = (140, 0)
    links.new(bsdf.outputs['BSDF'], out.inputs['Surface'])
    tex_d = nodes.new('ShaderNodeTexImage'); tex_d.location = (-180, 80)
    tex_d.image = bpy.data.images.load(base_path)
    tex_n = nodes.new('ShaderNodeTexImage'); tex_n.location = (-180, -240)
    tex_n.image = bpy.data.images.load(norm_path)
    try: tex_n.image.colorspace_settings.name = 'Non-Color'
    except Exception: pass
    nmap = nodes.new('ShaderNodeNormalMap'); nmap.location = (20, -240)
    uv = nodes.new('ShaderNodeUVMap'); uv.location = (-380, -80); uv.uv_map = UV_NAME
    links.new(uv.outputs['UV'], tex_d.inputs['Vector'])
    links.new(uv.outputs['UV'], tex_n.inputs['Vector'])
    links.new(tex_d.outputs['Color'], bsdf.inputs['Base Color'])
    links.new(tex_n.outputs['Color'], nmap.inputs['Color'])
    links.new(nmap.outputs['Normal'], bsdf.inputs['Normal'])
    obj.data.materials.clear(); obj.data.materials.append(mat); obj.active_material = mat

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
    Image, ImageOps = _get_pil()
    slot_images = []
    for idx, mat in enumerate(obj.data.materials):
        if not mat or not mat.use_nodes or not mat.node_tree:
            continue
        nt = mat.node_tree; bsdf = _find_principled(nt)
        if not bsdf: continue
        base_node = _find_basecolor_image_node(nt, bsdf)
        normal_node = _find_normal_image_node(nt, bsdf)
        base_img = base_node.image if base_node else None
        normal_img = normal_node.image if normal_node else None
        def save_img(img):
            if not img: return None
            src = _abspath(img.filepath)
            if src and os.path.exists(src): return src
            name = (img.name or 'Image').replace('.', '_').replace(' ', '_')
            path = os.path.join(tmp_dir, f"{name}.png")
            img.filepath_raw = path; img.file_format = 'PNG'; img.save(); return path
        base_path = save_img(base_img)
        normal_path = save_img(normal_img)
        slot_images.append({'slot_index': idx, 'slot_name': mat.name, 'base_path': base_path, 'normal_path': normal_path})
    if not slot_images:
        raise RuntimeError('No textures found in material slots (Base Color / Normal).')
    base_atlas_path, normal_atlas_path, manifest = _build_atlases(slot_images, out_dir, base_name)
    bpy.ops.object.select_all(action='DESELECT'); obj.select_set(True); bpy.context.view_layer.objects.active = obj
    bpy.ops.object.duplicate(); dup = bpy.context.active_object; dup.name = f"{obj.name}_ATLAS"
    _create_atlas_material(dup, base_atlas_path, normal_atlas_path, MATERIAL_NAME)
    if SRC_UV_NAME:
        src_uv = SRC_UV_NAME
    else:
        uvs = obj.data.uv_layers
        if len(uvs) == 0: raise RuntimeError('The active object has no UV layers.')
        src_uv = None
        for uv in uvs:
            if uv.active_render: src_uv = uv.name; break
        if not src_uv: src_uv = uvs.active.name
    _remap_uvs_to_atlas(dup, src_uv, UV_NAME, manifest['rects_uv_by_slot_index'])
    try:
        bpy.ops.file.pack_all()
    except Exception as e:
        print('Pack warning:', e)
    print(f"[DONE] Created '{dup.name}' with one material and atlases at: {out_dir}")
    print(f"  BaseColor: {base_atlas_path}")
    print(f"  Normal:    {normal_atlas_path}")
    print(f"  UV Map:    {UV_NAME} (mapped by material slot)")

if __name__ == '__main__':
    main()
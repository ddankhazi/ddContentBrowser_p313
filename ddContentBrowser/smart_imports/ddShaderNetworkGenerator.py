# -*- coding: utf-8 -*-
from __future__ import print_function, division

import os
import re
import json
import glob

import maya.cmds as cmds

# -------------------------------
# Config loading (JSON sidecar)
# -------------------------------

_DEFAULT_CONFIG = {
    "channel_aliases": {
        "baseColor": ["basecolor", "base_color", "base", "albedo", "diffuse", "diff", "color", "col"],
        "roughness": ["roughness", "rough", "glossiness", "gloss"],
        "metalness": ["metalness", "metallic", "metal", "met"],
        "normal": ["normal", "normalmap", "nrm", "nor", "norm"],
        "height": ["height", "heightmap", "bumpheight"],
        "displacement": ["displacement", "disp", "displ", "displace"],
        "emission": ["emission", "emissive", "emit"],
        "opacity": ["opacity", "alpha", "cutout", "cutoutopacity", "mask"],
        "transmission": ["transmission", "trans", "refraction", "refract", "glass"]
    },
    "material_suffixes_to_strip": [
        r"_MAT$", r"_mat$", r"_aiStandardSurface$", r"_openPBR$", r"_Mtl$", r"_mtl$", r"_dGecko$", r"_openPBRSurface$"
    ],

    # Global defaults (NO .tx, NO .exr)
    "extension_priority": [".tif", ".tiff", ".png", ".jpg", ".jpeg"],
    "accept_extensions":   [".tif", ".tiff", ".png", ".jpg", ".jpeg"],

    # Channel-specific overrides
    "accept_extensions_per_channel": {
        "displacement": [".exr", ".tif", ".tiff", ".png", ".jpg", ".jpeg"]
    },
    "extension_priority_per_channel": {
        "displacement": [".exr", ".tif", ".tiff", ".png", ".jpg", ".jpeg"]
    },

    "udim_regex": r"(?:[\._-])(1\d{3})(?=[\._-]|$)",
    "scan_depth": 1,
    "openpbr_nits_per_unit_fallback": 1000.0
}



def _load_config():
    # Try to load config JSON sitting next to this script (same folder, name + .json)
    this_file = os.path.abspath(__file__)
    base, _ = os.path.splitext(this_file)
    candidate = base + ".json"
    if os.path.exists(candidate):
        try:
            with open(candidate, "r") as f:
                data = json.load(f)
                return _merge_dicts(_DEFAULT_CONFIG, data)
        except Exception as e:
            print("[ShaderGen] Failed to load JSON config: {0}".format(e))
    return _DEFAULT_CONFIG


def _merge_dicts(base_dict, override_dict):
    # Deep-merge for dict-of-dicts
    out = dict(base_dict)
    for k, v in override_dict.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            sub = dict(out[k])
            sub.update(v)
            out[k] = sub
        else:
            out[k] = v
    return out


CONFIG = _load_config()

# -------------------------------
# Utility helpers
# -------------------------------

def _get_project_sourceimages():
    try:
        root = cmds.workspace(q=True, rootDirectory=True)
        rule = cmds.workspace(fileRuleEntry="sourceImages")
        rel = rule or "sourceimages"
        p = os.path.normpath(os.path.join(root, rel))
        return p
    except Exception:
        return os.path.join(os.getcwd(), "sourceimages")


def _choose_folder(default_dir):
    if not os.path.isdir(default_dir):
        default_dir = os.path.expanduser("~")
    sel = cmds.fileDialog2(dir=default_dir, fm=3, ds=2, okc="Use Folder")
    if sel and len(sel):
        return sel[0]
    return None


def _ls_unique(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def _shapes_from_selection():
    sel = cmds.ls(sl=True, long=True) or []
    if not sel:
        print("[ShaderGen] Nothing selected.")
        return []
    shapes = []
    for n in sel:
        if cmds.nodeType(n) in ("mesh", "nurbsSurface", "subdiv"):
            shapes.append(n)
        else:
            kids = cmds.listRelatives(n, shapes=True, noIntermediate=True, fullPath=True) or []
            for k in kids:
                if cmds.nodeType(k) in ("mesh", "nurbsSurface", "subdiv"):
                    shapes.append(k)
    return _ls_unique(shapes)

def _channel_dst_attr(material, channel):
    t = cmds.nodeType(material)

    def _first_existing(candidates):
        for a in candidates:
            if cmds.attributeQuery(a, node=material, exists=True):
                return a
        return None

    if t == "openPBRSurface":
        mapping = {
            "baseColor":    ["baseColor"],
            "roughness":    ["specularRoughness"],
            "metalness":    ["baseMetalness"],
            "normal":       ["normalCamera"],
            "emission":     ["emissionColor"],
            # prefer scalar geometryOpacity, fall back to the older color-style names if present
            "opacity":      ["geometryOpacity", "opacity", "cutoutOpacity"],
            "transmission": ["transmission", "transmissionWeight", "baseTransmission"],
        }

    else:  # aiStandardSurface
        mapping = {
            "baseColor":    ["baseColor"],
            "roughness":    ["specularRoughness"],
            "metalness":    ["metalness"],
            "normal":       ["normalCamera"],
            "emission":     ["emissionColor"],
            "opacity":      ["opacity"],          # cutout/alpha
            "transmission": ["transmission"],     # weight
        }
    return _first_existing(mapping.get(channel, []))

def _is_scalar_attr(node, attr):
    """True if the dest plug is a scalar (double/float/bool), else False."""
    try:
        atype = cmds.getAttr("{}.{}".format(node, attr), type=True)
        return atype in ("double", "float", "bool")
    except Exception:
        return False


def _get_arnold_nits_per_unit(default_val=1000.0):
    """Read Arnold's nits_per_unit from defaultArnoldRenderOptions if available; else fallback."""
    try:
        node = "defaultArnoldRenderOptions"
        if cmds.objExists(node) and cmds.attributeQuery("nits_per_unit", node=node, exists=True):
            v = cmds.getAttr(node + ".nits_per_unit")
            if v and v > 0:
                return float(v)
    except Exception:
        pass
    # optional config override; else use hard fallback
    return float(CONFIG.get("openpbr_nits_per_unit_fallback", default_val))


def _materials_from_shapes(shapes):
    sgs = set()
    for sh in shapes:
        con = cmds.listConnections(sh, type="shadingEngine") or []
        for sg in con:
            sgs.add(sg)
    mats = set()
    for sg in sgs:
        m = cmds.connectionInfo(sg + ".surfaceShader", sfd=True)
        if m and "." in m:
            m = m.split(".")[0]
        if not m or not cmds.objExists(m):
            continue
        t = cmds.nodeType(m)
        if t in ("aiStandardSurface", "openPBRSurface"):
            mats.add(m)
    return sorted(list(mats))


def _dst_has_input(dst_attr):
    """Return True if dst_attr already has an incoming connection."""
    return bool(cmds.listConnections(dst_attr, s=True, d=False, plugs=True))

def _find_file_node_by_path(path_or_pattern):
    """Return the first file node whose fileTextureName equals the given path_or_pattern (exact match)."""
    for n in cmds.ls(type="file") or []:
        try:
            v = cmds.getAttr(n + ".fileTextureName")
        except Exception:
            continue
        if v == path_or_pattern:
            return n
    return None


def _derive_tex_roots(material_name):
    roots = [material_name]
    # strip configured suffixes to create additional candidates
    for pat in CONFIG.get("material_suffixes_to_strip", []):
        stripped = re.sub(pat, "", material_name, flags=re.IGNORECASE)
        if stripped and stripped != material_name and stripped not in roots:
            roots.append(stripped)
    # Also add upper/lower variants just in case
    low = material_name.lower()
    if low not in [r.lower() for r in roots]:
        roots.append(material_name.lower())
    return roots

_FILE_SCAN_CACHE = {}

def _gather_files(base_dir, acc_exts, depth):
    """Return files in base_dir and, if depth>=1, in its immediate subfolders. Cached."""
    key = (os.path.abspath(base_dir), tuple(sorted([e.lower() for e in acc_exts])), int(depth))
    if key in _FILE_SCAN_CACHE:
        return list(_FILE_SCAN_CACHE[key])

    files = []
    # Top level
    for ext in acc_exts:
        files.extend(glob.glob(os.path.join(base_dir, "*{0}".format(ext))))
    # One level down
    if depth >= 1:
        for ext in acc_exts:
            files.extend(glob.glob(os.path.join(base_dir, "*", "*{0}".format(ext))))

    files = [os.path.normpath(p) for p in files]
    # Never consider .tx
    files = [p for p in files if os.path.splitext(p)[1].lower() != ".tx"]

    _FILE_SCAN_CACHE[key] = files
    return list(files)

def _scan_textures_for_channel(base_dir, roots, channel_key):
    # before:
    # aliases = CONFIG["channel_aliases"].get(channel_key, [])
    # after:
    aliases = [a for a in CONFIG["channel_aliases"].get(channel_key, []) if len(a) >= 3]
    if not aliases:
        return (None, False)


    # Choose per-channel accept/priority, falling back to global defaults
    acc_exts = (CONFIG.get("accept_extensions_per_channel", {}).get(channel_key)
                or CONFIG.get("accept_extensions", []))
    pri_list = (CONFIG.get("extension_priority_per_channel", {}).get(channel_key)
                or CONFIG.get("extension_priority", []))

    acc_exts = [e.lower() for e in acc_exts]
    depth = int(CONFIG.get("scan_depth", 0))
    all_files = _gather_files(base_dir, acc_exts, depth)

    # Pre-sort by extension priority
    ext_priority = {ext: i for i, ext in enumerate(pri_list)}
    def _score(p):
        ext = os.path.splitext(p)[1].lower()
        return ext_priority.get(ext, 999)
    all_files.sort(key=_score)

    # Build regex patterns with separator boundaries around alias
    roots_escaped = [re.escape(r) for r in roots]
    alias_group = "|".join([re.escape(a) for a in aliases])

    tight_re_list = []
    for rpat in roots_escaped:
        tight_re_list.append(re.compile(
            r"^" + rpat + r"(?:[_\.-])(" + alias_group + r")(?:[\._-]|$)",
            re.IGNORECASE
        ))

    loose_re_list = []
    for rpat in roots_escaped:
        loose_re_list.append(re.compile(
            r"^" + rpat + r".*(?:[_\.-])(" + alias_group + r")(?:[\._-]|$)",
            re.IGNORECASE
        ))

    udim_re = re.compile(CONFIG.get("udim_regex", r"(?:[\._-])(1\d{3})(?=[\._-]|$)"))

    def _as_udim_pattern(path):
        # Replace the matched UDIM digits with <UDIM>
        bn = os.path.basename(path)
        m = udim_re.search(bn)
        if not m:
            return (path, False)
        start, end = m.span(1)
        udimified = bn[:start] + "<UDIM>" + bn[end:]
        return (os.path.join(os.path.dirname(path), udimified), True)

    # Pass 1: tight
    for f in all_files:
        name = os.path.basename(f)
        for cre in tight_re_list:
            if cre.search(name):
                return _as_udim_pattern(f)

    # Pass 2: loose
    for f in all_files:
        name = os.path.basename(f)
        for cre in loose_re_list:
            if cre.search(name):
                return _as_udim_pattern(f)

    return (None, False)


def _set_file_colorspace(node, colorspace):
    """Force a specific color space and disable file-rule auto mapping."""
    try:
        if cmds.attributeQuery("ignoreColorSpaceFileRules", node=node, exists=True):
            cmds.setAttr(node + ".ignoreColorSpaceFileRules", 1)
    except Exception:
        pass
    try:
        if cmds.attributeQuery("colorSpace", node=node, exists=True):
            cmds.setAttr(node + ".colorSpace", colorspace, type="string")
    except Exception:
        pass

def _get_or_create_shared_place2d(material):
    """Return a single shared place2dTexture node for this material."""
    base_name = material + "_place2d"
    if cmds.objExists(base_name) and cmds.nodeType(base_name) == "place2dTexture":
        return base_name
    # Create (Maya may uniquify the name, so capture the actual name)
    node = cmds.shadingNode("place2dTexture", asUtility=True, n=base_name)
    return node

def _get_sg_nodes_for_material(material):
    """Return all shadingEngine nodes driving this material's surfaceShader."""
    sgs = set()
    # Find SGs by following outgoing connections from material.surfaceShader back to SGs
    cons = cmds.listConnections(material, d=True, s=False, type="shadingEngine") or []
    for sg in cons:
        # Verify it's actually the surfaceShader plug
        src = cmds.connectionInfo(sg + ".surfaceShader", sfd=True)
        if src and src.split(".")[0] == material:
            sgs.add(sg)
    # Fallback: scan all SGs and match surfaceShader
    if not sgs:
        for sg in cmds.ls(type="shadingEngine") or []:
            src = cmds.connectionInfo(sg + ".surfaceShader", sfd=True)
            if src and src.split(".")[0] == material:
                sgs.add(sg)
    return sorted(sgs)

def _ensure_displacement_shader(name):
    """Create or reuse a Maya displacementShader node."""
    if cmds.objExists(name) and cmds.nodeType(name) == "displacementShader":
        return name
    return cmds.shadingNode("displacementShader", asShader=True, n=name)


def _ensure_floatMath(name):
    if cmds.objExists(name) and cmds.nodeType(name) == "floatMath":
        return name
    return cmds.shadingNode("floatMath", asUtility=True, n=name)

def _map_material_to_shapes(shapes):
    """Return {material: [shapes]} for supported materials on the given shapes."""
    result = {}
    for sh in shapes:
        sgs = cmds.listConnections(sh, type="shadingEngine") or []
        for sg in sgs:
            src = cmds.connectionInfo(sg + ".surfaceShader", sfd=True)
            if not src or "." not in src:
                continue
            mat = src.split(".")[0]
            if not cmds.objExists(mat):
                continue
            if cmds.nodeType(mat) in ("aiStandardSurface", "openPBRSurface"):
                result.setdefault(mat, []).append(sh)
    return result


def _set_shape_disp_settings(shapes):
    """Apply displacement-friendly settings on the given mesh shapes."""
    _ensure_mtoa()  # ensures ai* attrs exist
    for sh in shapes:
        # Smooth Mesh preview / render linkage
        try:
            if cmds.attributeQuery("smoothLevel", node=sh, exists=True):
                cmds.setAttr(sh + ".smoothLevel", 1)
        except Exception:
            pass
        try:
            if cmds.attributeQuery("useSmoothPreviewForRender", node=sh, exists=True):
                cmds.setAttr(sh + ".useSmoothPreviewForRender", 0)
        except Exception:
            pass
        try:
            if cmds.attributeQuery("renderSmoothLevel", node=sh, exists=True):
                cmds.setAttr(sh + ".renderSmoothLevel", 0)
        except Exception:
            pass

        # Arnold subdivision + displacement padding
        try:
            if cmds.attributeQuery("aiSubdivType", node=sh, exists=True):
                cmds.setAttr(sh + ".aiSubdivType", 1)  # 1 = catclark
        except Exception:
            pass
        try:
            if cmds.attributeQuery("aiSubdivIterations", node=sh, exists=True):
                cmds.setAttr(sh + ".aiSubdivIterations", 4)
        except Exception:
            pass
        try:
            if cmds.attributeQuery("aiDispPadding", node=sh, exists=True):
                cmds.setAttr(sh + ".aiDispPadding", 10)
        except Exception:
            pass


def _create_file_node(label, texture_path_or_pattern, is_udim, colorspace, place2d=None):
    name = label + "_file"
    created_new = False

    # Prefer a named node if it exists
    node = name if cmds.objExists(name) and cmds.nodeType(name) == "file" else None

    # Else, try to reuse any file node already pointing to this path/pattern
    if not node:
        node = _find_file_node_by_path(texture_path_or_pattern)

    # Else, create a new node
    if not node:
        node = cmds.shadingNode("file", asTexture=True, isColorManaged=True, n=name)
        created_new = True

    # If node has no file path set yet, set it. Do not overwrite an existing, different path.
    try:
        current_path = cmds.getAttr(node + ".fileTextureName")
    except Exception:
        current_path = ""
    if not current_path:
        cmds.setAttr(node + ".fileTextureName", texture_path_or_pattern, type="string")

    # UDIM handling (do not flip existing non-empty paths unless matching)
    if is_udim:
        if cmds.attributeQuery("uvTilingMode", node=node, exists=True):
            cmds.setAttr(node + ".uvTilingMode", 3)  # 3 = UDIM
        # Ensure the <UDIM> token form if our discovered pattern had a concrete tile and node is still empty or matches
        if "<UDIM>" not in (cmds.getAttr(node + ".fileTextureName") or ""):
            bn = os.path.basename(texture_path_or_pattern)
            udim_re = re.compile(CONFIG.get("udim_regex", r"(?:[\._-])(1\d{3})(?=[\._-]|$)"))
            m = udim_re.search(bn)
            if m and (not current_path or current_path == texture_path_or_pattern):
                s, e = m.span(1)
                ud = bn[:s] + "<UDIM>" + bn[e:]
                ud = os.path.join(os.path.dirname(texture_path_or_pattern), ud)
                cmds.setAttr(node + ".fileTextureName", ud, type="string")

    # Force color space and ignore file-rule mapping
    _set_file_colorspace(node, colorspace)

    # Ensure place2d connections exist. Only wire if missing.
    # Check one canonical connection to decide (coverage is reliable).
    try:
        has_p2d = bool(cmds.listConnections(node + ".coverage", s=True, d=False))
    except Exception:
        has_p2d = False

    if not has_p2d:
        # Use provided shared place2d, or create a private one as a fallback
        if place2d and cmds.objExists(place2d):
            p2d = place2d
        else:
            p2d = cmds.shadingNode("place2dTexture", asUtility=True, n=label + "_place2d")

        for a in ["coverage", "translateFrame", "rotateFrame", "mirrorU", "mirrorV", "stagger",
                  "wrapU", "wrapV", "repeatUV", "offset", "rotateUV", "noiseUV", "vertexUvOne",
                  "vertexUvTwo", "vertexUvThree", "vertexCameraOne"]:
            try:
                cmds.connectAttr(p2d + "." + a, node + "." + a, f=True)
            except Exception:
                pass
        for a in ["outUV", "outUvFilterSize"]:
            try:
                cmds.connectAttr(p2d + "." + a, node + "." + a, f=True)
            except Exception:
                pass

    return node


def _ensure_mtoa():
    if not cmds.pluginInfo("mtoa", q=True, loaded=True):
        try:
            cmds.loadPlugin("mtoa")
        except Exception:
            print("[ShaderGen] Arnold plugin not available.")
            return False
    return True

def _ensure_emission_rayswitch(label, file_node, material):
    """Create/reuse an aiRaySwitch and wire emission through it."""
    if not _ensure_mtoa():
        return None

    rs_name = label + "_aiRaySwitch"
    if cmds.objExists(rs_name) and cmds.nodeType(rs_name) == "aiRaySwitch":
        rs = rs_name
    else:
        rs = cmds.shadingNode("aiRaySwitch", asUtility=True, n=rs_name)

    # Drive multiple ray types from the emission texture (non-destructive)
    for attr in ("hardwareColor", "camera", "specularReflection", "specularTransmission"):
        _connect_if_free(file_node + ".outColor", rs + "." + attr)

    # Connect rayswitch outColor to the shader emissionColor (don’t double-connect)
    _connect_if_free(rs + ".outColor", material + ".emissionColor")

    # Make sure emission is enabled/weighted, per shader type
    try:
        t = cmds.nodeType(material)
        if t == "openPBRSurface":
            if cmds.attributeQuery("emissionLuminance", node=material, exists=True):
                cur = cmds.getAttr(material + ".emissionLuminance")
                if not cur or cur == 0:
                    cmds.setAttr(material + ".emissionLuminance", _get_arnold_nits_per_unit())
        else:
            if cmds.attributeQuery("emission", node=material, exists=True):
                if cmds.getAttr(material + ".emission") == 0:
                    cmds.setAttr(material + ".emission", 1.0)
    except Exception:
        pass

    return rs


def _ensure_normal_chain(label, file_node, material):
    if not _ensure_mtoa():
        return None

    n_name = label + "_aiNormalMap"
    if cmds.objExists(n_name) and cmds.nodeType(n_name) == "aiNormalMap":
        n_node = n_name
    else:
        n_node = cmds.shadingNode("aiNormalMap", asUtility=True, n=n_name)

    # file -> aiNormalMap.input (only if free)
    _connect_if_free(file_node + ".outColor", n_node + ".input")
    # aiNormalMap.outValue -> material.normalCamera (only if free)
    _connect_if_free(n_node + ".outValue", material + ".normalCamera")

    return n_node


def _connect_if_free(src_attr, dst_attr):
    existing = cmds.listConnections(dst_attr, s=True, d=False, plugs=True) or []
    if existing:
        print("[ShaderGen] Skipping, already connected: {0}".format(dst_attr))
        return False
    cmds.connectAttr(src_attr, dst_attr, f=True)
    return True


def _connect_channel(material, channel, file_node):
    t = cmds.nodeType(material)
    dst_attr = _channel_dst_attr(material, channel)
    if not dst_attr:
        print("[ShaderGen] No dst attr for channel {0} on {1}".format(channel, t))
        return
    dst = material + "." + dst_attr

    if channel == "baseColor":
        _connect_if_free(file_node + ".outColor", dst)

    elif channel == "roughness":
        _connect_if_free(file_node + ".outColorR", dst)

    elif channel == "metalness":
        _connect_if_free(file_node + ".outColorR", dst)

    elif channel == "emission":
        # If already driven, skip; else create/reuse rayswitch and wire it
        if _dst_has_input(dst):
            print("[ShaderGen] emission already connected on {0}, skipping.".format(material))
            return
        _ensure_emission_rayswitch(material + "_emission", file_node, material)

    elif channel == "normal":
        _ensure_normal_chain(material + "_normal", file_node, material)

    elif channel == "opacity":
        # Use R for scalar plugs (e.g., openPBRSurface.geometryOpacity), else full color
        use_scalar = _is_scalar_attr(material, dst_attr)
        src = file_node + (".outColorR" if use_scalar else ".outColor")
        _connect_if_free(src, dst)


    elif channel == "transmission":
        # Weight is scalar
        _connect_if_free(file_node + ".outColorR", dst)

    else:
        print("[ShaderGen] Channel not wired in base version: {0}".format(channel))


def _build_for_material(material, base_dir, shapes_for_material):
    print("[ShaderGen] Material: {0}".format(material))
    roots = _derive_tex_roots(material)

    found = {}
    # Determine candidate textures for the key channels
    for ch in ["baseColor", "roughness", "metalness", "normal", "emission", "opacity", "transmission", "height", "displacement"]:
        tex, is_udim = _scan_textures_for_channel(base_dir, roots, ch)
        found[ch] = (tex, is_udim)

    # Create/get a single shared place2dTexture for this material
    shared_place2d = _get_or_create_shared_place2d(material)

    # Map channels to required colorspace and destination attrs for early skip
    channel_cs = {
        "baseColor": "sRGB",
        "emission":  "sRGB",
        "roughness": "Raw",
        "metalness": "Raw",
        "normal":    "Raw",
        "opacity":   "Raw",
        "transmission": "Raw",
        "height":    "Raw",
        "displacement": "Raw"
    }

    
    def _dst(material, ch):
        a = _channel_dst_attr(material, ch)
        return material + "." + a if a else None

    for ch in ["baseColor", "roughness", "metalness", "normal", "emission", "opacity", "transmission"]:
        dst = _dst(material, ch)
        if not dst:
            continue
        if _dst_has_input(dst):
            print("[ShaderGen] {0} already connected on {1}, skipping.".format(ch, material))
            continue
        tex, is_udim = found.get(ch, (None, False))
        if not tex:
            continue
        label = "{0}_{1}".format(material, ch)
        fnode = _create_file_node(label, tex, is_udim,
                                colorspace=channel_cs.get(ch, "Raw"),
                                place2d=shared_place2d)
        if ch == "normal":
            _ensure_normal_chain(material + "_normal", fnode, material)
        else:
            _connect_channel(material, ch, fnode)

    
    # --- Displacement selection: prefer 'displacement', else 'height' as displacement ---
    disp_src = None
    if found.get("displacement", (None, False))[0]:
        disp_src = "displacement"
    elif found.get("height", (None, False))[0]:
        disp_src = "height"

    if disp_src:
        # If any SG for this material already has a displacement input, skip building the chain
        sgs = _get_sg_nodes_for_material(material)
        if any(_dst_has_input(sg + ".displacementShader") for sg in sgs):
            _set_shape_disp_settings(shapes_for_material)  # still apply per-shape settings
            print("[ShaderGen] Displacement already connected on {0}, skipping chain.".format(material))
        else:
            disp_tex, disp_udim = found[disp_src]
            disp_label = "{0}_{1}".format(
                material, "displacement" if disp_src == "displacement" else "heightAsDisplacement"
            )

            # File node (Raw + ignore rules), reuse shared place2d
            disp_file = _create_file_node(
                disp_label, disp_tex, disp_udim, colorspace="Raw", place2d=shared_place2d
            )

            # floatMath nodes: offset then multiply
            offset_node = _ensure_floatMath("{0}_disp_offset".format(material))
            multiply_node = _ensure_floatMath("{0}_disp_multiply".format(material))

            # file.outColorR -> offset.floatA (only if free)
            _connect_if_free(disp_file + ".outColorR", offset_node + ".floatA")

            # offset.floatB: EXR uses signed (mid=0), others are [0..1] (mid=0.5 -> B=-0.5)
            try:
                ext = os.path.splitext(disp_tex)[1].lower()
                offset_val = 0.0 if ext == ".exr" else -0.5
                if cmds.getAttr(offset_node + ".floatB") != offset_val:
                    cmds.setAttr(offset_node + ".floatB", offset_val)
            except Exception:
                pass

            # offset.outFloat -> multiply.floatA (only if free)
            _connect_if_free(offset_node + ".outFloat", multiply_node + ".floatA")

            # multiply.operation = 2 (multiply)
            try:
                if cmds.getAttr(multiply_node + ".operation") != 2:
                    cmds.setAttr(multiply_node + ".operation", 2)
            except Exception:
                pass

            # displacementShader node
            disp_shd = _ensure_displacement_shader("{0}_displacementShader".format(material))

            # multiply.outFloat -> displacementShader.displacement (only if free)
            _connect_if_free(multiply_node + ".outFloat", disp_shd + ".displacement")

            # displacementShader.displacement -> SG.displacementShader (only if free)
            for sg in sgs:
                _connect_if_free(disp_shd + ".displacement", sg + ".displacementShader")

            # Apply per-shape settings to the originally selected shapes using this material
            _set_shape_disp_settings(shapes_for_material)

            print("[ShaderGen] Using {0} as displacement for {1}".format(disp_src, material))



def run(base_dir=None):
    global _FILE_SCAN_CACHE
    _FILE_SCAN_CACHE = {}

    shapes = _shapes_from_selection()
    if not shapes:
        return

    mat_to_shapes = _map_material_to_shapes(shapes)
    mats = sorted(mat_to_shapes.keys())
    if not mats:
        print("[ShaderGen] No supported materials (aiStandardSurface/openPBRSurface) found on selection.")
        return

    if base_dir is None:
        default_dir = _get_project_sourceimages()
        base_dir = _choose_folder(default_dir)
        if not base_dir:
            print("[ShaderGen] Aborted. No folder chosen.")
            return

    print("[ShaderGen] Using texture folder: {0}".format(base_dir))

    for m in mats:
        _build_for_material(m, base_dir, mat_to_shapes[m])

    print("[ShaderGen] Done.")


"""Build static Blender/FBX/GLB previews from got_assets.py JSON.

Blender --background --factory-startup --python this.py -- --output DIR
--textures DIR [--textures DIR ...] INPUT.json [INPUT.json ...]
Source positions remain Z-up and are scaled from assumed cm to Blender metres.
Preview materials use diffuse/alpha only, not the original game shaders.
"""

import argparse
from array import array
import json
import math
from pathlib import Path
import sys

import bpy
from mathutils import Vector


def material(part, texture_dirs):
    names = [t['name'] for t in part['metadata']['textures']]
    diffuse = next((n for n in names if ('.msac.d.' in n and 'tint' not in n) or 'pampas_fluff' in n), None)
    if diffuse == 'foliage_dl_pampasgrass_001.msac.d.0.sps':
        basename = 'pampas_d.png'
    elif diffuse == 'fxt_or_034_pampas_fluff.psd.0.sps':
        basename = 'pampas_fluff.png'
    else:
        basename = Path(diffuse).stem + '.png' if diffuse else None
    path = next((d / basename for d in texture_dirs if basename and (d / basename).is_file()), None)
    mat = bpy.data.materials.new('Preview_' + (diffuse or part['hash']))
    mat.use_nodes = True
    mat.surface_render_method = 'DITHERED'
    mat.use_backface_culling = False
    shader = mat.node_tree.nodes.get('Principled BSDF')
    shader.inputs['Roughness'].default_value = 0.8
    if path:
        image = bpy.data.images.load(str(path), check_existing=True)
        image.colorspace_settings.name = 'sRGB'
        pixels = array('f', [0]) * len(image.pixels)
        image.pixels.foreach_get(pixels)
        print(f'TEXTURE {path.name}: {tuple(image.size)}, alpha={min(pixels[3::4]):.3f}..{max(pixels[3::4]):.3f}')
        tex = mat.node_tree.nodes.new('ShaderNodeTexImage')
        tex.image = image
        mat.node_tree.links.new(tex.outputs['Color'], shader.inputs['Base Color'])
        mat.node_tree.links.new(tex.outputs['Alpha'], shader.inputs['Alpha'])
        # Small emission keeps diagnostic atlas shapes visible in unlit card backs.
        mat.node_tree.links.new(tex.outputs['Color'], shader.inputs['Emission Color'])
        shader.inputs['Emission Strength'].default_value = 0.12
    else:
        shader.inputs['Base Color'].default_value = (0.36, 0.42, 0.28, 1)
    mat['preview_only'] = True
    return mat


def make_mesh(part, texture_dirs, index):
    mesh = bpy.data.meshes.new(f'Part_{index}_{part["hash"]}')
    positions = [[v / 100 for v in p] for p in part['positions']]
    indices = part['indices']
    triangles = [indices[i:i + 3] for i in range(0, len(indices), 3)]
    mesh.from_pydata(positions, [], triangles)
    mesh.update()
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    if part['normals']:
        mesh.normals_split_custom_set_from_vertices([Vector(n).normalized() for n in part['normals']])
    for index_uv, values in enumerate(part['uvs']):
        layer = mesh.uv_layers.new(name=f'UV{index_uv}')
        for loop in mesh.loops:
            u, v = values[loop.vertex_index]
            layer.data[loop.index].uv = (u, 1 - v)
    for index_color, values in enumerate(part['colors']):
        layer = mesh.color_attributes.new(name=f'SourceColor{index_color}', type='FLOAT_COLOR', domain='POINT')
        for i, value in enumerate(values):
            layer.data[i].color = value
    for index_vector, entry in enumerate(part['extra_vectors']):
        layer = mesh.attributes.new(name=f'_SOURCE_VECTOR_{entry["format"]}_{index_vector}', type='FLOAT_VECTOR', domain='POINT')
        for i, value in enumerate(entry['values']):
            layer.data[i].vector = value
    obj = bpy.data.objects.new(mesh.name, mesh)
    bpy.context.collection.objects.link(obj)
    obj['source_identifier'] = part.get('identifier', part['hash'])
    obj['source_record_offset'] = part['metadata']['record_offset']
    obj['unconverted_formats'] = json.dumps(part['unconverted_formats'])
    obj.data.materials.append(material(part, texture_dirs))
    assert len(mesh.vertices) == len(positions) and len(mesh.polygons) == len(triangles)
    assert len(mesh.uv_layers) == len(part['uvs'])
    return obj


def setup_render(objects):
    scene = bpy.context.scene
    points = [v.co for obj in objects for v in obj.data.vertices]
    minimum = Vector([min(p[k] for p in points) for k in range(3)])
    maximum = Vector([max(p[k] for p in points) for k in range(3)])
    center = (minimum + maximum) / 2
    extent = max(maximum - minimum)
    scene.render.engine = 'CYCLES'
    scene.cycles.samples = 24
    scene.cycles.use_denoising = True
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    if scene.world is None:
        scene.world = bpy.data.worlds.new('PreviewWorld')
    scene.world.use_nodes = True
    scene.world.node_tree.nodes['Background'].inputs[0].default_value = (0.32, 0.36, 0.42, 1)
    scene.world.node_tree.nodes['Background'].inputs[1].default_value = 0.8
    camera = bpy.data.objects.new('PreviewCamera', bpy.data.cameras.new('PreviewCamera'))
    scene.collection.objects.link(camera)
    camera.location = center + Vector((0.25, -1.6, 0.7)) * extent
    camera.rotation_euler = (center - camera.location).to_track_quat('-Z', 'Y').to_euler()
    camera.data.type = 'ORTHO'
    inverse_rotation = camera.rotation_euler.to_matrix().transposed()
    projected = [inverse_rotation @ (point - center) for point in points]
    width = max(p.x for p in projected) - min(p.x for p in projected)
    height = max(p.y for p in projected) - min(p.y for p in projected)
    camera.data.ortho_scale = max(width, height * 1400 / 900) * 1.15
    scene.camera = camera
    for i, direction in enumerate([(0.5, -0.6, 1.0), (-0.5, 0.4, 0.7)]):
        light = bpy.data.objects.new(f'PreviewLight{i}', bpy.data.lights.new(f'PreviewLight{i}', 'AREA'))
        scene.collection.objects.link(light)
        light.location = center + Vector(direction) * extent
        light.rotation_euler = (center - light.location).to_track_quat('-Z', 'Y').to_euler()
        light.data.energy = 150 * extent ** 2
        light.data.shape = 'DISK'
        light.data.size = extent * 0.8
    scene.view_settings.view_transform = 'AgX'


def verify_fbx(path, source_objects):
    expected = dict(vertices=sum(len(o.data.vertices) for o in source_objects),
                    triangles=sum(len(o.data.polygons) for o in source_objects),
                    meshes=len(source_objects),
                    uv_layers=[len(o.data.uv_layers) for o in source_objects])
    source_points = [o.matrix_world @ v.co for o in source_objects for v in o.data.vertices]
    source_bounds = [[min(v[k] for v in source_points), max(v[k] for v in source_points)] for k in range(3)]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(path))
    objects = [o for o in bpy.context.scene.objects if o.type == 'MESH']
    actual = dict(vertices=sum(len(o.data.vertices) for o in objects),
                  triangles=sum(len(o.data.polygons) for o in objects), meshes=len(objects),
                  uv_layers=[len(o.data.uv_layers) for o in objects])
    assert actual == expected, (expected, actual)
    imported_points = [o.matrix_world @ v.co for o in objects for v in o.data.vertices]
    imported_bounds = [[min(v[k] for v in imported_points), max(v[k] for v in imported_points)] for k in range(3)]
    bounds_error = max(abs(source_bounds[k][i] - imported_bounds[k][i]) for k in range(3) for i in range(2))
    assert bounds_error < 0.0001, bounds_error
    print(f'FBX VERIFIED: {actual}')
    return dict(expected=expected, actual=actual, bounds_error_metres=bounds_error, passed=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--textures', type=Path, action='append', default=[])
    parser.add_argument('inputs', type=Path, nargs='+')
    args = parser.parse_args(sys.argv[sys.argv.index('--') + 1:])
    args.output = args.output.resolve()
    args.textures = [p.resolve() for p in args.textures]
    args.inputs = [p.resolve() for p in args.inputs]
    args.output.mkdir(parents=True, exist_ok=True)
    for source in args.inputs:
        output = args.output / source.stem
        if output.exists() and any(output.iterdir()):
            raise ValueError(f'Output must be empty: {output}')
        output.mkdir(exist_ok=True)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        data = json.loads(source.read_text('utf-8'))
        objects = [make_mesh(p, args.textures, i) for i, p in enumerate(data['parts'])]
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0]
        fbx = output / (source.stem + '.fbx')
        bpy.ops.export_scene.fbx(filepath=str(fbx), use_selection=True, object_types={'MESH'},
                                 axis_forward='-Y', axis_up='Z', use_mesh_modifiers=False,
                                 add_leaf_bones=False, bake_anim=False, path_mode='COPY', embed_textures=True)
        bpy.ops.export_scene.gltf(filepath=str(output / (source.stem + '.glb')), export_format='GLB',
                                 use_selection=True, export_extras=True, export_all_vertex_colors=True, export_attributes=True)
        setup_render(objects)
        bpy.ops.wm.save_as_mainfile(filepath=str(output / (source.stem + '.blend')))
        bpy.context.scene.render.filepath = str(output / 'preview.png')
        bpy.ops.render.render(write_still=True)
        report = verify_fbx(fbx, objects)
        report.update(source_json=str(source.resolve()), units='Assumed source cm to Blender m; no axis rotation',
                      limitations='Static diffuse/alpha preview. Game shaders, hierarchy/wind data and source LOD selection are not reconstructed.')
        (output / 'verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')


if __name__ == '__main__':
    main()
